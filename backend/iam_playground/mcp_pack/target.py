"""SCIM calls for the MCP pack. The inbound bearer token is not forwarded."""

from __future__ import annotations

import json
import os
import uuid
import urllib.error
import urllib.request
from typing import Protocol
from urllib.parse import quote, urlencode, urlsplit

from iam_playground.constants import APPLICATIONS
from iam_playground.mcp_pack.errors import PackError
from iam_playground.scim_codec import CORE_USER, ENTERPRISE_URN, PATCH_OP

_MEDIA = "application/scim+json"
_DEFAULT_BASE = "http://127.0.0.1:8090"
_TOKEN_ENV = {"app-a": "SCIM_TOKEN_APP_A", "app-b": "SCIM_TOKEN_APP_B"}
_MAX_RESPONSE = 1_048_576


class TargetApi(Protocol):
    def lookup_account(self, app_id: str, user_name: str) -> dict[str, object]:
        """Find an account by userName."""

    def list_groups(self, app_id: str) -> dict[str, object]:
        """List groups for one application."""

    def create_account(
        self,
        app_id: str,
        user_name: str,
        email: str,
        employee_number: str,
        department: str,
    ) -> dict[str, object]:
        """Create one account."""

    def add_member(self, app_id: str, group_name: str, user_id: str) -> dict[str, object]:
        """Add one user to a group."""

    def remove_member(self, app_id: str, group_name: str, user_id: str) -> dict[str, object]:
        """Remove one user from a group."""

    def disable_account(self, app_id: str, user_id: str) -> dict[str, object]:
        """Set active to false."""


class ScimTarget:
    """Fixed lab target. No shell, no Docker socket, and no file handler."""

    def __init__(self, base_url: str | None = None, *, timeout: float = 30) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._configured = base_url
        self._timeout = timeout
        # No FileHandler, FTPHandler, or DataHandler. ProxyHandler({}) ignores HTTP_PROXY.
        # Redirects are not installed, so a 3xx cannot resend the SCIM token.
        self._opener = urllib.request.OpenerDirector()
        self._opener.add_handler(urllib.request.ProxyHandler({}))
        self._opener.add_handler(urllib.request.HTTPHandler())
        https = getattr(urllib.request, "HTTPSHandler", None)
        if https is not None:
            self._opener.add_handler(https())

    def lookup_account(self, app_id: str, user_name: str) -> dict[str, object]:
        app_id = _application(app_id)
        collected: list[dict[str, object]] = []
        seen = 0
        start = 1
        total = 0
        truncated = True
        quoted = _filter_quote(user_name)
        for _page in range(5):
            document = self._json(
                "GET",
                _collection(app_id, "Users"),
                app_id,
                query=[
                    ("startIndex", str(start)),
                    ("count", "100"),
                    ("filter", f"userName eq {quoted}"),
                ],
            )
            resources, total = _page_of(document)
            seen += len(resources)
            for item in resources:
                view = _account_view(item)
                if str(view["userName"]).lower() != user_name.lower():
                    raise PackError(502, "target response was invalid", source="target")
                collected.append(view)
            if seen >= total or not resources:
                truncated = False
                break
            start += len(resources)
        if truncated:
            raise PackError(502, "target list was truncated", source="target")
        if len(collected) > 1:
            raise PackError(502, "target response was invalid", source="target")
        if not collected:
            return {"app_id": app_id, "found": False, "account": None}
        return {"app_id": app_id, "found": True, "account": collected[0]}

    def list_groups(self, app_id: str) -> dict[str, object]:
        app_id = _application(app_id)
        groups: list[dict[str, object]] = []
        seen = 0
        start = 1
        total = 0
        truncated = True
        for _page in range(20):
            document = self._json(
                "GET",
                _collection(app_id, "Groups"),
                app_id,
                query=[("startIndex", str(start)), ("count", "100")],
            )
            resources, total = _page_of(document)
            seen += len(resources)
            for item in resources:
                groups.append(_group_view(item))
            if seen >= total or not resources:
                truncated = False
                break
            start += len(resources)
        if truncated:
            raise PackError(502, "target list was truncated", source="target")
        return {"app_id": app_id, "totalResults": total, "groups": groups}

    def create_account(
        self,
        app_id: str,
        user_name: str,
        email: str,
        employee_number: str,
        department: str,
    ) -> dict[str, object]:
        app_id = _application(app_id)
        document = self._json(
            "POST",
            _collection(app_id, "Users"),
            app_id,
            body={
                "schemas": [CORE_USER, ENTERPRISE_URN],
                "userName": user_name,
                "active": True,
                "emails": [{"value": email, "type": "work", "primary": True}],
                ENTERPRISE_URN: {
                    "employeeNumber": employee_number,
                    "department": department,
                },
            },
        )
        return {"app_id": app_id, "account": _account_view(document)}

    def add_member(self, app_id: str, group_name: str, user_id: str) -> dict[str, object]:
        return self._membership(app_id, group_name, user_id, add=True)

    def remove_member(self, app_id: str, group_name: str, user_id: str) -> dict[str, object]:
        return self._membership(app_id, group_name, user_id, add=False)

    def disable_account(self, app_id: str, user_id: str) -> dict[str, object]:
        app_id = _application(app_id)
        user_id = _canonical_user(user_id)
        document = self._json(
            "PATCH",
            _resource(app_id, "Users", user_id),
            app_id,
            body={
                "schemas": [PATCH_OP],
                "Operations": [{"op": "replace", "path": "active", "value": False}],
            },
        )
        return {"app_id": app_id, "account": _account_view(document)}

    def _membership(
        self,
        app_id: str,
        group_name: str,
        user_id: str,
        *,
        add: bool,
    ) -> dict[str, object]:
        app_id = _application(app_id)
        user_id = _canonical_user(user_id)
        group_id = self._find_group(app_id, group_name)
        if add:
            operation: dict[str, object] = {
                "op": "add",
                "path": "members",
                "value": [{"value": user_id, "type": "User"}],
            }
        else:
            operation = {"op": "remove", "path": f'members[value eq "{user_id}"]'}
        document = self._json(
            "PATCH",
            _resource(app_id, "Groups", group_id),
            app_id,
            body={"schemas": [PATCH_OP], "Operations": [operation]},
        )
        if _resource_id(document) != group_id:
            raise PackError(502, "target response was invalid", source="target")
        return {
            "app_id": app_id,
            "group_name": group_name,
            "group_id": group_id,
            "user_id": user_id,
            "member": _member_present(document, user_id),
        }

    def _find_group(self, app_id: str, group_name: str) -> str:
        document = self._json(
            "GET",
            _collection(app_id, "Groups"),
            app_id,
            query=[
                ("startIndex", "1"),
                ("count", "100"),
                ("filter", f"displayName eq {_filter_quote(group_name)}"),
            ],
        )
        resources, _total = _page_of(document)
        found: list[str] = []
        for item in resources:
            if not isinstance(item, dict) or item.get("displayName") != group_name:
                raise PackError(502, "target response was invalid", source="target")
            found.append(_resource_id(item))
        if not found:
            raise PackError(404, "group not found")
        if len(found) != 1:
            raise PackError(502, "target response was invalid", source="target")
        return found[0]

    def _json(
        self,
        method: str,
        path: str,
        app_id: str,
        *,
        query: list[tuple[str, str]] | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        raw = self._request(method, path, app_id, query=query, body=body)
        if not isinstance(raw, dict):
            raise PackError(502, "target response was invalid", source="target")
        return raw

    def _request(
        self,
        method: str,
        path: str,
        app_id: str,
        *,
        query: list[tuple[str, str]] | None = None,
        body: dict[str, object] | None = None,
    ) -> object:
        if method not in {"GET", "POST", "PATCH"}:
            raise PackError(502, "target request failed")
        if not path.startswith("/apps/") or "\\" in path or "://" in path:
            raise PackError(502, "target request failed")
        token = _scim_token(app_id)
        url = _base_url(self._configured) + path
        if query:
            url += "?" + urlencode(query, quote_via=quote)
        data = None
        headers = {
            "Accept": _MEDIA,
            "Authorization": f"Bearer {token}",
            "User-Agent": "iam-playground-mcp",
        }
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = _MEDIA
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                status = int(response.status)
                payload = response.read(_MAX_RESPONSE + 1)
        except PackError:
            raise
        except Exception:
            raise PackError(502, "target request failed") from None
        if len(payload) > _MAX_RESPONSE:
            raise PackError(502, "target response was too large")
        return _interpret(status, payload, token)

    def __repr__(self) -> str:
        return "ScimTarget()"


def _application(app_id: str) -> str:
    if app_id not in APPLICATIONS:
        raise PackError(403, "application is not allowed")
    return app_id


def _canonical_user(user_id: str) -> str:
    try:
        return str(uuid.UUID(user_id))
    except ValueError:
        raise PackError(400, "user_id must be a user id") from None


def _scim_token(app_id: str) -> str:
    env_name = _TOKEN_ENV.get(app_id)
    if env_name is None:
        raise PackError(403, "application is not allowed")
    token = os.environ.get(env_name, "")
    if not _acceptable_token(token):
        raise PackError(503, "scim credential is not configured")
    return token


def _acceptable_token(value: str) -> bool:
    if value == "":
        return False
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        return False
    return not any(ord(char) < 33 or ord(char) == 127 for char in value)


def _base_url(configured: str | None) -> str:
    if configured is not None:
        raw = configured
    else:
        raw = os.environ.get("LAB_TARGET_URL", "")
        if raw == "":
            raw = _DEFAULT_BASE
    if not isinstance(raw, str) or raw == "" or any(char.isspace() for char in raw):
        raise PackError(503, "target url is not configured")
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"} or parts.netloc == "":
        raise PackError(503, "target url is not configured")
    if parts.username is not None or parts.password is not None:
        raise PackError(503, "target url is not configured")
    if parts.query or parts.fragment or "\\" in raw:
        raise PackError(503, "target url is not configured")
    return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"


def _collection(app_id: str, kind: str) -> str:
    if kind not in {"Users", "Groups"}:
        raise PackError(502, "target request failed")
    return f"/apps/{quote(app_id, safe='')}/scim/v2/{kind}"


def _resource(app_id: str, kind: str, resource_id: str) -> str:
    return f"{_collection(app_id, kind)}/{quote(resource_id, safe='')}"


def _filter_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _interpret(status: int, payload: bytes, token: str) -> object:
    if 300 <= status < 400:
        raise PackError(502, "target request failed")
    if status in {401, 403}:
        raise PackError(502, "target rejected the lab credential", source="target")
    if status >= 500:
        raise PackError(502, "target request failed", source="target")
    if status < 200 or status >= 300:
        raise PackError(status, _scim_detail(payload, token), source="target")
    if payload.strip() == b"":
        raise PackError(502, "target response was invalid", source="target")
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise PackError(502, "target response was invalid", source="target") from None
    if not isinstance(parsed, dict):
        raise PackError(502, "target response was invalid", source="target")
    return parsed


def _scim_detail(payload: bytes, token: str) -> str:
    detail = "target request failed"
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        parsed = None
    if isinstance(parsed, dict):
        found = parsed.get("detail")
        if isinstance(found, str) and found != "":
            detail = found
    if token and token in detail:
        detail = detail.replace(token, "[redacted]")
    if len(detail) > 300:
        detail = detail[:300]
    return detail


def _page_of(document: dict[str, object]) -> tuple[list[object], int]:
    total = document.get("totalResults")
    resources = document.get("Resources")
    if type(total) is not int or total < 0 or not isinstance(resources, list):
        raise PackError(502, "target response was invalid", source="target")
    return resources, total


def _account_view(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PackError(502, "target response was invalid", source="target")
    user_name = value.get("userName")
    active = value.get("active")
    if not isinstance(user_name, str) or not isinstance(active, bool):
        raise PackError(502, "target response was invalid", source="target")
    number, department = _enterprise(value.get(ENTERPRISE_URN))
    return {
        "id": _resource_id(value),
        "userName": user_name,
        "active": active,
        "email": _email(value.get("emails")),
        "employee_number": number,
        "department": department,
    }


def _group_view(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PackError(502, "target response was invalid", source="target")
    display_name = value.get("displayName")
    if not isinstance(display_name, str) or display_name == "":
        raise PackError(502, "target response was invalid", source="target")
    return {
        "id": _resource_id(value),
        "displayName": display_name,
        "members": _member_ids(value),
    }


def _resource_id(value: dict[str, object]) -> str:
    raw = value.get("id")
    if not isinstance(raw, str):
        raise PackError(502, "target response was invalid", source="target")
    try:
        return str(uuid.UUID(raw))
    except ValueError:
        raise PackError(502, "target response was invalid", source="target") from None


def _email(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, list):
        raise PackError(502, "target response was invalid", source="target")
    chosen = ""
    for item in value:
        if not isinstance(item, dict):
            raise PackError(502, "target response was invalid", source="target")
        raw = item.get("value")
        if raw is None:
            continue
        if not isinstance(raw, str):
            raise PackError(502, "target response was invalid", source="target")
        if item.get("primary") is True:
            return raw
        if chosen == "":
            chosen = raw
    return chosen


def _enterprise(value: object) -> tuple[str, str]:
    if value is None:
        return "", ""
    if not isinstance(value, dict):
        raise PackError(502, "target response was invalid", source="target")
    number = value.get("employeeNumber", "")
    department = value.get("department", "")
    if not isinstance(number, str) or not isinstance(department, str):
        raise PackError(502, "target response was invalid", source="target")
    return number, department


def _member_ids(value: dict[str, object]) -> list[str]:
    members = value.get("members")
    if members is None:
        return []
    if not isinstance(members, list):
        raise PackError(502, "target response was invalid", source="target")
    found: list[str] = []
    for item in members:
        if not isinstance(item, dict):
            raise PackError(502, "target response was invalid", source="target")
        raw = item.get("value")
        if not isinstance(raw, str):
            raise PackError(502, "target response was invalid", source="target")
        try:
            found.append(str(uuid.UUID(raw)))
        except ValueError:
            raise PackError(502, "target response was invalid", source="target") from None
    return found


def _member_present(document: dict[str, object], user_id: str) -> bool:
    return user_id in _member_ids(document)
