"""Verifier verdicts from GET observations. No Docker and no writes."""

from __future__ import annotations

import ast
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clients" / "verifier"))

import verifier
from verifier import Expectation, verify

USER_ID = "11111111-1111-4111-8111-111111111111"
READERS = "22222222-2222-4222-8222-222222222222"
ADMINS = "33333333-3333-4333-8333-333333333333"
ENTERPRISE = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
READ_TOKEN = "read-token"
COOKIE = "session-cookie-value"

READER_ONLY = Expectation(
    user_name="alice",
    active=True,
    email="alice@lab.example",
    employee_number="E1001",
    department="Engineering",
    groups=frozenset({"Readers"}),
    read_status=200,
    read_reason="allow",
    admin_status=403,
    admin_reason="not_an_administrator",
)


def _user() -> dict[str, Any]:
    return {
        "id": USER_ID,
        "userName": "alice",
        "active": True,
        "emails": [{"value": "alice@lab.example", "primary": True}],
        ENTERPRISE: {"employeeNumber": "E1001", "department": "Engineering"},
    }


def _groups(admin_member: bool) -> dict[str, Any]:
    admin_members = [{"value": USER_ID, "type": "User"}] if admin_member else []
    return {
        "totalResults": 2,
        "startIndex": 1,
        "Resources": [
            {
                "id": READERS,
                "displayName": "Readers",
                "members": [{"value": USER_ID, "type": "User"}],
            },
            {
                "id": ADMINS,
                "displayName": "Administrators",
                "members": admin_members,
            },
        ],
    }


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.lock = threading.Lock()
        self.requests: list[dict[str, str | None]] = []
        self.user_status = 200
        self.admin_member = False
        self.read_status = 200
        self.read_body: dict[str, Any] = {"reason": "allow", "success": False, "allowed": True}
        self.admin_status = 403
        self.admin_body: dict[str, Any] = {"reason": "not_an_administrator", "success": True}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def do_GET(self) -> None:
        self._take("GET")

    def do_POST(self) -> None:
        self._take("POST")

    def do_PATCH(self) -> None:
        self._take("PATCH")

    def do_DELETE(self) -> None:
        self._take("DELETE")

    def log_message(self, format: str, *args: object) -> None:
        return

    def _take(self, method: str) -> None:
        server = self.server
        assert isinstance(server, _Server)
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length:
            self.rfile.read(length)
        path = urlsplit(self.path).path
        with server.lock:
            server.requests.append(
                {
                    "method": method,
                    "path": path,
                    "authorization": self.headers.get("Authorization"),
                    "cookie": self.headers.get("Cookie"),
                }
            )
        if method != "GET":
            self._send(500, {"detail": "verifier sent a write"})
            return
        if path == "/api/read":
            self._send(server.read_status, server.read_body)
            return
        if path == "/api/admin":
            self._send(server.admin_status, server.admin_body)
            return
        if path.endswith("/Groups"):
            self._send(200, _groups(server.admin_member))
            return
        if "/Users/" in path:
            if server.user_status != 200:
                self._send(server.user_status, {"detail": "unavailable"})
                return
            self._send(200, _user())
            return
        self._send(404, {"detail": "not found"})

    def _send(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Content-Type", "application/json")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture()
def server() -> Any:
    httpd = _Server()
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        yield httpd, base
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _calls(httpd: _Server) -> list[dict[str, str | None]]:
    with httpd.lock:
        return list(httpd.requests)


def test_missing_cookie_is_indeterminate(server: tuple[_Server, str]) -> None:
    httpd, base = server
    report = verify(
        target_base_url=base,
        read_token=READ_TOKEN,
        expectation=READER_ONLY,
        user_id=USER_ID,
        session_cookie=None,
        timeout=5,
    )
    assert report["verdict"] == "INDETERMINATE"
    assert "cookie" in report["missing"]
    assert all(not str(call["path"]).startswith("/api/") for call in _calls(httpd))
    assert all(call["method"] == "GET" for call in _calls(httpd))


def test_http_503_is_indeterminate(server: tuple[_Server, str]) -> None:
    httpd, base = server
    httpd.user_status = 503
    report = verify(
        target_base_url=base,
        read_token=READ_TOKEN,
        expectation=READER_ONLY,
        user_id=USER_ID,
        session_cookie=COOKIE,
        timeout=5,
    )
    assert report["verdict"] == "INDETERMINATE"
    assert "user" in report["missing"]
    assert report["verdict"] != "PASSED"


def test_extra_admin_membership_is_failed(server: tuple[_Server, str]) -> None:
    httpd, base = server
    httpd.admin_member = True
    report = verify(
        target_base_url=base,
        read_token=READ_TOKEN,
        expectation=READER_ONLY,
        user_id=USER_ID,
        session_cookie=COOKIE,
        timeout=5,
    )
    assert report["verdict"] == "FAILED"
    groups = next(item for item in report["assertions"] if item["name"] == "groups")
    assert groups["result"] == "contradicts"
    assert "Administrators" in groups["observed"]
    assert COOKIE not in json.dumps(report)
    assert all(call["method"] == "GET" for call in _calls(httpd))
    probed = [call for call in _calls(httpd) if str(call["path"]).startswith("/api/")]
    assert {call["path"] for call in probed} == {"/api/read", "/api/admin"}
    assert all(call["authorization"] is None for call in probed)
    assert all(call["cookie"] == f"lab_session={COOKIE}" for call in probed)


def test_matched_observations_pass(server: tuple[_Server, str]) -> None:
    httpd, base = server
    report = verify(
        target_base_url=base,
        read_token=READ_TOKEN,
        expectation=READER_ONLY,
        user_id=USER_ID,
        session_cookie=COOKIE,
        timeout=5,
    )
    assert report["verdict"] == "PASSED"
    assert report["missing"] == []
    assert all(item["result"] == "matched" for item in report["assertions"])
    text = json.dumps(report)
    assert COOKIE not in text
    assert READ_TOKEN not in text
    assert "success" not in text
    scim = [call for call in _calls(httpd) if "/scim/" in str(call["path"])]
    assert scim
    assert all(call["authorization"] == f"Bearer {READ_TOKEN}" for call in scim)


def test_success_true_is_not_evidence(server: tuple[_Server, str]) -> None:
    httpd, base = server
    httpd.read_body = {"success": True}
    httpd.read_status = 200
    httpd.admin_body = {"success": True}
    httpd.admin_status = 200
    report = verify(
        target_base_url=base,
        read_token=READ_TOKEN,
        expectation=READER_ONLY,
        user_id=USER_ID,
        session_cookie=COOKIE,
        timeout=5,
    )
    assert report["verdict"] == "FAILED"
    assert "success" not in json.dumps(report)


def test_connection_error_is_indeterminate() -> None:
    report = verify(
        target_base_url="http://127.0.0.1:1",
        read_token=READ_TOKEN,
        expectation=READER_ONLY,
        user_id=USER_ID,
        session_cookie=COOKIE,
        timeout=1,
    )
    assert report["verdict"] == "INDETERMINATE"


def test_verifier_does_not_import_target_writes() -> None:
    source_path = Path(verifier.__file__)
    source = source_path.read_text(encoding="utf-8")
    assert "iam_playground" not in source
    assert ".get(\"success\")" not in source
    assert '["success"]' not in source
    tree = ast.parse(source)
    imported: set[str] = set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            calls.add(node.func.attr)
    assert "iam_playground" not in imported
    for banned in ("sqlite3", "psycopg", "psycopg2", "sqlalchemy", "asyncpg"):
        assert banned not in imported
    for banned in (
        "create_user",
        "patch_user",
        "delete_user",
        "create_group",
        "patch_group_add_member",
        "patch_group_remove_member",
        "delete_group",
    ):
        assert banned not in calls
    assert "get_user" in calls
    assert "list_groups" in calls
