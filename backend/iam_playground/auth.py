"""Admin bearer check. Loopback binding is not a substitute for this."""

from __future__ import annotations

import hmac


def presented_bearer(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    scheme, separator, rest = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer":
        return None
    token = rest.strip()
    if not token or " " in token:
        return None
    return token


def bearer_matches(authorization: str | None, expected: str) -> bool:
    if not expected:
        return False
    presented = presented_bearer(authorization)
    if presented is None:
        return False
    presented_b = presented.encode("utf-8")
    expected_b = expected.encode("utf-8")
    if len(presented_b) != len(expected_b):
        return False
    return hmac.compare_digest(presented_b, expected_b)
