"""JSON account bodies, cursors, and pages. Hashes use the canonical payload."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping

from iam_playground.rest.constants import (
    ACCOUNT_ID_MAX,
    IDEMPOTENCY_KEY_MAX,
    PAGE_DEFAULT,
    PAGE_MAX,
    PAGE_NUMBER_MAX,
    STATUS_ENABLED,
    STATUSES,
    TEXT_MAX,
)
from iam_playground.rest.errors import RestError
from iam_playground.rest.models import Account
from iam_playground.rest.recovery import Operation

_LOGIN = re.compile(r"[ -~]+")
_ROLE = re.compile(r"[a-z][a-z0-9-]{0,63}")
_CURSOR = re.compile(r"[A-Za-z0-9_-]+")
_POSITIVE = re.compile(r"[1-9][0-9]*")
_OPERATION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_CREATE_FIELDS = frozenset({"login", "employeeRef", "status", "profile"})
_PATCH_FIELDS = _CREATE_FIELDS
_PROFILE_FIELDS = frozenset({"firstName", "lastName", "department"})


def account_json(account: Account) -> dict:
    return {
        "id": account.id,
        "login": account.login,
        "employeeRef": account.employee_ref,
        "status": account.status,
        "profile": {
            "firstName": account.first_name,
            "lastName": account.last_name,
            "department": account.department,
        },
        "roles": list(account.roles),
    }


def operation_json(op: Operation) -> dict:
    return {
        "id": op.id,
        "state": op.state,
        "operation": op.kind,
        "accountId": op.account_id,
        "role": op.role_name,
        "clientId": op.client_id,
        "error": op.error,
    }


def parse_create(body: object) -> dict:
    raw = _object(body)
    _unknown(raw, _CREATE_FIELDS)
    profile = _profile(raw.get("profile"), required=True)
    status = raw.get("status", STATUS_ENABLED)
    return {
        "login": _login(raw.get("login")),
        "employeeRef": _text(raw.get("employeeRef"), "employeeRef"),
        "status": _status(status),
        "profile": profile,
    }


def parse_patch(body: object) -> dict:
    raw = _object(body)
    _unknown(raw, _PATCH_FIELDS)
    if not raw:
        raise RestError(400, "request body must change a field")
    parsed: dict = {}
    if "login" in raw:
        parsed["login"] = _login(raw.get("login"))
    if "employeeRef" in raw:
        parsed["employeeRef"] = _text(raw.get("employeeRef"), "employeeRef")
    if "status" in raw:
        parsed["status"] = _status(raw.get("status"))
    if "profile" in raw:
        profile = _profile(raw.get("profile"), required=False)
        if not profile:
            raise RestError(400, "profile must change a field")
        parsed["profile"] = profile
    return parsed


def apply_patch(account: Account, patch: Mapping) -> Account:
    profile = patch.get("profile")
    if not isinstance(profile, Mapping):
        profile = {}
    return Account(
        app_id=account.app_id,
        id=account.id,
        login=str(patch.get("login", account.login)),
        employee_ref=str(patch.get("employeeRef", account.employee_ref)),
        status=str(patch.get("status", account.status)),
        first_name=str(profile.get("firstName", account.first_name)),
        last_name=str(profile.get("lastName", account.last_name)),
        department=str(profile.get("department", account.department)),
        roles=account.roles,
    )


def canonical_payload(kind: str, account_id: int | None, role: str | None, body: dict | None) -> str:
    material = {
        "accountId": account_id,
        "body": body,
        "kind": kind,
        "role": role,
    }
    return json.dumps(material, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def payload_hash(canonical: str) -> str:
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def encode_cursor(account_id: int) -> str:
    raw = f"v1:{account_id}".encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(value: str) -> int:
    if not _CURSOR.fullmatch(value):
        raise RestError(400, "cursor is invalid")
    padded = value + ("=" * (-len(value) % 4))
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("ascii")
    except Exception as exc:
        raise RestError(400, "cursor is invalid") from exc
    prefix, separator, number = raw.partition(":")
    if prefix != "v1" or separator != ":" or not _POSITIVE.fullmatch(number):
        raise RestError(400, "cursor is invalid")
    account_id = int(number)
    if account_id > ACCOUNT_ID_MAX:
        raise RestError(400, "cursor is invalid")
    return account_id


def parse_account_id(value: str) -> int:
    if not _POSITIVE.fullmatch(value):
        raise RestError(400, "account id is invalid")
    account_id = int(value)
    if account_id > ACCOUNT_ID_MAX:
        raise RestError(400, "account id is invalid")
    return account_id


def parse_operation_id(value: str) -> str:
    lowered = value.lower()
    if not _OPERATION_ID.fullmatch(lowered):
        raise RestError(404, "operation not found")
    return lowered


def parse_role_name(value: str) -> str:
    if not _ROLE.fullmatch(value):
        raise RestError(400, "role is invalid")
    return value


def parse_idempotency_key(value: str | None) -> str:
    if value is None or value == "":
        raise RestError(400, "Idempotency-Key is required")
    if value != value.strip() or len(value) > IDEMPOTENCY_KEY_MAX:
        raise RestError(400, "Idempotency-Key is invalid")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise RestError(400, "Idempotency-Key is invalid")
    return value


def parse_limit(value: str | None) -> int:
    if value is None:
        return PAGE_DEFAULT
    return _bounded(value, "limit", PAGE_MAX)


def parse_page_size(value: str | None) -> int:
    if value is None:
        return PAGE_DEFAULT
    return _bounded(value, "pageSize", PAGE_MAX)


def parse_page(value: str | None) -> int:
    if value is None:
        return 1
    return _bounded(value, "page", PAGE_NUMBER_MAX)


def reject_unknown(names: list[str], allowed: frozenset[str]) -> None:
    unknown = [name for name in names if name not in allowed]
    if unknown:
        raise RestError(400, f"unsupported query parameter {unknown[0]}")


def single_value(values: list[str], field: str) -> str | None:
    if not values:
        return None
    if len(values) > 1:
        raise RestError(400, f"{field} was repeated")
    return values[0]


def cursor_page(rows: list[dict], after_id: int | None, limit: int) -> dict:
    selected = [row for row in rows if after_id is None or int(row["id"]) > after_id]
    page = selected[:limit]
    has_more = len(selected) > limit
    next_cursor = encode_cursor(int(page[-1]["id"])) if has_more and page else None
    return {"accounts": page, "nextCursor": next_cursor}


def number_page(rows: list[dict], page: int, page_size: int) -> dict:
    offset = (page - 1) * page_size
    return {
        "accounts": rows[offset : offset + page_size],
        "page": page,
        "pageSize": page_size,
        "total": len(rows),
    }


def malformed_list(profile: str, page: int | None = None) -> dict:
    if profile == "legacy":
        return {"accounts": {"unexpected": True}, "page": page if page is not None else 1}
    return {"accounts": {"unexpected": True}}


def _bounded(value: str, field: str, maximum: int) -> int:
    if not _POSITIVE.fullmatch(value):
        raise RestError(400, f"{field} is invalid")
    number = int(value)
    if number > maximum:
        raise RestError(400, f"{field} is invalid")
    return number


def _object(body: object) -> dict:
    if not isinstance(body, dict):
        raise RestError(400, "request body must be an object")
    return body


def _unknown(raw: Mapping, allowed: frozenset[str]) -> None:
    for key in raw:
        if key not in allowed:
            raise RestError(400, f"unsupported field {key}")


def _profile(value: object, *, required: bool) -> dict:
    if value is None and not required:
        raise RestError(400, "profile must be an object")
    if not isinstance(value, dict):
        raise RestError(400, "profile must be an object")
    _unknown(value, _PROFILE_FIELDS)
    if required:
        return {
            "firstName": _text(value.get("firstName"), "profile.firstName"),
            "lastName": _text(value.get("lastName"), "profile.lastName"),
            "department": _text(value.get("department"), "profile.department"),
        }
    parsed = {}
    for key in ("firstName", "lastName", "department"):
        if key in value:
            parsed[key] = _text(value.get(key), f"profile.{key}")
    return parsed


def _login(value: object) -> str:
    text = _text(value, "login")
    if any(char.isspace() for char in text) or not text.isascii() or _LOGIN.fullmatch(text) is None:
        raise RestError(400, "login must be ASCII without whitespace")
    return text


def _status(value: object) -> str:
    if not isinstance(value, str) or value not in STATUSES:
        raise RestError(400, "status must be enabled or disabled")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or value == "" or value != value.strip():
        raise RestError(400, f"{field} must be a non-empty string")
    if len(value) > TEXT_MAX:
        raise RestError(400, f"{field} is too long")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise RestError(400, f"{field} has control characters")
    return value
