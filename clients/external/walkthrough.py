"""External-client example.

HTTP only, through urllib. GET /hr/changes and POST to a target base URL
passed in. Does not run on import. Does not open a database.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlencode, urlsplit

_MEDIA = "application/json"
Json = dict[str, Any] | list[Any] | None


class WalkthroughError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail
        super().__init__(f"HTTP {status}: {detail}")


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Do not follow redirects. A 3xx must not be replayed onto another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


class Walkthrough:
    """Read the HR change feed and POST that document to a caller-supplied URL."""

    def __init__(self, hr_base_url: str, *, timeout: float = 30) -> None:
        self._hr = _base_url(hr_base_url)
        self._timeout = _timeout_value(timeout)
        # Not urlopen: that opener follows redirects and honors proxy env vars.
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _RefuseRedirect(),
        )

    def get_changes(self, after: int) -> dict[str, Any]:
        """GET /hr/changes?after=<sequence> from the HR base URL."""
        if type(after) is not int or after < 0:
            raise ValueError("after must be a non-negative integer")
        query = urlencode({"after": str(after)})
        payload = self._request("GET", f"{self._hr}/hr/changes?{query}", None)
        if not isinstance(payload, dict):
            raise WalkthroughError(0, "changes response was not an object")
        return payload

    def post_target(self, target_base_url: str, body: dict[str, Any] | list[Any]) -> Json:
        """POST body to the target base URL passed in. The URL is not rewritten."""
        if not isinstance(body, (dict, list)):
            raise ValueError("body must be a JSON object or array")
        return self._request("POST", _base_url(target_base_url), body)

    def apply(self, target_base_url: str, after: int) -> Json:
        """Read changes after the sequence, then POST them to target_base_url."""
        return self.post_target(target_base_url, self.get_changes(after))

    def _request(self, method: str, url: str, body: dict[str, Any] | list[Any] | None) -> Json:
        headers = {"Accept": _MEDIA}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
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
        return _interpret(status, raw)


def _base_url(value: object) -> str:
    if not isinstance(value, str) or value == "" or any(char.isspace() for char in value):
        raise ValueError("base URL must be an absolute http(s) URL")
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or parts.netloc == "":
        raise ValueError("base URL must be an absolute http(s) URL")
    if parts.username is not None or parts.password is not None:
        raise ValueError("base URL must not include credentials")
    if parts.query or parts.fragment:
        raise ValueError("base URL must not include a query or fragment")
    return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"


def _timeout_value(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
        raise ValueError("timeout must be a positive number")
    return float(value)


def _interpret(status: int, raw: bytes) -> Json:
    if 200 <= status < 300:
        if status == 204 or raw.strip() == b"":
            return None
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WalkthroughError(status, "response was not JSON") from exc
        if not isinstance(parsed, (dict, list)):
            raise WalkthroughError(status, "response was not a JSON object or array")
        return parsed
    detail = "request failed"
    if raw.strip():
        try:
            parsed_error = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed_error = None
        if isinstance(parsed_error, dict):
            found = parsed_error.get("detail")
            if isinstance(found, str) and found != "":
                detail = found
    if len(detail) > 500:
        detail = detail[:500]
    raise WalkthroughError(status, detail)
