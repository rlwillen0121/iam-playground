"""Call the admin reset. The bearer token is not printed."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from iam_playground.constants import FIXTURE_ID, LOOPBACK_ENDPOINTS
from iam_playground.envfile import load_env
from iam_playground.net import fetch_bytes

_PRINTABLE_DETAILS = {
    "lab_meta row missing",
    "fixture is not in this checkpoint",
    "admin token required",
    "reset failed",
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    fixture = args[0] if args else ""
    if fixture != FIXTURE_ID:
        shown = fixture or "missing"
        print(f"reset: fixture {shown} is not in this checkpoint", file=sys.stderr)
        return 2
    root = Path(os.environ.get("LAB_ROOT", ".")).resolve()
    try:
        env = load_env(root / ".env")
    except FileNotFoundError:
        print("admin: reset token is not configured. Next: ./lab up", file=sys.stderr)
        return 1
    token = env.get("LAB_ADMIN_TOKEN", "")
    if not token:
        print("admin: reset token is not configured. Next: ./lab up", file=sys.stderr)
        return 1
    payload = json.dumps({"fixture_id": fixture}).encode("utf-8")
    url = LOOPBACK_ENDPOINTS["admin"] + "/reset"
    try:
        status, body = fetch_bytes(
            url,
            15,
            method="POST",
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
    except Exception:
        print("admin: reset did not respond. Next: ./lab up", file=sys.stderr)
        return 1
    if status == 200:
        print(f"reset: {FIXTURE_ID}")
        return 0
    detail = ""
    try:
        parsed = json.loads(body.decode("utf-8"))
        if isinstance(parsed, dict) and parsed.get("detail") in _PRINTABLE_DETAILS:
            detail = str(parsed["detail"])
    except Exception:
        detail = ""
    suffix = f" ({detail})" if detail else ""
    if status == 401:
        print(f"admin: reset was refused{suffix}. Next: ./lab doctor", file=sys.stderr)
        return 1
    print(f"admin: reset failed with HTTP {status}{suffix}. Next: ./lab doctor", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
