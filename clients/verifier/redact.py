"""Redact lab reports. A fixture password prefix must not survive."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "password",
        "secret",
    }
)
_BEARER = re.compile(r"Bearer\s+\S+", re.IGNORECASE)
_BEARER_LEAK = re.compile(r"Bearer\s+(?!\[redacted\])\S+", re.IGNORECASE)
_COOKIE = re.compile(r"lab_session=[^\s;,\"']+")
_COOKIE_LEAK = re.compile(r"lab_session=(?!\[redacted\])")
_SYNTHETIC = re.compile(r"synthetic-lab-[A-Za-z0-9._-]*")
_MIN_SECRET = 12


class RedactionError(ValueError):
    """The document still contains something the report must not keep."""


def redact(value: object, extras: Sequence[str] = ()) -> object:
    """Return a copy with bearer values, cookies, and synthetic-lab- strings removed."""
    secrets = _long_secrets(extras)
    return _walk(value, secrets)


def require_redacted(document: object, extras: Sequence[str] = ()) -> None:
    """Fail when a report still contains a secret. This does not rewrite it."""
    text = json.dumps(document, sort_keys=True, ensure_ascii=True)
    if "synthetic-lab-" in text:
        raise RedactionError("report contains a fixture password prefix")
    if _BEARER_LEAK.search(text):
        raise RedactionError("report contains an authorization bearer")
    if _COOKIE_LEAK.search(text):
        raise RedactionError("report contains a session cookie")
    for secret in _long_secrets(extras):
        if secret in text:
            raise RedactionError("report contains a secret")


def _long_secrets(extras: Sequence[str]) -> list[str]:
    found = [item for item in extras if isinstance(item, str) and len(item) >= _MIN_SECRET]
    found.sort(key=len, reverse=True)
    return found


def _walk(value: object, secrets: list[str]) -> object:
    if isinstance(value, dict):
        cleaned: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and key.lower() in _SENSITIVE_KEYS:
                cleaned[key] = "[redacted]"
            else:
                cleaned[key] = _walk(item, secrets)
        return cleaned
    if isinstance(value, list):
        return [_walk(item, secrets) for item in value]
    if isinstance(value, str):
        return _redact_text(value, secrets)
    return value


def _redact_text(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret in text:
            text = text.replace(secret, "[redacted]")
    text = _BEARER.sub("Bearer [redacted]", text)
    text = _COOKIE.sub("lab_session=[redacted]", text)
    text = _SYNTHETIC.sub("[redacted]", text)
    return text
