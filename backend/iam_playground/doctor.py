"""Host-side readiness checks. An open port is not success."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from iam_playground.constants import DISCOVERY_URL, EXPECTED_ISSUER, FIXTURE_ID, LOOPBACK_ENDPOINTS
from iam_playground.envfile import load_env
from iam_playground.net import fetch_bytes, fetch_json
from iam_playground.readiness import discovery_is_ready


def _fail(check: str, reason: str) -> int:
    print(f"{check}: {reason}", file=sys.stderr)
    return 1


def check_postgres(env: dict[str, str]) -> str | None:
    try:
        import psycopg
    except ImportError:
        return (
            "Python database driver is not installed, so the lab database was not queried. "
            "Next: python3 -m pip install -r requirements.txt"
        )
    password = env.get("ADMIN_OWNER_PASSWORD", "")
    if not password:
        return "admin database credential is missing. Next: ./lab up"
    try:
        with psycopg.connect(
            host="127.0.0.1",
            port=5432,
            dbname="lab",
            user="admin_owner",
            password=password,
            connect_timeout=3,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                one = cursor.fetchone()
                cursor.execute("SELECT generation, accepting, fixture_id FROM lab_meta")
                row = cursor.fetchone()
    except Exception:
        return "database query failed. Next: ./lab up"
    if one is None or one[0] != 1:
        return "SELECT 1 did not succeed. Next: ./lab up"
    if row is None or row[0] is None:
        return "lab_meta has no generation row. Next: ./lab up"
    if row[2] != FIXTURE_ID:
        return "lab_meta fixture is not enterprise-small-v1. Next: ./lab reset --fixture enterprise-small-v1"
    return None


def check_keycloak() -> str | None:
    try:
        status, document = fetch_json(DISCOVERY_URL, 3)
    except Exception:
        return "discovery document was not fetched. Next: ./lab up"
    if status != 200 or not discovery_is_ready(document):
        return "discovery issuer does not match the lab issuer. Next: ./lab up"
    return None


def check_http_service(name: str, url: str) -> str | None:
    try:
        status, _body = fetch_bytes(url, 3, headers={"Accept": "application/json"})
    except Exception:
        return f"{name}: did not respond. Next: ./lab up"
    if status != 200:
        return f"{name}: /healthz returned HTTP {status}. Next: ./lab up"
    return None


def check_workbench() -> str | None:
    url = LOOPBACK_ENDPOINTS["workbench"].rstrip("/") + "/"
    try:
        status, body = fetch_bytes(url, 3)
    except Exception:
        return "workbench: did not respond. Next: ./lab up"
    if status != 200:
        return f"workbench: returned HTTP {status}. Next: ./lab up"
    if b"loopback" not in body:
        return "workbench: HTTP 200 did not contain loopback. Next: ./lab up"
    return None


def main() -> int:
    root = Path(os.environ.get("LAB_ROOT", ".")).resolve()
    try:
        env = load_env(root / ".env")
    except FileNotFoundError:
        return _fail(
            "postgres",
            ".env is missing, so the lab database was not queried. Next: ./lab up",
        )
    reason = check_postgres(env)
    if reason:
        return _fail("postgres", reason)
    print("postgres: ok")
    reason = check_keycloak()
    if reason:
        return _fail("keycloak", reason)
    print("keycloak: ok")
    for name, port_url in (("target", LOOPBACK_ENDPOINTS["target"]), ("admin", LOOPBACK_ENDPOINTS["admin"])):
        failure = check_http_service(name, port_url + "/healthz")
        if failure:
            print(failure, file=sys.stderr)
            return 1
        print(f"{name}: ok")
    failure = check_workbench()
    if failure:
        print(failure, file=sys.stderr)
        return 1
    print("workbench: ok")
    if EXPECTED_ISSUER != LOOPBACK_ENDPOINTS["issuer"]:
        return _fail("keycloak", "issuer constant mismatch. Next: ./lab doctor")
    return 0


if __name__ == "__main__":
    sys.exit(main())
