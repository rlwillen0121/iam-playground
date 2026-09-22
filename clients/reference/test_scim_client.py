"""HTTP contract tests for the reference SCIM client. No live network."""

from __future__ import annotations

import ast
import inspect
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scim_client
from scim_client import ScimClient, ScimClientError

APP = "app-a"
TOKEN = "lab-token"
USER = "11111111-1111-4111-8111-111111111111"
GROUP = "22222222-2222-4222-8222-222222222222"
MEMBER = "AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE"
ENTERPRISE = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
_FORBIDDEN = frozenset(
    {"actor_id", "issuer", "subject", "binding", "accountbinding", "account_binding"}
)


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
        server = cast(_Server, self.server)
        length_text = self.headers.get("Content-Length", "0")
        try:
            length = int(length_text)
        except (TypeError, ValueError):
            length = 0
        raw = self.rfile.read(length) if length else b""
        record = {
            "method": self.command,
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "content_type": self.headers.get("Content-Type"),
            "accept": self.headers.get("Accept"),
            "body": raw,
        }
        with server.lock:
            server.requests.append(record)
        status = server.response_status
        payload = server.response_body
        if status is None:
            if self.command == "DELETE":
                status = 204
            elif self.command == "POST":
                status = 201
            else:
                status = 200
        if payload is None:
            payload = b"" if status == 204 else b'{"schemas":[],"id":"res-1"}'
        self.close_connection = True
        self.send_response(status)
        if server.location:
            self.send_header("Location", server.location)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        if payload:
            self.send_header("Content-Type", "application/scim+json")
        self.end_headers()
        if payload:
            self.wfile.write(payload)


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler]) -> None:
        super().__init__(address, handler)
        self.requests: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        self.response_status: int | None = None
        self.response_body: bytes | None = None
        self.location: str | None = None


def _json(recorded: dict[str, Any]) -> Any:
    raw = recorded["body"]
    if not isinstance(raw, bytes) or raw == b"":
        raise AssertionError("expected a JSON body")
    parsed = json.loads(raw.decode("utf-8"))
    keys: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                keys.append(key.lower())
                walk(child)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(parsed)
    if _FORBIDDEN.intersection(keys):
        raise AssertionError(keys)
    return parsed


class ScimClientHttpTests(unittest.TestCase):
    httpd: _Server
    base: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.httpd = _Server(("127.0.0.1", 0), _Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        host, port = cls.httpd.server_address[:2]
        cls.base = f"http://{host}:{port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def setUp(self) -> None:
        self.httpd.response_status = None
        self.httpd.response_body = None
        self.httpd.location = None
        self._clear()
        self.client = ScimClient(self.base, APP, TOKEN, timeout=5)

    def _clear(self) -> None:
        with self.httpd.lock:
            self.httpd.requests.clear()

    def _only(self) -> dict[str, Any]:
        with self.httpd.lock:
            self.assertEqual(len(self.httpd.requests), 1)
            return self.httpd.requests[0]

    def _count(self) -> int:
        with self.httpd.lock:
            return len(self.httpd.requests)

    def test_public_api(self) -> None:
        names = (
            "create_user",
            "get_user",
            "list_users",
            "patch_user",
            "delete_user",
            "create_group",
            "list_groups",
            "patch_group_add_member",
            "patch_group_remove_member",
            "delete_group",
            "get_service_provider_config",
            "get_schemas",
        )
        for name in names:
            self.assertTrue(callable(getattr(self.client, name)), name)
        user_params = tuple(inspect.signature(ScimClient.list_users).parameters)
        group_params = tuple(inspect.signature(ScimClient.list_groups).parameters)
        self.assertEqual(user_params, ("self", "start_index", "count", "filter"))
        self.assertEqual(group_params, ("self", "start_index", "count", "filter"))

    def test_create_user_post_body_and_bearer(self) -> None:
        found = self.client.create_user(
            "alice@example.com",
            external_id="hr-alice",
            given_name="Alice",
            family_name="Example",
            email="alice@example.com",
            active=True,
            employee_number="E100",
            department="Engineering",
        )
        self.assertEqual(found, {"schemas": [], "id": "res-1"})
        recorded = self._only()
        self.assertEqual(recorded["method"], "POST")
        self.assertEqual(recorded["path"], f"/apps/{APP}/scim/v2/Users")
        self.assertEqual(recorded["authorization"], f"Bearer {TOKEN}")
        self.assertEqual(recorded["content_type"], "application/scim+json")
        self.assertEqual(recorded["accept"], "application/scim+json")
        self.assertNotIn(TOKEN, str(recorded["path"]))
        self.assertEqual(
            _json(recorded),
            {
                "schemas": [
                    "urn:ietf:params:scim:schemas:core:2.0:User",
                    ENTERPRISE,
                ],
                "userName": "alice@example.com",
                "externalId": "hr-alice",
                "name": {"givenName": "Alice", "familyName": "Example"},
                "emails": [{"value": "alice@example.com", "type": "work", "primary": True}],
                "active": True,
                ENTERPRISE: {"employeeNumber": "E100", "department": "Engineering"},
            },
        )

    def test_list_users_passes_filter(self) -> None:
        text = 'userName eq "alice&bob"'
        self.client.list_users(1, 20, text)
        recorded = self._only()
        self.assertEqual(recorded["method"], "GET")
        self.assertEqual(recorded["body"], b"")
        self.assertEqual(recorded["authorization"], f"Bearer {TOKEN}")
        self.assertNotIn(TOKEN, str(recorded["path"]))
        parts = urlsplit(str(recorded["path"]))
        self.assertEqual(parts.path, f"/apps/{APP}/scim/v2/Users")
        query = parse_qs(parts.query, keep_blank_values=True)
        self.assertEqual(set(query), {"startIndex", "count", "filter"})
        self.assertEqual(query["startIndex"], ["1"])
        self.assertEqual(query["count"], ["20"])
        self.assertEqual(query["filter"], [text])

        self._clear()
        self.client.list_users(4, 1, "")
        query = parse_qs(urlsplit(str(self._only()["path"])).query, keep_blank_values=True)
        self.assertEqual(query["startIndex"], ["4"])
        self.assertEqual(query["filter"], [""])

        self._clear()
        self.client.list_groups(2, 3, 'displayName eq "Readers"')
        recorded = self._only()
        self.assertEqual(recorded["method"], "GET")
        self.assertEqual(recorded["authorization"], f"Bearer {TOKEN}")
        parts = urlsplit(str(recorded["path"]))
        self.assertEqual(parts.path, f"/apps/{APP}/scim/v2/Groups")
        query = parse_qs(parts.query, keep_blank_values=True)
        self.assertEqual(query["startIndex"], ["2"])
        self.assertEqual(query["count"], ["3"])
        self.assertEqual(query["filter"], ['displayName eq "Readers"'])

        self._clear()
        self.client.list_users(1, 10, None)
        query = parse_qs(urlsplit(str(self._only()["path"])).query, keep_blank_values=True)
        self.assertEqual(query["startIndex"], ["1"])
        self.assertEqual(query["count"], ["10"])
        self.assertNotIn("filter", query)

    def test_pagination_is_one_based_and_not_rewritten(self) -> None:
        with self.assertRaises(ValueError):
            self.client.list_users(0, 10, None)
        with self.assertRaises(ValueError):
            self.client.list_groups(1, -1, None)
        self.assertEqual(self._count(), 0)
        self.client.list_users(1, 0, None)
        query = parse_qs(urlsplit(str(self._only()["path"])).query, keep_blank_values=True)
        self.assertEqual(query["startIndex"], ["1"])
        self.assertEqual(query["count"], ["0"])
        self.assertNotIn("filter", query)

    def test_unknown_filter_is_still_sent(self) -> None:
        self.httpd.response_status = 400
        self.httpd.response_body = json.dumps(
            {"detail": "filter is not supported", "scimType": "invalidFilter"}
        ).encode()
        text = 'title eq "nope"'
        with self.assertRaises(ScimClientError) as caught:
            self.client.list_users(1, 5, text)
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(caught.exception.detail, "filter is not supported")
        self.assertEqual(caught.exception.scim_type, "invalidFilter")
        self.assertNotIn(TOKEN, str(caught.exception))
        query = parse_qs(urlsplit(str(self._only()["path"])).query, keep_blank_values=True)
        self.assertEqual(query["filter"], [text])

    def test_patch_user_replace_body(self) -> None:
        self.client.patch_user(
            USER,
            active=False,
            given_name="A",
            family_name="B",
            email="a@example.com",
            employee_number="E2",
            department="Sales",
        )
        recorded = self._only()
        self.assertEqual(recorded["method"], "PATCH")
        self.assertEqual(recorded["path"], f"/apps/{APP}/scim/v2/Users/{USER}")
        self.assertEqual(recorded["authorization"], f"Bearer {TOKEN}")
        self.assertEqual(
            _json(recorded),
            {
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                "Operations": [
                    {"op": "replace", "path": "active", "value": False},
                    {"op": "replace", "path": "name.givenName", "value": "A"},
                    {"op": "replace", "path": "name.familyName", "value": "B"},
                    {
                        "op": "replace",
                        "path": "emails",
                        "value": [{"value": "a@example.com", "type": "work", "primary": True}],
                    },
                    {
                        "op": "replace",
                        "path": f"{ENTERPRISE}:employeeNumber",
                        "value": "E2",
                    },
                    {"op": "replace", "path": f"{ENTERPRISE}:department", "value": "Sales"},
                ],
            },
        )

    def test_patch_user_without_attributes_does_not_send(self) -> None:
        with self.assertRaises(ValueError):
            self.client.patch_user(USER)
        self.assertEqual(self._count(), 0)

    def test_create_group_body(self) -> None:
        self.client.create_group("Readers", external_id="hr-g", members=[MEMBER])
        recorded = self._only()
        self.assertEqual(recorded["method"], "POST")
        self.assertEqual(recorded["path"], f"/apps/{APP}/scim/v2/Groups")
        self.assertEqual(recorded["authorization"], f"Bearer {TOKEN}")
        self.assertEqual(
            _json(recorded),
            {
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
                "displayName": "Readers",
                "externalId": "hr-g",
                "members": [{"value": MEMBER, "type": "User"}],
            },
        )

    def test_patch_group_add_member(self) -> None:
        self.client.patch_group_add_member(GROUP, MEMBER)
        recorded = self._only()
        self.assertEqual(recorded["method"], "PATCH")
        self.assertEqual(recorded["path"], f"/apps/{APP}/scim/v2/Groups/{GROUP}")
        self.assertEqual(recorded["authorization"], f"Bearer {TOKEN}")
        self.assertEqual(recorded["content_type"], "application/scim+json")
        self.assertNotIn(TOKEN, str(recorded["path"]))
        self.assertEqual(
            _json(recorded),
            {
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                "Operations": [
                    {
                        "op": "add",
                        "path": "members",
                        "value": [{"value": MEMBER, "type": "User"}],
                    }
                ],
            },
        )

    def test_patch_group_remove_member(self) -> None:
        self.client.patch_group_remove_member(GROUP, MEMBER)
        recorded = self._only()
        self.assertEqual(recorded["method"], "PATCH")
        self.assertEqual(recorded["path"], f"/apps/{APP}/scim/v2/Groups/{GROUP}")
        self.assertEqual(recorded["authorization"], f"Bearer {TOKEN}")
        self.assertEqual(
            _json(recorded),
            {
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                "Operations": [
                    {"op": "remove", "path": f'members[value eq "{MEMBER}"]'},
                ],
            },
        )

    def test_delete_user_and_group(self) -> None:
        self.assertIsNone(self.client.delete_user(USER))
        recorded = self._only()
        self.assertEqual(recorded["method"], "DELETE")
        self.assertEqual(recorded["path"], f"/apps/{APP}/scim/v2/Users/{USER}")
        self.assertEqual(recorded["authorization"], f"Bearer {TOKEN}")
        self.assertEqual(recorded["body"], b"")
        self._clear()
        self.assertIsNone(self.client.delete_group(GROUP))
        recorded = self._only()
        self.assertEqual(recorded["method"], "DELETE")
        self.assertEqual(recorded["path"], f"/apps/{APP}/scim/v2/Groups/{GROUP}")
        self.assertEqual(recorded["authorization"], f"Bearer {TOKEN}")

    def test_discovery_paths(self) -> None:
        self.assertEqual(
            self.client.get_service_provider_config(),
            {"schemas": [], "id": "res-1"},
        )
        recorded = self._only()
        self.assertEqual(recorded["method"], "GET")
        self.assertEqual(recorded["path"], f"/apps/{APP}/scim/v2/ServiceProviderConfig")
        self.assertEqual(recorded["authorization"], f"Bearer {TOKEN}")
        self.assertEqual(recorded["body"], b"")
        self._clear()
        self.assertEqual(self.client.get_schemas(), {"schemas": [], "id": "res-1"})
        recorded = self._only()
        self.assertEqual(recorded["method"], "GET")
        self.assertEqual(recorded["path"], f"/apps/{APP}/scim/v2/Schemas")
        self.assertEqual(recorded["authorization"], f"Bearer {TOKEN}")

    def test_get_user_does_not_follow_redirects(self) -> None:
        self.httpd.response_status = 302
        self.httpd.response_body = b""
        self.httpd.location = f"{self.base}/stolen"
        with self.assertRaises(ScimClientError) as caught:
            self.client.get_user(USER)
        self.assertEqual(caught.exception.status, 302)
        self.assertNotIn(TOKEN, str(caught.exception))
        recorded = self._only()
        self.assertEqual(recorded["method"], "GET")
        self.assertEqual(recorded["path"], f"/apps/{APP}/scim/v2/Users/{USER}")
        self.assertEqual(recorded["authorization"], f"Bearer {TOKEN}")

    def test_error_detail_redacts_the_token(self) -> None:
        self.httpd.response_status = 401
        self.httpd.response_body = json.dumps({"detail": f"bad {TOKEN}"}).encode()
        with self.assertRaises(ScimClientError) as caught:
            self.client.get_schemas()
        self.assertEqual(caught.exception.status, 401)
        self.assertNotIn(TOKEN, caught.exception.detail)
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertIn("[redacted]", caught.exception.detail)

    def test_client_does_not_import_playground_or_a_database(self) -> None:
        source_path = Path(cast(str, scim_client.__file__))
        source = source_path.read_text(encoding="utf-8")
        self.assertNotIn("iam_playground", source)
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertNotIn("iam_playground", imported)
        for banned in ("sqlite3", "psycopg", "psycopg2", "sqlalchemy", "asyncpg"):
            self.assertNotIn(banned, imported)


if __name__ == "__main__":
    unittest.main()
