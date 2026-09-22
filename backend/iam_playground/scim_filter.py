"""Equality-only SCIM filters. Anything else is invalidFilter, never a full list."""

from __future__ import annotations

import re
from dataclasses import dataclass

from iam_playground.errors import ScimError

USER_FILTERS = frozenset({"userName", "emails.value", "active", "externalId"})
GROUP_FILTERS = frozenset({"displayName"})

_CANON = {
    "username": "userName",
    "emails.value": "emails.value",
    "active": "active",
    "externalid": "externalId",
    "displayname": "displayName",
}
_HEAD = re.compile(r"^([A-Za-z][\w.]*)\s+([A-Za-z]+)\s+([\s\S]+)$")


@dataclass(frozen=True)
class EqFilter:
    attribute: str
    value: str | bool


def parse_page(start_text: str | None, count_text: str | None) -> tuple[int, int]:
    """Return 1-based startIndex and count. Count defaults to 50 and caps at 100."""
    if start_text is None or start_text.strip() == "":
        start = 1
    else:
        try:
            start = int(start_text.strip())
        except ValueError as exc:
            raise ScimError(400, "startIndex is invalid", "invalidValue") from exc
    if start < 1:
        start = 1
    if count_text is None or count_text.strip() == "":
        limit = 50
    else:
        try:
            limit = int(count_text.strip())
        except ValueError as exc:
            raise ScimError(400, "count is invalid", "invalidValue") from exc
    if limit < 0:
        raise ScimError(400, "count is invalid", "invalidValue")
    if limit > 100:
        limit = 100
    return start, limit


def parse_equality_filter(text: str | None, allowed: frozenset[str]) -> EqFilter | None:
    if text is None:
        return None
    raw = text.strip()
    if not raw:
        raise ScimError(400, "filter is empty", "invalidFilter")
    match = _HEAD.match(raw)
    if match is None:
        raise ScimError(400, "filter is not supported", "invalidFilter")
    attribute = _CANON.get(match.group(1).lower())
    operator = match.group(2).lower()
    if operator != "eq" or attribute is None or attribute not in allowed:
        raise ScimError(400, "filter is not supported", "invalidFilter")
    return EqFilter(attribute, _parse_value(attribute, match.group(3).strip()))


def _parse_value(attribute: str, rest: str) -> str | bool:
    if not rest.startswith('"'):
        word = rest.strip()
        if word.lower() in {"true", "false"} and word == rest:
            if attribute != "active":
                raise ScimError(400, "filter value type is not supported", "invalidFilter")
            return word.lower() == "true"
        raise ScimError(400, "filter is malformed", "invalidFilter")
    if attribute == "active":
        raise ScimError(400, "active filter must be a boolean", "invalidFilter")
    return _parse_quoted(rest)


def _parse_quoted(rest: str) -> str:
    if not rest.startswith('"'):
        raise ScimError(400, "filter is malformed", "invalidFilter")
    chars: list[str] = []
    index = 1
    while index < len(rest):
        char = rest[index]
        if char == "\\":
            if index + 1 >= len(rest) or rest[index + 1] not in {'\\', '"'}:
                raise ScimError(400, "filter is malformed", "invalidFilter")
            chars.append(rest[index + 1])
            index += 2
            continue
        if char == '"':
            if rest[index + 1 :].strip():
                raise ScimError(400, "filter is not a single equality", "invalidFilter")
            return "".join(chars)
        chars.append(char)
        index += 1
    raise ScimError(400, "filter is malformed", "invalidFilter")
