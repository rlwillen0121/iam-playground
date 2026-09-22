from iam_playground.constants import EXPECTED_ISSUER
from iam_playground.readiness import (
    admin_status,
    discovery_is_ready,
    evaluate_admin_row,
    evaluate_target_row,
)


def test_wrong_issuer_is_not_ready():
    document = {"issuer": "http://evil.example/realms/iam-playground"}
    assert discovery_is_ready(document) is False
    ok, detail = admin_status(True, "ok", document, fetch_failed=False)
    assert ok is False
    assert detail == "keycloak issuer does not match"


def test_exact_issuer_is_ready():
    document = {
        "issuer": EXPECTED_ISSUER,
        "authorization_endpoint": EXPECTED_ISSUER + "/protocol/openid-connect/auth",
    }
    assert discovery_is_ready(document) is True
    assert admin_status(True, "ok", document, fetch_failed=False) == (True, "ok")


def test_issuer_lookalikes_are_not_ready():
    assert discovery_is_ready({"issuer": EXPECTED_ISSUER + "/"}) is False
    assert discovery_is_ready({"issuer": EXPECTED_ISSUER.replace("http://", "https://")}) is False
    assert discovery_is_ready({"issuer": None}) is False
    assert discovery_is_ready({}) is False
    assert discovery_is_ready(["not", "a", "document"]) is False
    assert discovery_is_ready(None) is False


def test_target_row_requires_generation_and_accepting():
    assert evaluate_target_row(None)[0] is False
    assert evaluate_target_row((None, True))[0] is False
    assert evaluate_target_row((1, False))[0] is False
    assert evaluate_target_row((1, True)) == (True, "ok")


def test_admin_row_requires_generation_but_not_accepting():
    assert evaluate_admin_row(None)[0] is False
    assert evaluate_admin_row((None, False, "enterprise-small-v1"))[0] is False
    assert evaluate_admin_row((1, False, "enterprise-small-v1")) == (True, "ok")


def test_discovery_fetch_failure_is_not_ready():
    ok, detail = admin_status(True, "ok", {"issuer": EXPECTED_ISSUER}, fetch_failed=True)
    assert ok is False
    assert "discovery" in detail
