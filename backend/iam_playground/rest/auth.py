"""Profile credentials. The actor is the matched credential, never a JSON field."""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass

from iam_playground.auth import bearer_matches
from iam_playground.rest.constants import (
    APP_LEGACY,
    APP_MODERN,
    CLIENT_LEGACY,
    CLIENT_LEGACY_READ,
    CLIENT_MODERN,
    CLIENT_MODERN_READ,
)
from iam_playground.rest.errors import RestError


@dataclass(frozen=True)
class Principal:
    app_id: str
    client_id: str
    read_only: bool


def env_modern_token() -> str:
    return os.environ.get("REST_MODERN_TOKEN", "")


def env_modern_read_token() -> str:
    return os.environ.get("REST_MODERN_READ", "")


def env_legacy_key() -> str:
    return os.environ.get("REST_LEGACY_KEY", "")


def env_legacy_read_key() -> str:
    return os.environ.get("REST_LEGACY_READ", "")


def api_key_matches(presented: str | None, expected: str) -> bool:
    if not expected or presented is None or presented == "":
        return False
    presented_b = presented.encode("utf-8")
    expected_b = expected.encode("utf-8")
    if len(presented_b) != len(expected_b):
        return False
    return hmac.compare_digest(presented_b, expected_b)


def modern_principal(
    authorization: str | None,
    *,
    mutation: bool,
    write_token: str,
    read_token: str,
) -> Principal:
    if bearer_matches(authorization, write_token):
        return Principal(APP_MODERN, CLIENT_MODERN, False)
    if bearer_matches(authorization, read_token):
        if mutation:
            raise RestError(403, "read credential cannot modify")
        return Principal(APP_MODERN, CLIENT_MODERN_READ, True)
    raise RestError(401, "bearer token required")


def legacy_principal(
    api_key: str | None,
    *,
    mutation: bool,
    write_key: str,
    read_key: str,
) -> Principal:
    if api_key_matches(api_key, write_key):
        return Principal(APP_LEGACY, CLIENT_LEGACY, False)
    if api_key_matches(api_key, read_key):
        if mutation:
            raise RestError(403, "read credential cannot modify")
        return Principal(APP_LEGACY, CLIENT_LEGACY_READ, True)
    raise RestError(401, "api key required")
