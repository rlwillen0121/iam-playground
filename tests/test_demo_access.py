"""Trusted binding, session cookie, and per-request app-a decisions."""

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from iam_playground.admin.app import create_app as create_admin_app
from iam_playground.constants import EXPECTED_ISSUER
from iam_playground.memory_store import MemoryStore
from iam_playground.targets.app import create_app as create_target_app

TOKEN_A = "token-a"
TOKEN_B = "token-b"
ADMIN = "lab-token"
ISSUER = EXPECTED_ISSUER
SUBJECT = "alice-subject"
ENTERPRISE = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"


def _discovery(**overrides: str) -> dict:
    document = {
        "issuer": ISSUER,
        "authorization_endpoint": ISSUER + "/authorize-from-discovery",
        "token_endpoint": ISSUER + "/token-from-discovery",
        "jwks_uri": ISSUER + "/jwks-from-discovery",
    }
    document.update(overrides)
    return document


def _keys():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private, private.public_key()


def _token(private, **claims: object) -> str:
    now = int(datetime.now(timezone.utc).timestamp())
    body = {"iss": ISSUER, "aud": "demo-app", "sub": SUBJECT, "exp": now + 300, "iat": now}
    body.update(claims)
    return jwt.encode(body, private, algorithm="RS256")


def _apps(store: MemoryStore, **target_kwargs: object):
    target = create_target_app(
        ready_check=lambda: (True, "ok"),
        store=store,
        token_provider=lambda: {"app-a": TOKEN_A, "app-b": TOKEN_B},
        read_token_provider=lambda: {"app-a": "", "app-b": ""},
        **target_kwargs,
    )
    admin = create_admin_app(
        ready_check=lambda: (True, "ok"),
        token_provider=lambda: ADMIN,
        reset_fn=lambda fixture_id: None,
        store=store,
    )
    return target, admin


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


def _session(store: MemoryStore, session_id: str, issuer: str = ISSUER, subject: str = SUBJECT) -> None:
    with store.transaction() as unit:
        unit.insert_session(
            session_id,
            issuer,
            subject,
            datetime.now(timezone.utc) + timedelta(hours=1),
        )


def test_login_uses_discovery_and_callback_hides_tokens():
    private, public = _keys()
    id_token = _token(private)
    seen: dict[str, str] = {}

    def exchange(*, token_endpoint: str, code: str, code_verifier: str) -> dict:
        seen["endpoint"] = token_endpoint
        seen["verifier"] = code_verifier
        seen["code"] = code
        return {"id_token": id_token, "access_token": "access-token-value", "token_type": "Bearer"}

    store = MemoryStore()
    target, _admin = _apps(
        store,
        discovery_fetcher=lambda: _discovery(),
        code_exchanger=exchange,
        signing_key_for=lambda token, jwks_uri: public,
    )
    with TestClient(target, follow_redirects=False) as client:
        started = client.get("/login")
        assert started.status_code == 302
        location = started.headers["location"]
        parsed = urlparse(location)
        assert location.startswith(ISSUER + "/authorize-from-discovery?")
        query = parse_qs(parsed.query)
        assert query["response_type"] == ["code"]
        assert query["client_id"] == ["demo-app"]
        assert query["redirect_uri"] == ["http://127.0.0.1:8090/session/callback"]
        assert query["scope"] == ["openid"]
        assert query["code_challenge_method"] == ["S256"]
        state = query["state"][0]
        verifier = store.logins[state].code_verifier
        assert verifier not in location
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        assert query["code_challenge"] == [challenge]

        callback = client.get("/session/callback", params={"code": "auth-code", "state": state})
        assert callback.status_code == 302
        assert urlparse(callback.headers["location"]).path == "/"
        assert "access-token-value" not in callback.text
        assert id_token not in callback.text
        assert id_token not in str(callback.headers)
        cookie = callback.headers["set-cookie"]
        assert "lab_session=" in cookie
        assert "HttpOnly" in cookie
        assert "samesite=lax" in cookie.lower()
        assert "Path=/" in cookie
        assert "; Secure" not in cookie
        assert callback.headers["X-Lab-Cookie-Policy"] == "local-http-not-secure"
        assert "access-token-value" not in cookie
        assert id_token not in cookie
        assert seen["verifier"] == verifier
        assert seen["endpoint"] == ISSUER + "/token-from-discovery"
        assert seen["code"] == "auth-code"

        me = client.get("/api/me")
        assert me.status_code == 200
        body = me.json()
        assert body["issuer"] == ISSUER
        assert body["subject"] == SUBJECT
        assert body["app_id"] == "app-a"
        assert "id_token" not in me.text
        assert "access_token" not in me.text
        page = client.get("/")
        assert page.status_code == 200
        assert 'href="/login"' in page.text
        assert 'href="/api/read"' in page.text
        assert 'href="/api/admin"' in page.text
        assert SUBJECT in page.text

        replay = client.get("/session/callback", params={"code": "auth-code", "state": state})
        assert replay.status_code == 400

    wrong = MemoryStore()
    bad_target, _admin = _apps(wrong, discovery_fetcher=lambda: _discovery(issuer="http://evil.example/realms/x"))
    with TestClient(bad_target, follow_redirects=False) as client:
        response = client.get("/login")
        assert response.status_code == 503
        assert response.json()["reason"] == "dependency"
        assert "evil.example" not in response.headers.get("location", "")


def test_binding_replace_delete_and_recreate_do_not_keep_access():
    store = MemoryStore()
    target_app, admin_app = _apps(store)
    with TestClient(target_app) as target, TestClient(admin_app) as admin:
        first = target.post("/apps/app-a/scim/v2/Users", headers={"Authorization": f"Bearer {TOKEN_A}"}, json=_user("alice"))
        second = target.post("/apps/app-a/scim/v2/Users", headers={"Authorization": f"Bearer {TOKEN_A}"}, json=_user("ally"))
        assert first.status_code == 201 and second.status_code == 201
        first_id = first.json()["id"]
        second_id = second.json()["id"]
        readers = target.post(
            "/apps/app-a/scim/v2/Groups",
            headers={"Authorization": f"Bearer {TOKEN_A}"},
            json={"displayName": "Readers"},
        )
        admins = target.post(
            "/apps/app-a/scim/v2/Groups",
            headers={"Authorization": f"Bearer {TOKEN_A}"},
            json={"displayName": "Administrators"},
        )
        assert readers.status_code == 201 and admins.status_code == 201

        def bind(user_id: str) -> dict:
            response = admin.post(
                "/bindings",
                headers={"Authorization": f"Bearer {ADMIN}"},
                json={"app_id": "app-a", "issuer": ISSUER, "subject": SUBJECT, "scim_user_id": user_id},
            )
            assert response.status_code == 200, response.text
            return response.json()

        assert bind(first_id)["scim_user_id"] == first_id
        replaced = bind(second_id)
        assert replaced["scim_user_id"] == second_id
        assert store.bindings[("app-a", ISSUER, SUBJECT)] == second_id
        stolen = admin.post(
            "/bindings",
            headers={"Authorization": f"Bearer {TOKEN_A}"},
            json={"app_id": "app-a", "issuer": ISSUER, "subject": SUBJECT, "scim_user_id": first_id},
        )
        assert stolen.status_code == 401
        assert store.bindings[("app-a", ISSUER, SUBJECT)] == second_id

        _session(store, "sess-1")
        target.cookies.set("lab_session", "sess-1")
        assert target.get("/api/read").json()["reason"] == "not_a_reader"
        target.patch(
            f"/apps/app-a/scim/v2/Groups/{readers.json()['id']}",
            headers={"Authorization": f"Bearer {TOKEN_A}"},
            json={"Operations": [{"op": "add", "path": "members", "value": [{"value": second_id}]}]},
        )
        assert target.get("/api/read").status_code == 200
        assert target.get("/api/admin").json()["reason"] == "not_an_administrator"

        target.patch(
            f"/apps/app-a/scim/v2/Groups/{admins.json()['id']}",
            headers={"Authorization": f"Bearer {TOKEN_A}"},
            json={"Operations": [{"op": "add", "path": "members", "value": [{"value": second_id}]}]},
        )
        assert target.get("/api/admin").status_code == 200
        assert target.get("/api/read").status_code == 200

        target.patch(
            f"/apps/app-a/scim/v2/Users/{second_id}",
            headers={"Authorization": f"Bearer {TOKEN_A}"},
            json={"Operations": [{"op": "replace", "path": "active", "value": False}]},
        )
        assert target.get("/api/read").json() == {"reason": "disabled"}
        assert target.get("/api/admin").json() == {"reason": "disabled"}

        deleted = target.delete(
            f"/apps/app-a/scim/v2/Users/{second_id}",
            headers={"Authorization": f"Bearer {TOKEN_A}"},
        )
        assert deleted.status_code == 204
        assert store.bindings == {}
        assert target.get("/api/read").json()["reason"] == "no_account"
        missing = admin.post(
            "/bindings",
            headers={"Authorization": f"Bearer {ADMIN}"},
            json={"app_id": "app-a", "issuer": ISSUER, "subject": SUBJECT, "scim_user_id": second_id},
        )
        assert missing.status_code == 422

        recreated = target.post(
            "/apps/app-a/scim/v2/Users",
            headers={"Authorization": f"Bearer {TOKEN_A}"},
            json=_user("ally"),
        )
        assert recreated.status_code == 201
        new_id = recreated.json()["id"]
        assert new_id != second_id
        target.patch(
            f"/apps/app-a/scim/v2/Groups/{readers.json()['id']}",
            headers={"Authorization": f"Bearer {TOKEN_A}"},
            json={"Operations": [{"op": "add", "path": "members", "value": [{"value": new_id}]}]},
        )
        assert ("app-a", ISSUER, SUBJECT) not in store.bindings
        assert target.get("/api/read").json()["reason"] == "no_account"
        assert target.get("/api/admin").json()["reason"] == "no_account"
        bind(new_id)
        assert target.get("/api/read").status_code == 200
        page = target.get("/")
        assert 'href="/api/admin"' in page.text
        assert "not_an_administrator" in page.text


def test_read_and_admin_denials_and_dependency_failure():
    store = MemoryStore()
    target_app, _admin = _apps(store)
    with TestClient(target_app) as target:
        assert target.get("/api/read").status_code == 401
        assert target.get("/api/admin").json()["reason"] == "no_session"
        _session(store, "sess-1", subject="nobody")
        target.cookies.set("lab_session", "sess-1")
        assert target.get("/api/read").json() == {"reason": "no_account"}
        assert target.get("/api/admin").json() == {"reason": "no_account"}
        home = target.get("/")
        assert 'href="/login"' in home.text
        assert 'href="/api/read"' in home.text
        assert 'href="/api/admin"' in home.text

    class DownStore:
        def transaction(self):
            raise RuntimeError("database query failed")

    down = create_target_app(ready_check=lambda: (True, "ok"), store=DownStore())
    with TestClient(down) as client:
        assert client.get("/api/read").status_code == 401
        client.cookies.set("lab_session", "sess-1")
        failed = client.get("/api/read")
        assert failed.status_code == 503
        assert failed.json() == {"reason": "dependency"}
        assert failed.status_code != 403
        admin_failed = client.get("/api/admin")
        assert admin_failed.status_code == 503
        assert admin_failed.json()["reason"] == "dependency"


def test_callback_rejects_wrong_audience_without_setting_a_cookie():
    private, public = _keys()
    bad_token = _token(private, aud="other-app")
    store = MemoryStore()
    target, _admin = _apps(
        store,
        discovery_fetcher=lambda: _discovery(),
        code_exchanger=lambda **_kwargs: {"id_token": bad_token},
        signing_key_for=lambda token, jwks_uri: public,
    )
    with TestClient(target, follow_redirects=False) as client:
        started = client.get("/login")
        state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
        rejected = client.get("/session/callback", params={"code": "x", "state": state})
        assert rejected.status_code == 401
        assert rejected.json()["reason"] == "rejected"
        assert "set-cookie" not in rejected.headers
        assert store.sessions == {}
        assert bad_token not in rejected.text
