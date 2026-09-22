"""Write the private Keycloak import used on first boot."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from iam_playground.fixture import load_fixture
from iam_playground.realm import build_realm


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)


def write_keycloak_import(root: Path) -> Path:
    fixture = load_fixture(root / "fixtures" / "enterprise-small-v1.json")
    realm = build_realm(fixture, include_credentials=True)
    destination = root / "infra" / "keycloak" / "generated" / "iam-playground-realm.json"
    write_private(destination, json.dumps(realm, indent=2) + "\n")
    return destination


def main() -> int:
    root = Path(os.environ.get("LAB_ROOT", ".")).resolve()
    destination = write_keycloak_import(root)
    if not destination.is_file():
        print("keycloak: realm import was not generated. Next: ./lab up", file=sys.stderr)
        return 1
    print("keycloak: realm import generated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
