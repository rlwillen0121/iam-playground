"""Print loopback URLs from the admin process. Exit 1 if it does not respond."""

from __future__ import annotations

import sys

from iam_playground.constants import EXPECTED_ISSUER, LOOPBACK_ENDPOINTS
from iam_playground.net import fetch_json


def main() -> int:
    url = LOOPBACK_ENDPOINTS["admin"] + "/endpoints"
    try:
        status, payload = fetch_json(url, 3)
    except Exception:
        print("admin: /endpoints did not respond. Next: ./lab up", file=sys.stderr)
        return 1
    if status != 200 or not isinstance(payload, dict):
        print("admin: /endpoints did not respond. Next: ./lab up", file=sys.stderr)
        return 1
    if payload.get("issuer") != EXPECTED_ISSUER:
        print("admin: /endpoints issuer does not match. Next: ./lab doctor", file=sys.stderr)
        return 1
    for key in ("postgres", "keycloak", "target", "admin", "workbench", "issuer"):
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            print("admin: /endpoints is incomplete. Next: ./lab doctor", file=sys.stderr)
            return 1
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
