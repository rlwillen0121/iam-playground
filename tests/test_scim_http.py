"""SCIM HTTP behavior, including transaction rollback and app isolation."""

import uuid

from fastapi.testclient import TestClient

from iam_playground.constants import EXPECTED_ISSUER
from iam_playground.memory_store import MemoryStore, MemoryUnit
from iam_playground.scim_filter import parse_equality_filter, parse_page, USER_FILTERS
from iam_playground.sql_store import SqlUnit
from iam_playground.targets.app import create_app

TOKEN_A = "token-a"
TOKEN_B = "token-b"
ENTERPRISE = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"


def _methods(cls: type) -> set[str]:
    return {name for name, value in vars(cls).items() if callable(value) and not name.startswith("_")}


def test_store_units_expose_the_same_operations():
    assert _methods(MemoryUnit) == _methods(SqlUnit)


def test_page_bounds():
    assert parse_page(None, None) == (1, 50)
    assert parse_page("0", "1000") == (1, 100)
    assert parse_page("-3", "1") == (1, 1)


def _app(store: MemoryStore, read_tokens: dict[str, str] | None = None) -> TestClient:
    tokens = {"app-a": "", "app-b": ""} if read_tokens is None else read_tokens
    app = create_app(
        ready_check=lambda: (True, "ok"),
        store=store,
        token_provider=lambda: {"app-a": TOKEN_A, "app-b": TOKEN_B},
        read_token_provider=lambda: tokens,
    )
    return TestClient(app)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _user(user_name: str, **overrides: object) -> dict:
    body: dict = {
        "userName": user_name,
        "name": {"givenName": "Ada", "familyName": "Lovelace"},
        "emails": [{"value": f"{user_name}@lab.example", "type": "work"}],
        "active": True,
        "externalId": f"ext-{user_name}",
        ENTERPRISE: {"employeeNumber": "E1001", "department": "Engineering"},
    }
    body.update(overrides)
    return body


def _create_user(client: TestClient, token: str, user_name: str, **overrides: object) -> dict:
    response = client.post(
        "/apps/app-a/scim/v2/Users" if token == TOKEN_A else "/apps/app-b/scim/v2/Users",
        headers=_auth(token),
        json=_user(user_name, **overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_group(client: TestClient, token: str, app_id: str, display_name: str) -> dict:
    response = client.post(
        f"/apps/{app_id}/scim/v2/Groups",
        headers=_auth(token),
        json={"displayName": display_name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_user_lifecycle_filter_and_pagination():
    store = MemoryStore()
    with _app(store) as client:
        created = _create_user(client, TOKEN_A, "Alice")
        assert created["userName"] == "Alice"
        assert created["name"] == {"givenName": "Ada", "familyName": "Lovelace"}
        assert created["emails"] == [{"value": "Alice@lab.example", "type": "work", "primary": True}]
        assert created[ENTERPRISE] == {"employeeNumber": "E1001", "department": "Engineering"}
        assert created["active"] is True
        user_id = created["id"]
        assert store.journal[-1].actor == "scim:app-a"
        assert store.journal[-1].op == "create"

        duplicate = client.post(
            "/apps/app-a/scim/v2/Users",
            headers=_auth(TOKEN_A),
            json=_user("alice"),
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["scimType"] == "uniqueness"

        other_external = _create_user(client, TOKEN_A, "bob", externalId="ext-Alice")
        assert other_external["externalId"] == "ext-Alice"
        listed = client.get(
            "/apps/app-a/scim/v2/Users",
            headers=_auth(TOKEN_A),
            params={"filter": 'externalId eq "ext-Alice"'},
        )
        assert listed.status_code == 200
        assert listed.json()["totalResults"] == 2

        fetched = client.get(f"/apps/app-a/scim/v2/Users/{user_id}", headers=_auth(TOKEN_A))
        assert fetched.status_code == 200
        assert fetched.json()["userName"] == "Alice"

        found = client.get(
            "/apps/app-a/scim/v2/Users",
            headers=_auth(TOKEN_A),
            params={"filter": 'userName eq "ALICE"'},
        )
        assert found.status_code == 200
        assert found.json()["totalResults"] == 1
        assert found.json()["Resources"][0]["userName"] == "Alice"

        email_hit = client.get(
            "/apps/app-a/scim/v2/Users",
            headers=_auth(TOKEN_A),
            params={"filter": 'emails.value eq "ALICE@lab.example"'},
        )
        assert email_hit.json()["totalResults"] == 1

        inactive = _create_user(client, TOKEN_A, "cara", active=False)
        active_only = client.get(
            "/apps/app-a/scim/v2/Users",
            headers=_auth(TOKEN_A),
            params={"filter": "active eq true"},
        )
        names = {item["userName"] for item in active_only.json()["Resources"]}
        assert inactive["userName"] not in names
        assert "Alice" in names

        for user_name in ("a", "b", "c"):
            _create_user(client, TOKEN_A, user_name)
        page = client.get(
            "/apps/app-a/scim/v2/Users",
            headers=_auth(TOKEN_A),
            params={"startIndex": "2", "count": "1", "filter": 'userName sw "ignored"'},
        )
        # The filter above is unsupported and must not fall through to a page of users.
        assert page.status_code == 400

        page = client.get(
            "/apps/app-a/scim/v2/Users",
            headers=_auth(TOKEN_A),
            params={"startIndex": "2", "count": "1"},
        )
        body = page.json()
        ordered = client.get("/apps/app-a/scim/v2/Users", headers=_auth(TOKEN_A), params={"count": "100"})
        ordered_names = [item["userName"] for item in ordered.json()["Resources"]]
        assert page.status_code == 200
        assert body["totalResults"] == len(ordered_names)
        assert body["startIndex"] == 2
        assert body["itemsPerPage"] == 1
        assert body["schemas"]
        assert body["Resources"][0]["userName"] == ordered_names[1]

        patched = client.patch(
            f"/apps/app-a/scim/v2/Users/{user_id}",
            headers=_auth(TOKEN_A),
            json={
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                "Operations": [
                    {"op": "replace", "path": "active", "value": False},
                    {"op": "replace", "path": "name.givenName", "value": "Augusta"},
                    {"op": "replace", "path": "name.familyName", "value": "King"},
                    {
                        "op": "replace",
                        "path": "emails",
                        "value": [{"value": "queen@lab.example", "type": "work"}],
                    },
                    {
                        "op": "replace",
                        "path": f"{ENTERPRISE}:employeeNumber",
                        "value": "E9",
                    },
                    {
                        "op": "replace",
                        "path": f"{ENTERPRISE}:department",
                        "value": "Sales",
                    },
                ],
            },
        )
        assert patched.status_code == 200, patched.text
        current = patched.json()
        assert current["active"] is False
        assert current["name"]["givenName"] == "Augusta"
        assert current["emails"][0]["value"] == "queen@lab.example"
        assert current[ENTERPRISE]["employeeNumber"] == "E9"
        assert current[ENTERPRISE]["department"] == "Sales"
        assert any(entry.op == "replace" and entry.actor == "scim:app-a" for entry in store.journal)

        deleted = client.delete(f"/apps/app-a/scim/v2/Users/{user_id}", headers=_auth(TOKEN_A))
        assert deleted.status_code == 204
        missing = client.get(f"/apps/app-a/scim/v2/Users/{user_id}", headers=_auth(TOKEN_A))
        assert missing.status_code == 404


def test_unsupported_filter_does_not_return_users():
    store = MemoryStore()
    with _app(store) as client:
        _create_user(client, TOKEN_A, "alice")
        for raw in (
            'userName co "ali"',
            'name.givenName eq "Ada"',
            'userName eq "alice" and active eq true',
            'userName eq',
            "",
        ):
            response = client.get(
                "/apps/app-a/scim/v2/Users",
                headers=_auth(TOKEN_A),
                params={"filter": raw},
            )
            assert response.status_code == 400, raw
            body = response.json()
            assert body["scimType"] == "invalidFilter"
            assert "Resources" not in body
            assert "alice" not in response.text
        unsorted = client.get(
            "/apps/app-a/scim/v2/Users",
            headers=_auth(TOKEN_A),
            params={"sortBy": "userName"},
        )
        assert unsorted.status_code == 400
        assert "Resources" not in unsorted.json()
        try:
            parse_equality_filter('userName co "ali"', USER_FILTERS)
        except Exception as exc:
            assert getattr(exc, "scim_type", None) == "invalidFilter"
        else:
            raise AssertionError("unsupported filter was accepted")


def test_group_membership_duplicate_remove_and_rollback():
    store = MemoryStore()
    with _app(store) as client:
        user = _create_user(client, TOKEN_A, "alice")
        group = _create_group(client, TOKEN_A, "app-a", "Readers")
        _create_group(client, TOKEN_A, "app-a", "Auditors")
        group_id = group["id"]
        user_id = user["id"]
        filtered = client.get(
            "/apps/app-a/scim/v2/Groups",
            headers=_auth(TOKEN_A),
            params={"filter": 'displayName eq "Readers"'},
        )
        assert filtered.status_code == 200
        assert filtered.json()["totalResults"] == 1
        assert filtered.json()["Resources"][0]["displayName"] == "Readers"
        unsupported = client.get(
            "/apps/app-a/scim/v2/Groups",
            headers=_auth(TOKEN_A),
            params={"filter": 'displayName co "R"'},
        )
        assert unsupported.status_code == 400
        assert unsupported.json()["scimType"] == "invalidFilter"
        assert "Resources" not in unsupported.json()
        assert "Auditors" not in unsupported.text

        def add() -> object:
            return client.patch(
                f"/apps/app-a/scim/v2/Groups/{group_id}",
                headers=_auth(TOKEN_A),
                json={
                    "Operations": [
                        {"op": "add", "path": "members", "value": [{"value": user_id}, {"value": user_id}]}
                    ]
                },
            )

        first = add()
        assert first.status_code == 200, first.text
        assert first.json()["members"] == [{"value": user_id, "type": "User"}]
        assert any(
            entry.op == "member.add" and entry.actor == "scim:app-a" and entry.subject_id.endswith(user_id)
            for entry in store.journal
        )
        second = add()
        assert second.status_code == 200
        assert second.json()["members"] == [{"value": user_id, "type": "User"}]
        fetched = client.get(f"/apps/app-a/scim/v2/Groups/{group_id}", headers=_auth(TOKEN_A))
        assert fetched.json()["members"] == [{"value": user_id, "type": "User"}]

        removed = client.patch(
            f"/apps/app-a/scim/v2/Groups/{group_id}",
            headers=_auth(TOKEN_A),
            json={"Operations": [{"op": "remove", "path": f'members[value eq "{user_id}"]'}]},
        )
        assert removed.status_code == 200, removed.text
        assert removed.json()["members"] == []
        assert client.get(f"/apps/app-a/scim/v2/Groups/{group_id}", headers=_auth(TOKEN_A)).json()["members"] == []

        missing = str(uuid.uuid4())
        before = list(store.journal)
        rolled = client.patch(
            f"/apps/app-a/scim/v2/Groups/{group_id}",
            headers=_auth(TOKEN_A),
            json={
                "Operations": [
                    {"op": "add", "path": "members", "value": [{"value": user_id}]},
                    {"op": "add", "path": "members", "value": [{"value": missing}]},
                ]
            },
        )
        assert rolled.status_code == 400
        assert client.get(f"/apps/app-a/scim/v2/Groups/{group_id}", headers=_auth(TOKEN_A)).json()["members"] == []
        assert store.journal == before

        user_rolled = client.patch(
            f"/apps/app-a/scim/v2/Users/{user_id}",
            headers=_auth(TOKEN_A),
            json={
                "Operations": [
                    {"op": "replace", "path": "active", "value": False},
                    {"op": "replace", "path": "name.givenName", "value": "Changed"},
                    {"op": "replace", "path": "userName", "value": "other"},
                ]
            },
        )
        assert user_rolled.status_code == 400
        current = client.get(f"/apps/app-a/scim/v2/Users/{user_id}", headers=_auth(TOKEN_A)).json()
        assert current["active"] is True
        assert current["name"]["givenName"] == "Ada"
        assert current["userName"] == "alice"


def test_put_is_unsupported_and_metadata_is_a_subset():
    store = MemoryStore()
    with _app(store) as client:
        denied = client.put("/apps/app-a/scim/v2/Users", headers=_auth(TOKEN_A), json={})
        assert denied.status_code == 501
        assert "unsupported" in denied.text.lower()
        config = client.get("/apps/app-a/scim/v2/ServiceProviderConfig", headers=_auth(TOKEN_A))
        assert config.status_code == 200
        body = config.json()
        assert body["bulk"]["supported"] is False
        assert body["sort"]["supported"] is False
        assert body["etag"]["supported"] is False
        assert body["patch"]["supported"] is True
        description = body["authenticationSchemes"][0]["description"]
        assert "not a complete RFC 7643 or RFC 7644 implementation" in description
        types = client.get("/apps/app-a/scim/v2/ResourceTypes", headers=_auth(TOKEN_A))
        assert {item["id"] for item in types.json()["Resources"]} == {"User", "Group"}
        schemas = client.get("/apps/app-a/scim/v2/Schemas", headers=_auth(TOKEN_A))
        assert schemas.status_code == 200
        missing = client.get("/apps/app-a/scim/v2/ServiceProviderConfig")
        assert missing.status_code == 401
        unknown = client.get("/apps/no-such-app/scim/v2/Users", headers=_auth(TOKEN_A))
        assert unknown.status_code == 404


def test_app_a_cannot_read_or_patch_app_b():
    store = MemoryStore()
    with _app(store) as client:
        user_b = client.post(
            "/apps/app-b/scim/v2/Users",
            headers=_auth(TOKEN_B),
            json=_user("only-on-b", active=True),
        )
        assert user_b.status_code == 201
        user_b_id = user_b.json()["id"]
        group_b = _create_group(client, TOKEN_B, "app-b", "Readers")
        user_a = _create_user(client, TOKEN_A, "alice")
        group_a = _create_group(client, TOKEN_A, "app-a", "Readers")

        by_path = client.get(f"/apps/app-b/scim/v2/Users/{user_b_id}", headers=_auth(TOKEN_A))
        assert by_path.status_code == 401
        assert "only-on-b" not in by_path.text
        assert TOKEN_A not in by_path.text

        by_id = client.get(f"/apps/app-a/scim/v2/Users/{user_b_id}", headers=_auth(TOKEN_A))
        assert by_id.status_code == 404
        by_group = client.get(f"/apps/app-a/scim/v2/Groups/{group_b['id']}", headers=_auth(TOKEN_A))
        assert by_group.status_code == 404

        patched = client.patch(
            f"/apps/app-b/scim/v2/Users/{user_b_id}",
            headers=_auth(TOKEN_A),
            json={"Operations": [{"op": "replace", "path": "active", "value": False}]},
        )
        assert patched.status_code == 401
        still = client.get(f"/apps/app-b/scim/v2/Users/{user_b_id}", headers=_auth(TOKEN_B))
        assert still.json()["active"] is True

        cross = client.patch(
            f"/apps/app-a/scim/v2/Groups/{group_a['id']}",
            headers=_auth(TOKEN_A),
            json={
                "Operations": [
                    {"op": "add", "path": "members", "value": [{"value": user_a["id"]}]},
                    {"op": "add", "path": "members", "value": [{"value": user_b_id}]},
                ]
            },
        )
        assert cross.status_code == 400
        members = client.get(
            f"/apps/app-a/scim/v2/Groups/{group_a['id']}",
            headers=_auth(TOKEN_A),
        ).json()["members"]
        assert members == []

        listed = client.get("/apps/app-b/scim/v2/Users", headers=_auth(TOKEN_A))
        assert listed.status_code == 401
        assert "only-on-b" not in listed.text


def test_scim_cannot_create_a_binding_or_choose_the_actor(monkeypatch):
    del monkeypatch
    store = MemoryStore()
    with _app(store) as client:
        stolen = _user("carol")
        stolen["issuer"] = EXPECTED_ISSUER
        stolen["subject"] = "subject-1"
        stolen["actor_id"] = "scim:app-b"
        rejected = client.post("/apps/app-a/scim/v2/Users", headers=_auth(TOKEN_A), json=stolen)
        assert rejected.status_code == 400
        assert store.bindings == {}
        listed = client.get("/apps/app-a/scim/v2/Users", headers=_auth(TOKEN_A))
        assert listed.json()["totalResults"] == 0

        created = client.post(
            "/apps/app-a/scim/v2/Users",
            headers=_auth(TOKEN_A),
            json=_user("dave", actor_id="scim:app-b"),
        )
        assert created.status_code == 201
        assert store.journal[-1].actor == "scim:app-a"
        nested = client.patch(
            f"/apps/app-a/scim/v2/Users/{created.json()['id']}",
            headers=_auth(TOKEN_A),
            json={"Operations": [{"op": "replace", "value": {"subject": "stolen"}}]},
        )
        assert nested.status_code == 400
        assert store.bindings == {}
        assert client.post("/bindings", headers=_auth(TOKEN_A), json={}).status_code == 404


def test_read_token_can_get_but_not_modify():
    store = MemoryStore()
    read_tokens = {"app-a": "read-a", "app-b": "read-b"}
    with _app(store, read_tokens) as client:
        created = _create_user(client, TOKEN_A, "alice")
        user_id = created["id"]
        group = _create_group(client, TOKEN_A, "app-a", "Readers")
        fetched = client.get(f"/apps/app-a/scim/v2/Users/{user_id}", headers=_auth("read-a"))
        assert fetched.status_code == 200
        assert fetched.json()["userName"] == "alice"
        config = client.get("/apps/app-a/scim/v2/ServiceProviderConfig", headers=_auth("read-a"))
        assert config.status_code == 200
        listed = client.get("/apps/app-a/scim/v2/Groups", headers=_auth("read-a"))
        assert listed.status_code == 200

        denied = client.post(
            "/apps/app-a/scim/v2/Users",
            headers=_auth("read-a"),
            json=_user("erin"),
        )
        assert denied.status_code == 403
        assert denied.json()["status"] == "403"
        assert "read-a" not in denied.text
        assert client.get("/apps/app-a/scim/v2/Users", headers=_auth(TOKEN_A)).json()["totalResults"] == 1

        patched = client.patch(
            f"/apps/app-a/scim/v2/Users/{user_id}",
            headers=_auth("read-a"),
            json={"Operations": [{"op": "replace", "path": "active", "value": False}]},
        )
        assert patched.status_code == 403
        assert client.get(f"/apps/app-a/scim/v2/Users/{user_id}", headers=_auth("read-a")).json()["active"] is True

        removed = client.delete(f"/apps/app-a/scim/v2/Users/{user_id}", headers=_auth("read-a"))
        assert removed.status_code == 403
        assert client.get(f"/apps/app-a/scim/v2/Users/{user_id}", headers=_auth(TOKEN_A)).status_code == 200

        group_write = client.patch(
            f"/apps/app-a/scim/v2/Groups/{group['id']}",
            headers=_auth("read-a"),
            json={"Operations": [{"op": "add", "path": "members", "value": [{"value": user_id}]}]},
        )
        assert group_write.status_code == 403
        put = client.put(f"/apps/app-a/scim/v2/Users/{user_id}", headers=_auth("read-a"), json={})
        assert put.status_code == 403

        cross = client.get(f"/apps/app-b/scim/v2/Users/{user_id}", headers=_auth("read-a"))
        assert cross.status_code == 401
        other = client.get("/apps/app-a/scim/v2/Users", headers=_auth("read-b"))
        assert other.status_code == 401
        still_writes = client.post(
            "/apps/app-a/scim/v2/Users",
            headers=_auth(TOKEN_A),
            json=_user("frank"),
        )
        assert still_writes.status_code == 201
