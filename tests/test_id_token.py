"""ID token checks. These call the validator directly and do not call Keycloak."""

import base64
import json
from datetime import datetime, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from iam_playground.constants import EXPECTED_ISSUER
from iam_playground.errors import TokenRejected
from iam_playground.oidc import validate_id_token


def _pair():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private, private.public_key()


def _claims(**overrides: object) -> dict:
    now = int(datetime.now(timezone.utc).timestamp())
    body: dict = {
        "iss": EXPECTED_ISSUER,
        "aud": "demo-app",
        "sub": "alice-subject",
        "exp": now + 300,
        "iat": now,
    }
    body.update(overrides)
    return body


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def test_validator_accepts_rs256_and_rejects_bad_claims():
    private, public = _pair()
    good = jwt.encode(_claims(), private, algorithm="RS256")
    claims = validate_id_token(
        good,
        verification_key=public,
        issuer=EXPECTED_ISSUER,
        audience="demo-app",
    )
    assert claims["sub"] == "alice-subject"
    assert claims["iss"] == EXPECTED_ISSUER

    with pytest.raises(TokenRejected):
        validate_id_token(good, verification_key=public, issuer="http://evil.example/realms/other", audience="demo-app")
    with pytest.raises(TokenRejected):
        validate_id_token(good, verification_key=public, issuer=EXPECTED_ISSUER, audience="other-app")

    wrong_issuer = jwt.encode(_claims(iss="http://evil.example/realms/iam-playground"), private, algorithm="RS256")
    wrong_audience = jwt.encode(_claims(aud="other-app"), private, algorithm="RS256")
    expired = jwt.encode(_claims(exp=int(datetime.now(timezone.utc).timestamp()) - 30), private, algorithm="RS256")
    other_private, _other_public = _pair()
    wrong_key = jwt.encode(_claims(), other_private, algorithm="RS256")
    for token in (wrong_issuer, wrong_audience, expired, wrong_key):
        with pytest.raises(TokenRejected):
            validate_id_token(token, verification_key=public, issuer=EXPECTED_ISSUER, audience="demo-app")


def test_validator_rejects_none_and_hs256():
    _private, public = _pair()
    claims = _claims()
    header = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode("utf-8"))
    payload = _b64(json.dumps(claims).encode("utf-8"))
    none_token = f"{header}.{payload}."
    hmac_token = jwt.encode(claims, "not-the-rsa-key", algorithm="HS256")
    for token in (none_token, hmac_token):
        with pytest.raises(TokenRejected) as caught:
            validate_id_token(token, verification_key=public, issuer=EXPECTED_ISSUER, audience="demo-app")
        assert caught.value.reason == "algorithm"
