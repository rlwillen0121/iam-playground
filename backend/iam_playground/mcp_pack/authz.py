"""Principals, allowlists, and request checks. Decisions are not cached."""

from __future__ import annotations

import hmac
import threading
import uuid
from collections.abc import Mapping

from iam_playground.auth import bearer_matches
from iam_playground.constants import APPLICATIONS, DEMO_APP_ID
from iam_playground.mcp_pack.errors import PackError

AGENT = "agent"
REFERENCE = "reference"
PRINCIPALS = frozenset({AGENT, REFERENCE})

AGENT_APPS = frozenset({DEMO_APP_ID})
REFERENCE_APPS = frozenset(APPLICATIONS)

# Administrators is intentionally absent. Only these exact names are allowed.
AGENT_ENTITLEMENTS = frozenset({"Readers", "Editors", "Engineering", "Sales"})

TOOL_ACTIONS = (
    "lookup_account",
    "list_groups",
    "create_account",
    "add_member",
    "remove_member",
    "disable_account",
)
MUTATING_ACTIONS = frozenset(
    {"create_account", "add_member", "remove_member", "disable_account"}
)
PROHIBITED_ACTIONS = frozenset(
    {
        "bindings",
        "reset",
        "faults",
        "fixtures",
        "policy",
        "shell",
        "docker",
        "verifier",
    }
)

_TOOL_FIELDS = {
    "lookup_account": ("app_id", "user_name"),
    "list_groups": ("app_id",),
    "create_account": ("app_id", "user_name", "email", "employee_number", "department"),
    "add_member": ("app_id", "group_name", "user_id"),
    "remove_member": ("app_id", "group_name", "user_id"),
    "disable_account": ("app_id", "user_id"),
}

_CONTROL_FIELDS = frozenset({"url", "sql", "command"})
_BINDING_FIELDS = frozenset(
    {
        "binding",
        "bindings",
        "issuer",
        "subject",
        "accountbinding",
        "account_binding",
        "scim_user_id",
    }
)
_MAX_JSON_DEPTH = 20
_FIELD_LIMITS = {
    "app_id": 32,
    "user_name": 256,
    "email": 254,
    "employee_number": 64,
    "department": 128,
    "group_name": 128,
    "user_id": 64,
}


class PrincipalGate:
    """Process-local enablement. Disablement is not a token revocation."""

    def __init__(self) -> None:
        self._enabled = {AGENT: True, REFERENCE: True}
        self._lock = threading.Lock()

    def is_enabled(self, name: str) -> bool:
        with self._lock:
            return self._enabled.get(name, False)

    def disable(self, name: str) -> None:
        with self._lock:
            if name not in self._enabled:
                raise KeyError(name)
            self._enabled[name] = False


def principal_from_header(authorization: str | None, tokens: tuple[str, str]) -> str:
    agent, reference = tokens
    if agent and reference and _same_secret(agent, reference):
        raise PackError(503, "mcp tokens must be distinct")
    if bearer_matches(authorization, agent):
        return AGENT
    if bearer_matches(authorization, reference):
        return REFERENCE
    raise PackError(401, "bearer token required")


def require_enabled(
    authorization: str | None,
    tokens: tuple[str, str],
    gate: PrincipalGate,
) -> str:
    name = principal_from_header(authorization, tokens)
    if not gate.is_enabled(name):
        raise PackError(403, "principal disabled")
    return name


def reject_control_fields(value: object, depth: int = 0) -> None:
    if depth > _MAX_JSON_DEPTH:
        raise PackError(400, "JSON object required")
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str) and key.lower() in _CONTROL_FIELDS:
                raise PackError(400, "url, sql, and command fields are rejected")
            reject_control_fields(child, depth + 1)
    elif isinstance(value, list):
        for item in value:
            reject_control_fields(item, depth + 1)


def reject_query_controls(names: object) -> None:
    for key in names:
        if isinstance(key, str) and key.lower() in _CONTROL_FIELDS:
            raise PackError(400, "url, sql, and command fields are rejected")


def reject_binding_fields(value: object, depth: int = 0) -> None:
    if depth > _MAX_JSON_DEPTH:
        raise PackError(400, "JSON object required")
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str) and key.lower() in _BINDING_FIELDS:
                raise PackError(403, "bindings cannot be changed")
            reject_binding_fields(child, depth + 1)
    elif isinstance(value, list):
        for item in value:
            reject_binding_fields(item, depth + 1)


def parse_tool_body(action: str, body: Mapping[str, object]) -> dict[str, str]:
    fields = _TOOL_FIELDS.get(action)
    if fields is None:
        raise PackError(403, "action is not allowed")
    unknown = [key for key in body if key not in fields]
    if unknown:
        raise PackError(400, "unsupported field")
    missing = [key for key in fields if key not in body]
    if missing:
        raise PackError(400, f"{missing[0]} is required")
    parsed: dict[str, str] = {}
    for key in fields:
        if key == "user_id":
            parsed[key] = _user_id(body[key])
        else:
            parsed[key] = _text(body[key], key)
    return parsed


def authorize(principal: str, action: str, args: Mapping[str, str]) -> None:
    if action not in TOOL_ACTIONS or principal not in PRINCIPALS:
        raise PackError(403, "action is not allowed")
    allowed_apps = AGENT_APPS if principal == AGENT else REFERENCE_APPS
    if args.get("app_id") not in allowed_apps:
        raise PackError(403, "application is not allowed")
    if principal == AGENT and "group_name" in args:
        if args["group_name"] not in AGENT_ENTITLEMENTS:
            raise PackError(403, "entitlement is not allowed")


def _user_id(value: object) -> str:
    text = _text(value, "user_id")
    try:
        return str(uuid.UUID(text))
    except ValueError:
        raise PackError(400, "user_id must be a user id") from None


def _text(value: object, key: str) -> str:
    if not isinstance(value, str):
        raise PackError(400, f"{key} must be a string")
    if value == "" or value != value.strip():
        raise PackError(400, f"{key} must be a non-empty string")
    limit = _FIELD_LIMITS[key]
    if len(value) > limit:
        raise PackError(400, f"{key} is too long")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise PackError(400, f"{key} is invalid")
    return value


def _same_secret(left: str, right: str) -> bool:
    left_b = left.encode("utf-8")
    right_b = right.encode("utf-8")
    if len(left_b) != len(right_b):
        return False
    return hmac.compare_digest(left_b, right_b)
