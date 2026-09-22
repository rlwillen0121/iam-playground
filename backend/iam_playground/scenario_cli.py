"""Scenario, smoke, and redacted export commands for ./lab."""

from __future__ import annotations

import copy
import json
import os
import re
import sys
import secrets as token_source
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from iam_playground.constants import FIXTURE_ID, LOOPBACK_ENDPOINTS
from iam_playground.envfile import load_env
from iam_playground.fixture import idp_user_uuid
from iam_playground.net import fetch_json

_ROOT = Path(__file__).resolve().parents[2]
for _folder in ("clients/verifier", "clients/reference"):
    _path = str(_ROOT / _folder)
    if _path not in sys.path:
        sys.path.insert(0, _path)

from redact import RedactionError, redact, require_redacted
from scenario_scim_login_revoke import FLAGSHIP, DriverStopped, run_scim_login_revoke
from verifier import expectation_from, verify

TARGET_BASE = LOOPBACK_ENDPOINTS["target"]
ADMIN_BASE = LOOPBACK_ENDPOINTS["admin"]
REQUIRED_ENV = ("SCIM_TOKEN_APP_A", "SCIM_TOKEN_APP_A_READ", "LAB_ADMIN_TOKEN")
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")

CONTRACT = {
    "scenario_id": "scim-login-revoke",
    "scenario_version": "1",
    "fixture_id": FIXTURE_ID,
    "required_capabilities": ["scim-app-a", "admin-binding", "demo-session-probe"],
    "preconditions": [
        "target /healthz is ready",
        "admin /healthz is ready",
        "app-a has Readers and Administrators",
    ],
    "allowed_changes": [
        "create scim user alice on app-a",
        "bind the caller-supplied subject",
        "add Readers",
        "add Administrators",
        "remove Administrators",
        "set active false",
    ],
    "protected_state": [
        "app-b is not changed by this driver",
        "final app-a membership is Readers only",
    ],
    "deadline_seconds": 60,
    "cleanup": "no automatic delete; ./lab reset --fixture enterprise-small-v1",
    "mode": "reference",
}


class EnvError(Exception):
    def __init__(self, key: str, reason: str) -> None:
        super().__init__(reason)
        self.key = key
        self.reason = reason


def lab_root() -> Path:
    return Path(os.environ.get("LAB_ROOT", ".")).resolve()


def scenario_list_lines(root: Path) -> list[str]:
    """Flagship first, then each scenarios/*.json id. Rollback stays unavailable."""
    lines = ["scim-login-revoke"]
    folder = root / "scenarios"
    if not folder.is_dir():
        return lines
    seen = {"scim-login-revoke"}
    for path in sorted(folder.glob("*.json")):
        scenario_id = _id_from_scenario(path)
        if scenario_id is None or scenario_id in seen:
            continue
        seen.add(scenario_id)
        if scenario_id == "transaction-rollback":
            lines.append("transaction-rollback is unavailable")
        else:
            lines.append(scenario_id)
    return lines


def _id_from_scenario(path: Path) -> str | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict):
        return None
    scenario_id = document.get("id")
    if not isinstance(scenario_id, str) or scenario_id == "":
        return None
    return scenario_id


def alice_subject() -> str:
    """Keycloak subject baked into the fixture. Not a database lookup."""
    return str(idp_user_uuid("alice"))


def verdict_exit(verdict: str) -> int:
    if verdict == "PASSED":
        return 0
    if verdict == "INDETERMINATE":
        return 2
    return 1


def execute_reference(
    root: Path,
    *,
    health: Callable[[], list[str]],
    drive: Callable[[], dict[str, Any]],
    check: Callable[[dict[str, Any] | None], dict[str, Any]],
    secret_values: Callable[[], Sequence[str]],
) -> int:
    """Run one mutating scenario. The lock is removed in a finally block."""
    runs = root / ".lab-runs"
    runs.mkdir(parents=True, exist_ok=True)
    os.chmod(runs, 0o700)
    lock = runs / "active"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        print(
            "scenario: a run is active. Wait for it to finish or reset: "
            "./lab reset --fixture enterprise-small-v1",
            file=sys.stderr,
        )
        return 1
    try:
        try:
            os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
        finally:
            os.close(descriptor)
        problems = health()
        if problems:
            for line in problems:
                print(line, file=sys.stderr)
            return 1
        started = _iso_now()
        contract = copy.deepcopy(CONTRACT)
        requested: dict[str, Any] | None = None
        completed = False
        try:
            requested = drive()
            completed = True
        except EnvError as exc:
            print(f"env: {exc.key} {exc.reason}. Next: ./lab up", file=sys.stderr)
            return 1
        except DriverStopped as stopped:
            requested = stopped.as_dict()
        except Exception:
            requested = None
        observed = check(requested)
        if not _valid_observed(observed):
            observed = {
                "verdict": "INDETERMINATE",
                "missing": ["verifier"],
                "assertions": [],
                "observations": {},
            }
        run_id = _new_run_id()
        report = _assemble(run_id, started, contract, requested, observed, completed)
        extras = [item for item in secret_values() if isinstance(item, str)]
        cleaned = redact(report, extras)
        require_redacted(cleaned, extras)
        _write_json(runs / f"{run_id}.json", cleaned)
        print(cleaned["verdict"])
        print(f"run_id: {run_id}")
        return verdict_exit(str(cleaned["verdict"]))
    except RedactionError:
        print("scenario: report failed redaction", file=sys.stderr)
        return 1
    finally:
        lock.unlink(missing_ok=True)


def smoke(ready_check: Callable[[str], bool] | None = None) -> int:
    check = ready_check or _ready
    exit_code = 0
    for name, base in (("target", TARGET_BASE), ("admin", ADMIN_BASE)):
        if check(f"{base}/healthz"):
            print(f"{name}: ready")
        else:
            print(f"{name}: not ready. Next: ./lab doctor")
            exit_code = 1
    return exit_code


def verify_stored(root: Path, run_id: str) -> int:
    """Re-read the stored report. This does not collect observations again."""
    document = _read_report(root, run_id)
    if isinstance(document, int):
        return document
    try:
        require_redacted(document)
    except RedactionError:
        print("scenario: stored report failed redaction", file=sys.stderr)
        return 1
    verdict = document.get("verdict")
    if not isinstance(verdict, str) or verdict not in {"PASSED", "FAILED", "INDETERMINATE", "CANCELLED"}:
        print("scenario: stored report has no verdict", file=sys.stderr)
        return 1
    print(verdict)
    print("this is the stored report")
    return verdict_exit(verdict)


def export_report(root: Path, run_id: str) -> int:
    document = _read_report(root, run_id)
    if isinstance(document, int):
        return document
    try:
        require_redacted(document)
    except RedactionError:
        print("scenario: stored report failed redaction", file=sys.stderr)
        return 1
    print(json.dumps(document, indent=2, sort_keys=True))
    return 0


def reference_run(root: Path) -> int:
    holder: dict[str, dict[str, str]] = {}

    def health() -> list[str]:
        return readiness_problems()

    def drive() -> dict[str, Any]:
        try:
            env = load_env(root / ".env")
        except FileNotFoundError as exc:
            raise EnvError(".env", "is missing") from exc
        for key in REQUIRED_ENV:
            if not env.get(key):
                raise EnvError(key, "is empty")
        if env["SCIM_TOKEN_APP_A"] == env["SCIM_TOKEN_APP_A_READ"]:
            raise EnvError("SCIM_TOKEN_APP_A_READ", "must be distinct from the write token")
        holder["env"] = env
        return run_scim_login_revoke(
            target_base_url=TARGET_BASE,
            admin_base_url=ADMIN_BASE,
            scim_token=env["SCIM_TOKEN_APP_A"],
            admin_token=env["LAB_ADMIN_TOKEN"],
            subject=alice_subject(),
        )

    def check(requested: dict[str, Any] | None) -> dict[str, Any]:
        env = holder.get("env")
        if not env:
            return {
                "verdict": "INDETERMINATE",
                "missing": ["verifier"],
                "assertions": [],
                "observations": {},
            }
        user_id = None
        if isinstance(requested, dict) and isinstance(requested.get("user_id"), str):
            user_id = requested["user_id"]
        return verify(
            target_base_url=TARGET_BASE,
            read_token=env["SCIM_TOKEN_APP_A_READ"],
            expectation=expectation_from(FLAGSHIP),
            user_id=user_id,
            session_cookie=None,
        )

    def secret_values() -> list[str]:
        env = holder.get("env", {})
        return [value for value in env.values() if isinstance(value, str) and len(value) >= 12]

    return execute_reference(
        root,
        health=health,
        drive=drive,
        check=check,
        secret_values=secret_values,
    )


def readiness_problems() -> list[str]:
    problems = []
    for name, base in (("target", TARGET_BASE), ("admin", ADMIN_BASE)):
        if not _ready(f"{base}/healthz"):
            problems.append(f"{name}: not ready. Next: ./lab doctor")
    return problems


def main(argv: list[str]) -> int:
    if not argv:
        _usage()
        return 2
    command = argv[0]
    rest = argv[1:]
    if command == "scenario":
        return _scenario(rest)
    if command == "test":
        return _test(rest)
    if command == "export":
        return _export(rest)
    print(f"{command} is unavailable", file=sys.stderr)
    return 2


def _scenario(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help", "help"}:
        _scenario_usage()
        return 2
    command = argv[0]
    if command == "list":
        if len(argv) != 1:
            _scenario_usage()
            return 2
        for line in scenario_list_lines(lab_root()):
            print(line)
        return 0
    if command == "prepare":
        print("mover-engineering-to-sales is unavailable", file=sys.stderr)
        return 2
    if command == "verify":
        if len(argv) != 2:
            _scenario_usage()
            return 2
        return verify_stored(lab_root(), argv[1])
    if command == "run":
        return _run(argv[1:])
    print(f"{command} is unavailable", file=sys.stderr)
    return 2


def _run(argv: list[str]) -> int:
    scenario: str | None = None
    mode: str | None = None
    index = 0
    while index < len(argv):
        item = argv[index]
        if item == "--mode":
            if index + 1 >= len(argv):
                print("scenario: --mode reference is required", file=sys.stderr)
                return 2
            mode = argv[index + 1]
            index += 2
            continue
        if item.startswith("--mode="):
            mode = item.split("=", 1)[1]
            index += 1
            continue
        if item.startswith("-"):
            print(f"scenario: unknown argument {item}", file=sys.stderr)
            return 2
        if scenario is not None:
            print("scenario: too many arguments", file=sys.stderr)
            return 2
        scenario = item
        index += 1
    if scenario != "scim-login-revoke":
        print(f"{scenario or 'scenario'} is unavailable", file=sys.stderr)
        return 2
    if mode is None:
        print("scenario: --mode reference is required", file=sys.stderr)
        return 2
    if mode != "reference":
        print(f"{mode} mode is unavailable", file=sys.stderr)
        return 2
    return reference_run(lab_root())


def _test(argv: list[str]) -> int:
    if argv == ["smoke"]:
        return smoke()
    print("unavailable", file=sys.stderr)
    return 2


def _export(argv: list[str]) -> int:
    if not argv or argv[0].startswith("-"):
        print("export: --format json is required", file=sys.stderr)
        return 2
    run_id = argv[0]
    fmt: str | None = None
    index = 1
    while index < len(argv):
        item = argv[index]
        if item == "--format":
            if index + 1 >= len(argv):
                print("export: --format json is required", file=sys.stderr)
                return 2
            fmt = argv[index + 1]
            index += 2
            continue
        if item.startswith("--format="):
            fmt = item.split("=", 1)[1]
            index += 1
            continue
        print("export: --format json is required", file=sys.stderr)
        return 2
    if fmt is None:
        print("export: --format json is required", file=sys.stderr)
        return 2
    if fmt != "json":
        print(f"export: {fmt} is unavailable", file=sys.stderr)
        return 2
    return export_report(lab_root(), run_id)


def _ready(url: str) -> bool:
    try:
        status, body = fetch_json(url, 4)
    except Exception:
        return False
    return status == 200 and isinstance(body, dict) and body.get("ok") is True


def _valid_observed(observed: object) -> bool:
    if not isinstance(observed, dict):
        return False
    verdict = observed.get("verdict")
    return verdict in {"PASSED", "FAILED", "INDETERMINATE", "CANCELLED"}


def _assemble(
    run_id: str,
    started: str,
    contract: dict[str, Any],
    requested: dict[str, Any] | None,
    observed: dict[str, Any],
    completed: bool,
) -> dict[str, Any]:
    body = requested if isinstance(requested, dict) else {}
    operations = body.get("operations")
    if not isinstance(operations, list):
        operations = []
    group_ids = body.get("group_ids")
    if not isinstance(group_ids, dict):
        group_ids = {}
    return {
        "run_id": run_id,
        "scenario_id": "scim-login-revoke",
        "scenario_version": "1",
        "fixture_id": FIXTURE_ID,
        "mode": "reference",
        "contract": contract,
        "lab_generation": None,
        "started_at": started,
        "finished_at": _iso_now(),
        "driver_completed": completed,
        "requested_operations": operations,
        "ids": {
            "user_id": body.get("user_id"),
            "group_ids": group_ids,
            "subject": body.get("subject"),
        },
        "verdict": observed.get("verdict"),
        "missing": observed.get("missing", []),
        "assertions": observed.get("assertions", []),
        "observations": observed.get("observations", {}),
        "evidence_note": "observations are verifier reads; requested_operations are not evidence",
    }


def _read_report(root: Path, run_id: str) -> dict[str, Any] | int:
    if not _RUN_ID.fullmatch(run_id) or run_id in {".", ".."}:
        print("scenario: run id is invalid", file=sys.stderr)
        return 2
    path = root / ".lab-runs" / f"{run_id}.json"
    if not path.is_file():
        print("scenario: stored report was not found", file=sys.stderr)
        return 1
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("scenario: stored report is not json", file=sys.stderr)
        return 1
    if not isinstance(parsed, dict):
        print("scenario: stored report is not json", file=sys.stderr)
        return 1
    return parsed


def _write_json(path: Path, document: object) -> None:
    payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
    temporary = path.with_suffix(".json.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"scim-login-revoke-{stamp}-{token_source.token_hex(4)}"


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _usage() -> None:
    print(
        "Usage: scenario_cli <scenario|test|export> ...",
        file=sys.stderr,
    )


def _scenario_usage() -> None:
    print(
        "Usage: ./lab scenario list | run scim-login-revoke --mode reference | verify <run-id>",
        file=sys.stderr,
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
