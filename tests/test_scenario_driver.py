"""Reference driver speaks HTTP and does not open a database."""

from __future__ import annotations

import ast
import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "clients" / "reference"))

import scenario_scim_login_revoke as driver
from scenario_scim_login_revoke import ISSUER, run_scim_login_revoke

USER_ID = "11111111-1111-4111-8111-111111111111"
READERS = "22222222-2222-4222-8222-222222222222"
ADMINS = "33333333-3333-4333-8333-333333333333"
SCIM_TOKEN = "scim-write-token"
ADMIN_TOKEN = "admin-token"
SUBJECT = "subject-from-caller"
ENTERPRISE = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.lock = threading.Lock()
        self.requests: list[dict[str, Any]] = []


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def do_GET(self) -> None:
        self._take()

    def do_POST(self) -> None:
        self._take()

    def do_PATCH(self) -> None:
        self._take()

    def do_DELETE(self) -> None:
        self._take()

    def log_message(self, format: str, *args: object) -> None:
        return

    def _take(self) -> None:
        server = self.server
        assert isinstance(server, _Server)
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b""
        parts = urlsplit(self.path)
        record = {
            "method": self.command,
            "path": parts.path,
            "query": parse_qs(parts.query),
            "authorization": self.headers.get("Authorization"),
            "body": raw,
        }
        with server.lock:
            server.requests.append(record)
        if self.command == "GET" and parts.path.endswith("/Groups"):
            filt = parse_qs(parts.query).get("filter", [""])[0]
            if "Administrators" in filt:
                body = _group(ADMINS, "Administrators")
            else:
                body = _group(READERS, "Readers")
            self._send(200, body)
            return
        if self.command == "POST" and parts.path.endswith("/Users"):
            self._send(201, {"id": USER_ID, "userName": "alice"})
            return
        if self.command == "POST" and parts.path == "/bindings":
            self._send(200, {"app_id": "app-a", "scim_user_id": USER_ID})
            return
        if self.command == "PATCH":
            self._send(200, {"id": "patched"})
            return
        self._send(500, {"detail": "unexpected"})

    def _send(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Content-Type", "application/json")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)


def _group(group_id: str, name: str) -> dict[str, Any]:
    return {
        "totalResults": 1,
        "startIndex": 1,
        "Resources": [{"id": group_id, "displayName": name, "members": []}],
    }


@pytest.fixture()
def server(monkeypatch: pytest.MonkeyPatch) -> Any:
    httpd = _Server()
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[:2]
    real_connect = socket.create_connection

    def guarded(address: Any, *args: Any, **kwargs: Any) -> Any:
        target_host = address[0]
        target_port = address[1]
        if target_host != host or target_port != port:
            raise AssertionError(f"unexpected connection to {address}")
        return real_connect(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", guarded)
    base = f"http://{host}:{port}"
    try:
        yield httpd, base
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_driver_order_is_create_bind_add_remove_disable(server: tuple[_Server, str]) -> None:
    httpd, base = server
    result = run_scim_login_revoke(
        target_base_url=base,
        admin_base_url=base,
        scim_token=SCIM_TOKEN,
        admin_token=ADMIN_TOKEN,
        subject=SUBJECT,
        timeout=5,
    )
    assert "verdict" not in result
    assert result["user_id"] == USER_ID
    assert result["subject"] == SUBJECT
    assert result["issuer"] == ISSUER
    assert [item["name"] for item in result["operations"]] == [
        "create_user",
        "bind",
        "member_add",
        "member_add",
        "member_remove",
        "deactivate",
    ]
    assert result["operations"][2]["group"] == "Readers"
    assert result["operations"][3]["group"] == "Administrators"
    assert result["operations"][4]["group"] == "Administrators"
    with httpd.lock:
        calls = list(httpd.requests)
    mutating = [call for call in calls if call["method"] != "GET"]
    assert [call["method"] for call in mutating] == ["POST", "POST", "PATCH", "PATCH", "PATCH", "PATCH"]
    assert mutating[0]["path"].endswith("/Users")
    created = json.loads(mutating[0]["body"].decode("utf-8"))
    assert created["userName"] == "alice"
    assert created["active"] is True
    assert created["emails"][0]["value"] == "alice@lab.example"
    assert created[ENTERPRISE]["employeeNumber"] == "E1001"
    assert created[ENTERPRISE]["department"] == "Engineering"
    assert "issuer" not in created
    assert "subject" not in created
    assert mutating[0]["authorization"] == f"Bearer {SCIM_TOKEN}"
    assert mutating[1]["path"] == "/bindings"
    bound = json.loads(mutating[1]["body"].decode("utf-8"))
    assert bound == {
        "app_id": "app-a",
        "issuer": ISSUER,
        "subject": SUBJECT,
        "scim_user_id": USER_ID,
    }
    assert mutating[1]["authorization"] == f"Bearer {ADMIN_TOKEN}"
    added_readers = json.loads(mutating[2]["body"].decode("utf-8"))
    added_admins = json.loads(mutating[3]["body"].decode("utf-8"))
    removed = json.loads(mutating[4]["body"].decode("utf-8"))
    disabled = json.loads(mutating[5]["body"].decode("utf-8"))
    assert mutating[2]["path"].endswith(f"/Groups/{READERS}")
    assert mutating[3]["path"].endswith(f"/Groups/{ADMINS}")
    assert mutating[4]["path"].endswith(f"/Groups/{ADMINS}")
    assert added_readers["Operations"][0]["op"] == "add"
    assert added_readers["Operations"][0]["value"][0]["value"] == USER_ID
    assert added_admins["Operations"][0]["op"] == "add"
    assert removed["Operations"][0]["op"] == "remove"
    assert USER_ID in removed["Operations"][0]["path"]
    assert disabled["Operations"] == [{"op": "replace", "path": "active", "value": False}]
    assert all(call["method"] != "DELETE" for call in calls)


def test_subject_must_be_supplied() -> None:
    with pytest.raises(ValueError, match="subject"):
        run_scim_login_revoke(
            target_base_url="http://127.0.0.1:9",
            admin_base_url="http://127.0.0.1:9",
            scim_token=SCIM_TOKEN,
            admin_token=ADMIN_TOKEN,
            subject="  ",
            timeout=1,
        )


def test_driver_does_not_import_a_database() -> None:
    source_path = Path(driver.__file__)
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "iam_playground" not in imported
    for banned in ("sqlite3", "psycopg", "psycopg2", "sqlalchemy", "asyncpg", "subprocess"):
        assert banned not in imported
