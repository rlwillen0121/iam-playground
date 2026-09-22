"""Reference driver for scim-login-revoke. HTTP only. No verdict."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from scim_client import ScimClient, ScimClientError

ISSUER = "http://iam-playground.localhost:8080/realms/iam-playground"
APP_ID = "app-a"
ENTERPRISE_URN = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"

# Final state after the requested operations. The verifier judges observations.
FLAGSHIP = {
    "user_name": "alice",
    "active": False,
    "email": "alice@lab.example",
    "employee_number": "E1001",
    "department": "Engineering",
    "groups": ["Readers"],
    "read_status": 403,
    "read_reason": "disabled",
    "admin_status": 403,
    "admin_reason": "disabled",
}


class DriverResult(dict):
    """Outcome of the reference driver. record_login does not contact Keycloak."""

    def record_login(self, subject: str, session_cookie: str) -> None:
        """Store a caller-supplied subject and lab_session value. The cookie is not logged."""
        self["subject"] = _subject(subject)
        self["session_cookie"] = _session_cookie(session_cookie)

    def __repr__(self) -> str:
        visible = dict(self)
        if "session_cookie" in visible:
            visible["session_cookie"] = "[redacted]"
        return f"{type(self).__name__}({visible!r})"


class DriverStopped(Exception):
    """The driver did not finish. The message is fixed and has no secrets."""

    def __init__(
        self,
        operations: list[dict[str, str]],
        user_id: str | None,
        group_ids: dict[str, str],
        subject: str | None,
        session_cookie: str | None = None,
    ) -> None:
        super().__init__("driver did not finish")
        self.operations = operations
        self.user_id = user_id
        self.group_ids = group_ids
        self.subject = subject
        self.session_cookie = session_cookie

    def record_login(self, subject: str, session_cookie: str) -> None:
        """Store a caller-supplied subject and lab_session value. The cookie is not logged."""
        self.subject = _subject(subject)
        self.session_cookie = _session_cookie(session_cookie)

    def as_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "user_id": self.user_id,
            "group_ids": dict(self.group_ids),
            "subject": self.subject,
            "operations": list(self.operations),
        }
        if self.session_cookie is not None:
            body["session_cookie"] = self.session_cookie
        return body


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Do not follow redirects. A 3xx would resend the admin token."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


def run_scim_login_revoke(
    *,
    target_base_url: str,
    admin_base_url: str,
    scim_token: str,
    admin_token: str,
    subject: str,
    session_cookie: str | None = None,
    timeout: float = 30,
) -> DriverResult:
    """Create Alice, bind the supplied subject, then grant, revoke, and disable.

    subject is whatever the caller passes. This function does not look it up.
    session_cookie is the opaque lab_session value, not a Cookie header.
    When it is provided, the result keeps it for the verifier. This function
    does not sign in and does not contact Keycloak.
    """
    target = _base_url(target_base_url)
    admin = _base_url(admin_base_url)
    subject = _subject(subject)
    recorded_cookie = None if session_cookie is None else _session_cookie(session_cookie)
    _token(admin_token)
    client = ScimClient(target, APP_ID, scim_token, timeout=timeout)
    operations: list[dict[str, str]] = []
    user_id: str | None = None
    group_ids: dict[str, str] = {}
    try:
        group_ids["Readers"] = _find_group(client, "Readers")
        group_ids["Administrators"] = _find_group(client, "Administrators")
        operations.append(
            {"name": "create_user", "method": "POST", "path": f"/apps/{APP_ID}/scim/v2/Users"}
        )
        created = client.create_user(
            "alice",
            email="alice@lab.example",
            employee_number="E1001",
            department="Engineering",
            active=True,
        )
        if not isinstance(created, dict) or not isinstance(created.get("id"), str) or created["id"] == "":
            raise RuntimeError("create user did not return an id")
        user_id = created["id"]
        operations.append({"name": "bind", "method": "POST", "path": "/bindings"})
        _post_binding(
            f"{admin}/bindings",
            admin_token,
            {
                "app_id": APP_ID,
                "issuer": ISSUER,
                "subject": subject,
                "scim_user_id": user_id,
            },
            timeout,
        )
        for display_name, name in (
            ("Readers", "member_add"),
            ("Administrators", "member_add"),
        ):
            group_id = group_ids[display_name]
            operations.append(
                {
                    "name": name,
                    "method": "PATCH",
                    "path": f"/apps/{APP_ID}/scim/v2/Groups/{group_id}",
                    "group": display_name,
                }
            )
            client.patch_group_add_member(group_id, user_id)
        admin_id = group_ids["Administrators"]
        operations.append(
            {
                "name": "member_remove",
                "method": "PATCH",
                "path": f"/apps/{APP_ID}/scim/v2/Groups/{admin_id}",
                "group": "Administrators",
            }
        )
        client.patch_group_remove_member(admin_id, user_id)
        operations.append(
            {
                "name": "deactivate",
                "method": "PATCH",
                "path": f"/apps/{APP_ID}/scim/v2/Users/{user_id}",
            }
        )
        client.patch_user(user_id, active=False)
    except DriverStopped:
        raise
    except (ScimClientError, urllib.error.URLError, TimeoutError, OSError, RuntimeError, ValueError):
        raise DriverStopped(operations, user_id, group_ids, subject, recorded_cookie) from None
    result = DriverResult(
        {
            "user_id": user_id,
            "group_ids": group_ids,
            "subject": subject,
            "issuer": ISSUER,
            "operations": operations,
        }
    )
    if recorded_cookie is not None:
        result["session_cookie"] = recorded_cookie
    return result


def _find_group(client: ScimClient, display_name: str) -> str:
    listed = client.list_groups(1, 50, f'displayName eq "{display_name}"')
    if not isinstance(listed, dict) or not isinstance(listed.get("Resources"), list):
        raise RuntimeError(f"group {display_name} was not listed")
    for item in listed["Resources"]:
        if not isinstance(item, dict):
            continue
        if item.get("displayName") == display_name and isinstance(item.get("id"), str) and item["id"]:
            return item["id"]
    raise RuntimeError(f"group {display_name} was not listed")


def _post_binding(url: str, token: str, payload: dict[str, str], timeout: float) -> None:
    raw = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=raw,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _RefuseRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            status = int(response.status)
            response.read()
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        try:
            exc.read()
        finally:
            exc.close()
    if status < 200 or status >= 300:
        raise RuntimeError(f"binding request failed with HTTP {status}")


def _subject(value: object) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError("subject is required")
    return value.strip()


def _session_cookie(value: object) -> str:
    if not isinstance(value, str) or value == "":
        raise ValueError("session cookie is invalid")
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        raise ValueError("session cookie is invalid") from None
    if any(ord(char) < 33 or ord(char) == 127 for char in value):
        raise ValueError("session cookie is invalid")
    return value


def _token(value: object) -> str:
    if not isinstance(value, str) or value == "":
        raise ValueError("admin token is invalid")
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        raise ValueError("admin token is invalid") from None
    if any(ord(char) < 33 or ord(char) == 127 for char in value):
        raise ValueError("admin token is invalid")
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
