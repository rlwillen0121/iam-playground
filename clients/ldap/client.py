"""LDAP operation planner.

Returns operation dicts. Does not encode BER, open a socket, or import urllib.
apply_plan calls connection.search/add/modify/delete/rename/bind when a
connection is passed. A bind plan contains a password; do not log the plan.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

BASE_DN = "dc=iam,dc=test"
PEOPLE_DN = "ou=People,dc=iam,dc=test"
GROUPS_DN = "ou=Groups,dc=iam,dc=test"
SERVICE_ACCOUNTS_DN = "ou=ServiceAccounts,dc=iam,dc=test"
SYSTEM_DN = "ou=System,dc=iam,dc=test"
AGGREGATOR_DN = "cn=aggregator,ou=ServiceAccounts,dc=iam,dc=test"
PROVISIONER_DN = "cn=provisioner,ou=ServiceAccounts,dc=iam,dc=test"
ADMIN_DN = "cn=admin,dc=iam,dc=test"

# Synthetic lab passwords. The directory administrator password is not here.
AGGREGATOR_PASSWORD = "synthetic-lab-aggregator"
PROVISIONER_PASSWORD = "synthetic-lab-provisioner"

LOCK_ATTRIBUTE = "pwdAccountLockedTime"
LOCK_TIME = "000001010000Z"

_OPS = frozenset({"search", "add", "modify", "delete", "rename", "bind"})
_MODIFY_OPS = frozenset({"add", "replace", "delete"})

Operation = dict[str, Any]


def _require_dn(value: object) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError("dn must be a non-empty string")
    if any(char in value for char in "\r\n\x00"):
        raise ValueError("dn must be a non-empty string")
    if "=" not in value:
        raise ValueError("dn must include an attribute")
    return value.strip()


def _operation(op: str, dn: str, changes: Any) -> list[Operation]:
    return [{"op": op, "dn": _require_dn(dn), "changes": changes}]


def search(dn: str, changes: Mapping[str, Any] | None = None) -> list[Operation]:
    """Plan a search. changes may set filter, scope, and attributes."""
    body: dict[str, Any] = {
        "filter": "(objectClass=*)",
        "scope": "subtree",
        "attributes": ["*", "+"],
    }
    if changes is not None:
        if not isinstance(changes, Mapping):
            raise TypeError("search changes must be a mapping")
        body.update(changes)
    return _operation("search", dn, body)


def add(dn: str, changes: Mapping[str, Any]) -> list[Operation]:
    """Plan an add. changes is the attribute mapping."""
    if not isinstance(changes, Mapping) or not changes:
        raise ValueError("add changes must be attributes")
    return _operation("add", dn, dict(changes))


def modify(dn: str, changes: Sequence[Mapping[str, Any]]) -> list[Operation]:
    """Plan a modify. changes is a list of {op, attr, values} records."""
    if isinstance(changes, (str, bytes)) or not isinstance(changes, Sequence) or not changes:
        raise ValueError("modify changes must be a non-empty list")
    copied: list[dict[str, Any]] = []
    for item in changes:
        if not isinstance(item, Mapping):
            raise TypeError("modify change must be a mapping")
        record = dict(item)
        if record.get("op") not in _MODIFY_OPS or not isinstance(record.get("attr"), str):
            raise ValueError("modify change needs op and attr")
        copied.append(record)
    return _operation("modify", dn, copied)


def rename(dn: str, changes: Mapping[str, Any]) -> list[Operation]:
    """Plan a rename. changes needs newrdn and may set newsuperior."""
    if not isinstance(changes, Mapping):
        raise TypeError("rename changes must be a mapping")
    body: dict[str, Any] = {"deleteoldrdn": True}
    body.update(changes)
    newrdn = body.get("newrdn")
    if not isinstance(newrdn, str) or "=" not in newrdn:
        raise ValueError("rename changes need newrdn")
    return _operation("rename", dn, body)


def delete(dn: str, changes: Any = None) -> list[Operation]:
    """Plan a delete."""
    return _operation("delete", dn, changes)


def bind(dn: str, changes: Mapping[str, Any] | str) -> list[Operation]:
    """Plan a simple bind. changes is a password or a mapping containing one."""
    if isinstance(changes, str):
        if changes == "":
            raise ValueError("bind changes need a password")
        payload: dict[str, Any] = {"password": changes}
    elif isinstance(changes, Mapping):
        payload = dict(changes)
        if "password" not in payload and "userPassword" not in payload:
            raise ValueError("bind changes need a password")
    else:
        raise TypeError("bind changes must be a password or a mapping")
    return _operation("bind", dn, payload)


def disable_user(dn: str) -> list[Operation]:
    """Plan the administrative lock: add pwdAccountLockedTime=000001010000Z."""
    return modify(
        dn,
        [{"op": "add", "attr": LOCK_ATTRIBUTE, "values": [LOCK_TIME]}],
    )


def disable(dn: str) -> list[Operation]:
    """Same plan as disable_user."""
    return disable_user(dn)


def _copy_step(step: Mapping[str, Any]) -> Operation:
    if "op" not in step or "dn" not in step:
        raise ValueError("operation needs op and dn")
    changes = step.get("changes")
    if isinstance(changes, list):
        copied: Any = [dict(item) if isinstance(item, Mapping) else item for item in changes]
    elif isinstance(changes, Mapping):
        copied = dict(changes)
    else:
        copied = changes
    return {"op": step["op"], "dn": step["dn"], "changes": copied}


def apply_plan(plan: Sequence[Mapping[str, Any]], connection: Any = None) -> list[Any]:
    """Return the plan, or call connection.<op>(dn, changes) for each step."""
    steps = [_copy_step(step) for step in plan]
    if connection is None:
        return steps
    results: list[Any] = []
    for step in steps:
        op = step["op"]
        if op not in _OPS:
            raise ValueError(f"unsupported operation {op}")
        method = getattr(connection, op)
        results.append(method(step["dn"], step["changes"]))
    return results
