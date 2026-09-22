"""Report redaction. A fixture password prefix must fail closed."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clients" / "verifier"))

from redact import RedactionError, redact, require_redacted


def test_fixture_password_prefix_fails_redaction_helper():
    report = {"verdict": "PASSED", "leak": "synthetic-lab-alice"}
    try:
        require_redacted(report)
    except RedactionError as exc:
        assert "password prefix" in str(exc)
    else:
        raise AssertionError("expected the redaction helper to fail")


def test_redaction_strips_authorization_cookie_and_password_prefix():
    token = "super-secret-token-value"
    cookie = "session-cookie-value"
    raw = {
        "Authorization": f"Bearer {token}",
        "cookie": f"lab_session={cookie}",
        "trace": f"Authorization: Bearer {token} saw synthetic-lab-bruno",
        "nested": [{"note": f"lab_session={cookie}"}],
    }
    cleaned = redact(raw, extras=[token, cookie])
    text = json.dumps(cleaned, sort_keys=True)
    assert token not in text
    assert cookie not in text
    assert "synthetic-lab-" not in text
    assert "Bearer " not in text or "Bearer [redacted]" in text
    require_redacted(cleaned, extras=[token, cookie])
