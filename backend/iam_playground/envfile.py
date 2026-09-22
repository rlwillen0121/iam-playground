"""Read the untracked .env file without printing values."""

from __future__ import annotations

from pathlib import Path


def load_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise FileNotFoundError(path)
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value
    return values
