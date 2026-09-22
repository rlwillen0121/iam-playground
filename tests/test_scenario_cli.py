"""Lab scenario commands. These tests do not start Docker."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from iam_playground.scenario_cli import (
    alice_subject,
    execute_reference,
    export_report,
    smoke,
    verify_stored,
)

ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(ROOT / "lab"), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_scenario_list_names_the_flagship_and_scenario_files() -> None:
    result = _run(["scenario", "list"])
    assert result.returncode == 0
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert lines[0] == "scim-login-revoke"
    assert "transaction-rollback is unavailable" in lines
    assert "mover-engineering-to-sales is unavailable" not in result.stdout
    for path in sorted((ROOT / "scenarios").glob("*.json")):
        scenario_id = json.loads(path.read_text(encoding="utf-8"))["id"]
        if scenario_id == "transaction-rollback":
            assert "transaction-rollback is unavailable" in lines
            assert scenario_id not in lines
        else:
            assert scenario_id in lines


def test_jdbc_verify_does_not_open_a_database() -> None:
    jdbc = _run(["jdbc", "verify"])
    text = jdbc.stdout + jdbc.stderr
    assert jdbc.returncode == 0
    assert "The JDBC client is implemented." in jdbc.stdout
    assert "does not open a database" in jdbc.stdout
    assert "connected" not in text.lower()
    assert "PASSED" not in text
    external = _run(["scenario", "run", "scim-login-revoke", "--mode", "external"])
    assert external.returncode == 2
    assert "unavailable" in external.stderr
    assert "PASSED" not in external.stdout + external.stderr


def test_active_lock_tells_the_operator_to_wait_or_reset() -> None:
    lock = ROOT / ".lab-runs" / "active"
    if lock.exists():
        pytest.skip("a lab run is active")
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("test\n", encoding="utf-8")
    try:
        result = _run(["scenario", "run", "scim-login-revoke", "--mode", "reference"])
        text = result.stdout + result.stderr
        assert result.returncode == 1
        assert "wait" in text.lower()
        assert "reset" in text.lower()
        assert "PASSED" not in text
    finally:
        if lock.exists() and lock.read_text(encoding="utf-8") == "test\n":
            lock.unlink()


def test_smoke_says_ready_or_not_ready_and_never_passed(capsys: pytest.CaptureFixture[str]) -> None:
    down = smoke(ready_check=lambda url: False)
    down_out = capsys.readouterr().out
    assert down == 1
    assert "target: not ready" in down_out
    assert "admin: not ready" in down_out
    assert "PASSED" not in down_out
    up = smoke(ready_check=lambda url: True)
    up_out = capsys.readouterr().out
    assert up == 0
    assert "target: ready" in up_out
    assert "admin: ready" in up_out
    assert "PASSED" not in up_out
    assert "not ready" not in up_out


def test_health_failure_does_not_pass_and_releases_the_lock(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    called = False

    def drive() -> dict:
        nonlocal called
        called = True
        return {}

    code = execute_reference(
        tmp_path,
        health=lambda: ["target: not ready. Next: ./lab doctor"],
        drive=drive,
        check=lambda requested: {"verdict": "PASSED"},
        secret_values=lambda: [],
    )
    captured = capsys.readouterr()
    assert code == 1
    assert called is False
    assert "target" in captured.err
    assert "not ready" in captured.err
    assert "PASSED" not in captured.out
    assert "PASSED" not in captured.err
    assert not (tmp_path / ".lab-runs" / "active").exists()


def test_existing_lock_is_left_in_place(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    runs = tmp_path / ".lab-runs"
    runs.mkdir()
    lock = runs / "active"
    lock.write_text("busy", encoding="utf-8")
    code = execute_reference(
        tmp_path,
        health=lambda: [],
        drive=lambda: {"operations": []},
        check=lambda requested: {"verdict": "PASSED", "missing": [], "assertions": [], "observations": {}},
        secret_values=lambda: [],
    )
    captured = capsys.readouterr()
    assert code == 1
    assert lock.read_text(encoding="utf-8") == "busy"
    assert "wait" in captured.err.lower()
    assert "reset" in captured.err.lower()
    assert "PASSED" not in captured.out


def test_report_strips_bearer_cookie_and_password_prefix(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    token = "a" * 32
    cookie = "b" * 32

    def drive() -> dict:
        return {
            "user_id": "user-1",
            "group_ids": {"Readers": "group-1"},
            "subject": "subject-1",
            "operations": [{"name": "create_user", "detail": f"Bearer {token} synthetic-lab-alice"}],
        }

    def check(requested: dict | None) -> dict:
        assert requested is not None
        return {
            "verdict": "PASSED",
            "missing": [],
            "assertions": [],
            "observations": {"cookie": f"lab_session={cookie}", "note": token},
        }

    code = execute_reference(
        tmp_path,
        health=lambda: [],
        drive=drive,
        check=check,
        secret_values=lambda: [token, cookie],
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "PASSED" in captured.out
    assert token not in captured.out
    assert cookie not in captured.out
    reports = list((tmp_path / ".lab-runs").glob("*.json"))
    assert len(reports) == 1
    text = reports[0].read_text(encoding="utf-8")
    assert token not in text
    assert cookie not in text
    assert "synthetic-lab-" not in text
    assert not (tmp_path / ".lab-runs" / "active").exists()


def test_verify_reads_the_stored_verdict(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_id = "scim-login-revoke-20260922T120000Z-abcd1234"
    runs = tmp_path / ".lab-runs"
    runs.mkdir()
    (runs / f"{run_id}.json").write_text(
        json.dumps({"verdict": "INDETERMINATE", "missing": ["cookie"]}),
        encoding="utf-8",
    )
    code = verify_stored(tmp_path, run_id)
    captured = capsys.readouterr()
    assert code == 2
    assert "INDETERMINATE" in captured.out
    assert "this is the stored report" in captured.out


def test_export_and_verify_reject_a_fixture_password_prefix(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_id = "scim-login-revoke-20260922T120000Z-abcd1234"
    runs = tmp_path / ".lab-runs"
    runs.mkdir()
    (runs / f"{run_id}.json").write_text(
        json.dumps({"verdict": "PASSED", "leak": "synthetic-lab-alice"}),
        encoding="utf-8",
    )
    exported = export_report(tmp_path, run_id)
    exported_io = capsys.readouterr()
    assert exported == 1
    assert "synthetic-lab-" not in exported_io.out
    assert "synthetic-lab-" not in exported_io.err
    assert "PASSED" not in exported_io.out
    verified = verify_stored(tmp_path, run_id)
    verified_io = capsys.readouterr()
    assert verified == 1
    assert "PASSED" not in verified_io.out
    assert "synthetic-lab-" not in verified_io.out
    assert "synthetic-lab-" not in verified_io.err


def test_lab_export_prints_the_stored_report() -> None:
    run_id = "scim-login-revoke-20260922T120001Z-abcd1234"
    path = ROOT / ".lab-runs" / f"{run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"verdict": "FAILED", "missing": ["cookie"]}) + "\n", encoding="utf-8")
    try:
        exported = _run(["export", run_id, "--format", "json"])
        assert exported.returncode == 0
        assert "FAILED" in exported.stdout
        assert "synthetic-lab-" not in exported.stdout
        verified = _run(["scenario", "verify", run_id])
        assert verified.returncode == 1
        assert "FAILED" in verified.stdout
        assert "this is the stored report" in verified.stdout
    finally:
        path.unlink(missing_ok=True)


def test_alice_subject_matches_the_realm_import() -> None:
    realm = json.loads((ROOT / "infra" / "keycloak" / "iam-playground-realm.json").read_text(encoding="utf-8"))
    alice = next(user for user in realm["users"] if user["username"] == "alice")
    assert alice_subject() == alice["id"]
    assert "password" not in alice
