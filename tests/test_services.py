from pathlib import Path

from fastapi.testclient import TestClient

from iam_playground.admin.app import create_app as create_admin_app
from iam_playground.auth import bearer_matches
from iam_playground.constants import EXPECTED_ISSUER, LOOPBACK_ENDPOINTS
from iam_playground.readiness import admin_status
from iam_playground.targets.app import create_app as create_target_app

ROOT = Path(__file__).resolve().parents[1]


def test_target_health_and_ready_share_the_check():
    calls = {"n": 0}

    def check():
        calls["n"] += 1
        if calls["n"] == 1:
            return False, "database query failed"
        return True, "ok"

    app = create_target_app(ready_check=check)
    with TestClient(app) as client:
        denied = client.get("/healthz")
        assert denied.status_code == 503
        assert denied.json()["ok"] is False
        ready = client.get("/readyz")
        assert ready.status_code == 200
        assert ready.json() == {"ok": True}


def test_bearer_token_is_required_and_exact():
    assert bearer_matches(None, "secret") is False
    assert bearer_matches("Bearer secret", "") is False
    assert bearer_matches("Bearer secret", "secret") is True
    assert bearer_matches("bearer secret", "secret") is True
    assert bearer_matches("Bearer other", "secret") is False
    assert bearer_matches("Basic secret", "secret") is False


def test_admin_reset_refuses_missing_token_and_other_fixtures():
    called: list[str] = []
    app = create_admin_app(
        ready_check=lambda: (True, "ok"),
        token_provider=lambda: "lab-token",
        reset_fn=called.append,
    )
    with TestClient(app) as client:
        missing = client.post("/reset", json={"fixture_id": "enterprise-small-v1"})
        assert missing.status_code == 401
        wrong = client.post(
            "/reset",
            headers={"Authorization": "Bearer nope"},
            json={"fixture_id": "enterprise-small-v1"},
        )
        assert wrong.status_code == 401
        other = client.post(
            "/reset",
            headers={"Authorization": "Bearer lab-token"},
            json={"fixture_id": "other-fixture"},
        )
        assert other.status_code == 422
        assert called == []
        accepted = client.post(
            "/reset",
            headers={"Authorization": "Bearer lab-token"},
            json={"fixture_id": "enterprise-small-v1"},
        )
        assert accepted.status_code == 200
        assert accepted.json()["accepting"] is True
        assert called == ["enterprise-small-v1"]


def test_admin_health_uses_issuer_decision():
    def ready():
        return admin_status(
            True,
            "ok",
            {"issuer": "http://wrong.example/realms/iam-playground"},
            fetch_failed=False,
        )

    app = create_admin_app(ready_check=ready, token_provider=lambda: "lab-token")
    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 503
        assert response.json()["check"] == "keycloak issuer does not match"
        endpoints = client.get("/endpoints")
        assert endpoints.status_code == 200
        assert endpoints.json()["issuer"] == EXPECTED_ISSUER
        assert endpoints.json() == LOOPBACK_ENDPOINTS


def test_workbench_page_has_no_tokens():
    html = (ROOT / "workbench" / "index.html").read_text(encoding="utf-8")
    assert "<title>IAM Playground</title>" in html
    for view in ("Overview", "Applications", "Data", "Scenarios", "Activity"):
        assert view in html
    assert "loopback" in html
    assert "synthetic-lab-" not in html
    assert "Bearer " not in html
