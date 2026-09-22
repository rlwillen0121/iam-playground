"""Independent observations. GET only. A success field is not evidence."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_REFERENCE = Path(__file__).resolve().parents[1] / "reference"
_VERIFIER = Path(__file__).resolve().parent
if str(_REFERENCE) not in sys.path:
    sys.path.insert(0, str(_REFERENCE))
if str(_VERIFIER) not in sys.path:
    sys.path.insert(0, str(_VERIFIER))

from flagship import flagship_expectations, judge_stage
from scim_client import ScimClient, ScimClientError

__all__ = [
    "Expectation",
    "VERDICTS",
    "expectation_from",
    "flagship_expectations",
    "judge_stage",
    "verify",
]

ENTERPRISE_URN = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
VERDICTS = ("PASSED", "FAILED", "INDETERMINATE", "CANCELLED")
_COOKIE_NAME = "lab_session"


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Do not follow redirects. A 3xx would resend the session cookie."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


@dataclass(frozen=True)
class Expectation:
    """Final state the verifier compares to what it actually read."""

    user_name: str
    active: bool
    email: str
    employee_number: str
    department: str
    groups: frozenset[str]
    read_status: int
    read_reason: str
    admin_status: int
    admin_reason: str


def expectation_from(document: dict[str, Any]) -> Expectation:
    groups = document["groups"]
    if isinstance(groups, str) or not isinstance(groups, (list, tuple, set, frozenset)):
        raise ValueError("groups must be a set of names")
    return Expectation(
        user_name=_text(document["user_name"], "user_name"),
        active=_boolean(document["active"], "active"),
        email=_text(document["email"], "email"),
        employee_number=_text(document["employee_number"], "employee_number"),
        department=_text(document["department"], "department"),
        groups=frozenset(_text(name, "group") for name in groups),
        read_status=_status(document["read_status"], "read_status"),
        read_reason=_text(document["read_reason"], "read_reason"),
        admin_status=_status(document["admin_status"], "admin_status"),
        admin_reason=_text(document["admin_reason"], "admin_reason"),
    )


def verify(
    *,
    target_base_url: str,
    read_token: str,
    expectation: Expectation,
    user_id: str | None = None,
    session_cookie: str | None = None,
    app_id: str = "app-a",
    timeout: float = 30,
) -> dict[str, Any]:
    """Collect GET observations and judge them. Does not mutate."""
    base = _base_url(target_base_url)
    client = ScimClient(base, app_id, read_token, timeout=timeout)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _RefuseRedirect())
    assertions: list[dict[str, Any]] = []
    missing: list[str] = []

    user, user_state = _load_user(client, user_id, expectation.user_name)
    memberships: list[str] | None = None
    if user_state == "unavailable":
        missing.append("user")
    elif user is None:
        missing.append("user")
    else:
        _compare_user(user, expectation, assertions)
        observed_id = user.get("id")
        if not isinstance(observed_id, str) or observed_id == "":
            missing.append("memberships")
        else:
            names = _memberships(client, observed_id)
            if names is None:
                missing.append("memberships")
            else:
                memberships = sorted(names)
                result = "matched" if names == set(expectation.groups) else "contradicts"
                assertions.append(
                    {
                        "name": "groups",
                        "expected": sorted(expectation.groups),
                        "observed": memberships,
                        "result": result,
                    }
                )

    read_obs: dict[str, Any] | None = None
    admin_obs: dict[str, Any] | None = None
    if not _usable_cookie(session_cookie):
        missing.append("cookie")
    else:
        read_obs = _probe(opener, f"{base}/api/read", session_cookie or "", timeout)
        admin_obs = _probe(opener, f"{base}/api/admin", session_cookie or "", timeout)
        if read_obs is None:
            missing.append("read")
        else:
            assertions.append(_probe_assertion("read", expectation.read_status, expectation.read_reason, read_obs))
        if admin_obs is None:
            missing.append("admin")
        else:
            assertions.append(
                _probe_assertion("admin", expectation.admin_status, expectation.admin_reason, admin_obs)
            )

    verdict = _verdict(assertions, missing)
    user_view = None
    if user is not None and user_state == "ok":
        user_view = _user_view(user)
    return {
        "verdict": verdict,
        "missing": missing,
        "assertions": assertions,
        "observations": {
            "user": user_view,
            "memberships": memberships,
            "read": read_obs,
            "admin": admin_obs,
        },
    }


def _verdict(assertions: list[dict[str, Any]], missing: list[str]) -> str:
    if any(item.get("result") == "contradicts" for item in assertions):
        return "FAILED"
    if missing or any(item.get("result") == "missing" for item in assertions):
        return "INDETERMINATE"
    if not assertions:
        return "INDETERMINATE"
    return "PASSED"


def _compare_user(user: dict[str, Any], expectation: Expectation, assertions: list[dict[str, Any]]) -> None:
    enterprise = user.get(ENTERPRISE_URN)
    extra = enterprise if isinstance(enterprise, dict) else {}
    observed = {
        "user_name": user.get("userName"),
        "active": user.get("active"),
        "email": _email(user),
        "employee_number": extra.get("employeeNumber"),
        "department": extra.get("department"),
    }
    expected = {
        "user_name": expectation.user_name,
        "active": expectation.active,
        "email": expectation.email,
        "employee_number": expectation.employee_number,
        "department": expectation.department,
    }
    for name, want in expected.items():
        got = observed[name]
        assertions.append(
            {
                "name": name,
                "expected": want,
                "observed": got,
                "result": "matched" if got == want else "contradicts",
            }
        )


def _user_view(user: dict[str, Any]) -> dict[str, Any]:
    enterprise = user.get(ENTERPRISE_URN)
    extra = enterprise if isinstance(enterprise, dict) else {}
    return {
        "id": user.get("id"),
        "user_name": user.get("userName"),
        "active": user.get("active"),
        "email": _email(user),
        "employee_number": extra.get("employeeNumber"),
        "department": extra.get("department"),
    }


def _load_user(
    client: ScimClient,
    user_id: str | None,
    user_name: str,
) -> tuple[dict[str, Any] | None, str]:
    if user_id:
        document, state = _get_user(client, user_id)
        if state == "unavailable":
            return None, "unavailable"
        if state == "ok" and isinstance(document, dict):
            return document, "ok"
    return _find_user(client, user_name)


def _get_user(client: ScimClient, user_id: str) -> tuple[dict[str, Any] | None, str]:
    try:
        document = client.get_user(user_id)
    except ScimClientError as exc:
        if exc.status == 404:
            return None, "missing"
        return None, "unavailable"
    except (urllib.error.URLError, TimeoutError, OSError):
        return None, "unavailable"
    if isinstance(document, dict):
        return document, "ok"
    return None, "missing"


def _find_user(client: ScimClient, user_name: str) -> tuple[dict[str, Any] | None, str]:
    try:
        listed = client.list_users(1, 20, f'userName eq "{user_name}"')
    except ScimClientError:
        return None, "unavailable"
    except (urllib.error.URLError, TimeoutError, OSError):
        return None, "unavailable"
    if not isinstance(listed, dict) or not isinstance(listed.get("Resources"), list):
        return None, "unavailable"
    matches = []
    for item in listed["Resources"]:
        if isinstance(item, dict) and isinstance(item.get("userName"), str):
            if item["userName"].casefold() == user_name.casefold():
                matches.append(item)
    if len(matches) != 1:
        return None, "missing"
    return matches[0], "ok"


def _memberships(client: ScimClient, user_id: str) -> set[str] | None:
    wanted = user_id.casefold()
    start = 1
    seen = 0
    names: set[str] = set()
    seen_first: set[str] = set()
    for _ in range(20):
        try:
            page = client.list_groups(start, 100, None)
        except (ScimClientError, urllib.error.URLError, TimeoutError, OSError):
            return None
        if not isinstance(page, dict):
            return None
        resources = page.get("Resources")
        total = page.get("totalResults")
        if not isinstance(resources, list) or type(total) is not int:
            return None
        if not resources:
            return names if seen >= total else None
        first = resources[0].get("id") if isinstance(resources[0], dict) else None
        if isinstance(first, str):
            if first in seen_first:
                return None
            seen_first.add(first)
        for group in resources:
            if not isinstance(group, dict) or "members" not in group:
                return None
            members = group.get("members")
            display = group.get("displayName")
            if not isinstance(members, list):
                return None
            member_ids = set()
            for item in members:
                if isinstance(item, dict) and isinstance(item.get("value"), str):
                    member_ids.add(item["value"].casefold())
            if wanted in member_ids:
                if not isinstance(display, str) or display == "":
                    return None
                names.add(display)
        seen += len(resources)
        if seen >= total:
            return names
        start += len(resources)
    return None


def _probe(
    opener: urllib.request.OpenerDirector,
    url: str,
    cookie: str,
    timeout: float,
) -> dict[str, Any] | None:
    # status and reason only. The success field is not an authorization decision.
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "Cookie": f"{_COOKIE_NAME}={cookie}"},
        method="GET",
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            status = int(response.status)
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        try:
            raw = exc.read()
        finally:
            exc.close()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    if status >= 500:
        return None
    reason = _reason(raw)
    return {"status": status, "reason": reason}


def _reason(raw: bytes) -> str | None:
    if not raw.strip():
        return None
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    found = parsed.get("reason")
    if isinstance(found, str) and found != "":
        return found
    return None


def _probe_assertion(name: str, status: int, reason: str, observed: dict[str, Any]) -> dict[str, Any]:
    matched = observed.get("status") == status and observed.get("reason") == reason
    return {
        "name": name,
        "expected": {"status": status, "reason": reason},
        "observed": {"status": observed.get("status"), "reason": observed.get("reason")},
        "result": "matched" if matched else "contradicts",
    }


def _email(user: dict[str, Any]) -> str | None:
    emails = user.get("emails")
    if not isinstance(emails, list) or not emails:
        return None
    first = emails[0]
    if isinstance(first, dict) and isinstance(first.get("value"), str):
        return first["value"]
    return None


def _usable_cookie(value: str | None) -> bool:
    if not isinstance(value, str) or value == "":
        return False
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        return False
    if any(ord(char) < 33 or ord(char) == 127 for char in value):
        return False
    return True


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


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _status(value: object, name: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    return value
