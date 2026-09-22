"""Reference SCIM protocol caller.

HTTP only. Sends Authorization: Bearer. Does not send actor_id or
issuer/subject binding fields. List pagination is 1-based startIndex
and count. A filter string is forwarded unchanged.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Sequence
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

CORE_USER = "urn:ietf:params:scim:schemas:core:2.0:User"
CORE_GROUP = "urn:ietf:params:scim:schemas:core:2.0:Group"
ENTERPRISE_URN = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
PATCH_OP = "urn:ietf:params:scim:api:messages:2.0:PatchOp"

_MEDIA = "application/scim+json"
_SEGMENT = re.compile(r"^[A-Za-z0-9._~-]+$")
_FORBIDDEN = frozenset(
    {
        "actor_id",
        "issuer",
        "subject",
        "binding",
        "accountbinding",
        "account_binding",
    }
)

Json = dict[str, Any] | list[Any] | None


class ScimClientError(Exception):
    """The SCIM service returned a non-success HTTP status."""

    def __init__(self, status: int, detail: str, scim_type: str | None = None) -> None:
        self.status = status
        self.detail = detail
        self.scim_type = scim_type
        super().__init__(f"SCIM HTTP {status}: {detail}")


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Do not follow redirects. A 3xx would resend the bearer token."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


def _segment(value: object, name: str) -> str:
    if not isinstance(value, str) or value in {".", ".."} or _SEGMENT.fullmatch(value) is None:
        raise ValueError(f"{name} is invalid")
    return value


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _optional_str(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _optional_bool(value: object, name: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _timeout_value(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
        raise ValueError("timeout must be a positive number")
    return float(value)


def _token(value: object) -> str:
    if not isinstance(value, str) or value == "":
        raise ValueError("token is invalid")
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        raise ValueError("token is invalid") from None
    if any(ord(char) < 33 or ord(char) == 127 for char in value):
        raise ValueError("token is invalid")
    return value


def _base_url(value: object) -> str:
    if not isinstance(value, str) or value == "" or any(char.isspace() for char in value):
        raise ValueError("base_url must be an absolute http(s) URL")
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or parts.netloc == "":
        raise ValueError("base_url must be an absolute http(s) URL")
    if parts.username is not None or parts.password is not None:
        raise ValueError("base_url must not include credentials")
    if parts.query or parts.fragment:
        raise ValueError("base_url must not include a query or fragment")
    return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"


def _page(name: str, value: object, minimum: int) -> str:
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    if value < minimum:
        if name == "startIndex":
            raise ValueError("startIndex is 1-based")
        raise ValueError("count must be zero or greater")
    return str(value)


def _member_list(members: object) -> list[dict[str, str]] | None:
    if members is None:
        return None
    if isinstance(members, str) or not isinstance(members, Sequence):
        raise ValueError("members must be a sequence of user ids")
    return [{"value": _segment(member, "user_id"), "type": "User"} for member in members]


def _enterprise(employee_number: str | None, department: str | None) -> dict[str, str] | None:
    extra: dict[str, str] = {}
    if employee_number is not None:
        extra["employeeNumber"] = employee_number
    if department is not None:
        extra["department"] = department
    if not extra:
        return None
    return extra


def _reject_forbidden(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and key.lower() in _FORBIDDEN:
                raise ValueError("refusing to send actor or binding fields")
            _reject_forbidden(child)
    elif isinstance(value, list):
        for item in value:
            _reject_forbidden(item)


def _redact(text: str, token: str) -> str:
    if token and token in text:
        return text.replace(token, "[redacted]")
    return text


def _interpret(status: int, raw: bytes, token: str) -> Json:
    if 200 <= status < 300:
        if status == 204:
            return None
        if raw.strip() == b"":
            raise ScimClientError(status, "empty success response")
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ScimClientError(status, "response was not JSON") from None
        if not isinstance(parsed, (dict, list)):
            raise ScimClientError(status, "response was not a SCIM document")
        return parsed
    detail = "request failed"
    scim_type: str | None = None
    parsed_error: object = None
    if raw.strip():
        try:
            parsed_error = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed_error = None
    if isinstance(parsed_error, dict):
        found = parsed_error.get("detail")
        if isinstance(found, str) and found != "":
            detail = found
        kind = parsed_error.get("scimType")
        if isinstance(kind, str) and kind != "":
            scim_type = _redact(kind, token)
    detail = _redact(detail, token)
    if len(detail) > 500:
        detail = detail[:500]
    raise ScimClientError(status, detail, scim_type)


class ScimClient:
    """Call the supported SCIM subset for one application."""

    def __init__(self, base_url: str, app_id: str, token: str, *, timeout: float = 30) -> None:
        self._base = _base_url(base_url)
        self._app_id = _segment(app_id, "app_id")
        self._token = _token(token)
        self._timeout = _timeout_value(timeout)
        # Not urlopen: that opener follows redirects and honors proxy env vars.
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _RefuseRedirect(),
        )

    def __repr__(self) -> str:
        return f"ScimClient(base_url={self._base!r}, app_id={self._app_id!r})"

    def create_user(
        self,
        user_name: str,
        *,
        external_id: str | None = None,
        given_name: str | None = None,
        family_name: str | None = None,
        email: str | None = None,
        active: bool | None = None,
        employee_number: str | None = None,
        department: str | None = None,
    ) -> Json:
        """Create a user. external_id is correlation data, not a uniqueness key."""
        user_name = _required_text(user_name, "user_name")
        external_id = _optional_str(external_id, "external_id")
        given_name = _optional_str(given_name, "given_name")
        family_name = _optional_str(family_name, "family_name")
        email = _optional_str(email, "email")
        active = _optional_bool(active, "active")
        employee_number = _optional_str(employee_number, "employee_number")
        department = _optional_str(department, "department")
        body: dict[str, Any] = {"schemas": [CORE_USER], "userName": user_name}
        if external_id is not None:
            body["externalId"] = external_id
        name: dict[str, str] = {}
        if given_name is not None:
            name["givenName"] = given_name
        if family_name is not None:
            name["familyName"] = family_name
        if name:
            body["name"] = name
        if email is not None:
            body["emails"] = [{"value": email, "type": "work", "primary": True}]
        if active is not None:
            body["active"] = active
        enterprise = _enterprise(employee_number, department)
        if enterprise is not None:
            body["schemas"] = [CORE_USER, ENTERPRISE_URN]
            body[ENTERPRISE_URN] = enterprise
        return self._request("POST", self._collection("Users"), body=body)

    def get_user(self, user_id: str) -> Json:
        """Fetch one user by server-assigned id."""
        return self._request("GET", self._resource("Users", user_id))

    def list_users(self, start_index: int, count: int, filter: str | None = None) -> Json:
        """List users. start_index is 1-based. filter is forwarded unchanged."""
        return self._list("Users", start_index, count, filter)

    def patch_user(
        self,
        user_id: str,
        *,
        active: bool | None = None,
        given_name: str | None = None,
        family_name: str | None = None,
        email: str | None = None,
        employee_number: str | None = None,
        department: str | None = None,
    ) -> Json:
        """Replace the passed user attributes in one PATCH."""
        active = _optional_bool(active, "active")
        given_name = _optional_str(given_name, "given_name")
        family_name = _optional_str(family_name, "family_name")
        email = _optional_str(email, "email")
        employee_number = _optional_str(employee_number, "employee_number")
        department = _optional_str(department, "department")
        operations: list[dict[str, Any]] = []
        if active is not None:
            operations.append({"op": "replace", "path": "active", "value": active})
        if given_name is not None:
            operations.append({"op": "replace", "path": "name.givenName", "value": given_name})
        if family_name is not None:
            operations.append({"op": "replace", "path": "name.familyName", "value": family_name})
        if email is not None:
            operations.append(
                {
                    "op": "replace",
                    "path": "emails",
                    "value": [{"value": email, "type": "work", "primary": True}],
                }
            )
        if employee_number is not None:
            operations.append(
                {
                    "op": "replace",
                    "path": f"{ENTERPRISE_URN}:employeeNumber",
                    "value": employee_number,
                }
            )
        if department is not None:
            operations.append(
                {
                    "op": "replace",
                    "path": f"{ENTERPRISE_URN}:department",
                    "value": department,
                }
            )
        if not operations:
            raise ValueError("patch_user requires at least one attribute")
        return self._patch("Users", user_id, operations)

    def delete_user(self, user_id: str) -> Json:
        """Delete one user by server-assigned id."""
        return self._request("DELETE", self._resource("Users", user_id))

    def create_group(
        self,
        display_name: str,
        *,
        external_id: str | None = None,
        members: Sequence[str] | None = None,
    ) -> Json:
        """Create a group. external_id is correlation data, not a uniqueness key."""
        display_name = _required_text(display_name, "display_name")
        external_id = _optional_str(external_id, "external_id")
        member_values = _member_list(members)
        body: dict[str, Any] = {"schemas": [CORE_GROUP], "displayName": display_name}
        if external_id is not None:
            body["externalId"] = external_id
        if member_values is not None:
            body["members"] = member_values
        return self._request("POST", self._collection("Groups"), body=body)

    def list_groups(self, start_index: int, count: int, filter: str | None = None) -> Json:
        """List groups. start_index is 1-based. filter is forwarded unchanged."""
        return self._list("Groups", start_index, count, filter)

    def patch_group_add_member(self, group_id: str, user_id: str) -> Json:
        """Add one user id to the group."""
        member = _segment(user_id, "user_id")
        operations = [
            {
                "op": "add",
                "path": "members",
                "value": [{"value": member, "type": "User"}],
            }
        ]
        return self._patch("Groups", group_id, operations)

    def patch_group_remove_member(self, group_id: str, user_id: str) -> Json:
        """Remove one user id with a members[value eq \"id\"] filter."""
        member = _segment(user_id, "user_id")
        operations = [{"op": "remove", "path": f'members[value eq "{member}"]'}]
        return self._patch("Groups", group_id, operations)

    def delete_group(self, group_id: str) -> Json:
        """Delete one group by server-assigned id."""
        return self._request("DELETE", self._resource("Groups", group_id))

    def get_service_provider_config(self) -> Json:
        """Fetch ServiceProviderConfig for this application."""
        return self._request("GET", self._collection("ServiceProviderConfig"))

    def get_schemas(self) -> Json:
        """Fetch Schemas for this application."""
        return self._request("GET", self._collection("Schemas"))

    def _collection(self, kind: str) -> str:
        return f"/apps/{quote(self._app_id, safe='')}/scim/v2/{kind}"

    def _resource(self, kind: str, resource_id: str) -> str:
        return f"{self._collection(kind)}/{quote(_segment(resource_id, 'id'), safe='')}"

    def _list(self, kind: str, start_index: object, count: object, filter: object) -> Json:
        # None omits the parameter. Any string, including "", is forwarded unchanged.
        if filter is not None and not isinstance(filter, str):
            raise ValueError("filter must be a string")
        query = [
            ("startIndex", _page("startIndex", start_index, 1)),
            ("count", _page("count", count, 0)),
        ]
        if filter is not None:
            query.append(("filter", filter))
        return self._request("GET", self._collection(kind), query=query)

    def _patch(self, kind: str, resource_id: str, operations: list[dict[str, Any]]) -> Json:
        body = {"schemas": [PATCH_OP], "Operations": operations}
        return self._request("PATCH", self._resource(kind, resource_id), body=body)

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: list[tuple[str, str]] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Json:
        url = self._base + path
        if query:
            url += "?" + urlencode(query, quote_via=quote)
        headers = {
            "Accept": _MEDIA,
            "Authorization": f"Bearer {self._token}",
        }
        data = None
        if body is not None:
            _reject_forbidden(body)
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = _MEDIA
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                status = int(response.status)
                raw = response.read()
        except urllib.error.HTTPError as exc:
            try:
                status = int(exc.code)
                raw = exc.read()
            finally:
                exc.close()
        return _interpret(status, raw, self._token)
