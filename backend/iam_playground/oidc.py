"""Authorization code + PKCE and ID token checks. Tokens are not stored."""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import timedelta
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient

from iam_playground.constants import (
    DEMO_CLIENT_ID,
    DEMO_REDIRECT_URI,
    DISCOVERY_URL,
    EXPECTED_ISSUER,
)
from iam_playground.errors import DependencyFailure, TokenRejected

LOGIN_TTL = timedelta(minutes=10)
SESSION_TTL = timedelta(hours=8)


def fetch_discovery() -> dict:
    with httpx.Client(timeout=5.0, trust_env=False, follow_redirects=False) as client:
        response = client.get(DISCOVERY_URL, headers={"Accept": "application/json"})
        response.raise_for_status()
        document = response.json()
    if not isinstance(document, dict):
        raise DependencyFailure("discovery")
    return document


def issuer_endpoint(document: object, name: str) -> str:
    """Use one endpoint from discovery. Reject a document for any other issuer."""
    if not isinstance(document, dict) or document.get("issuer") != EXPECTED_ISSUER:
        raise DependencyFailure("issuer")
    value = document.get(name)
    prefix = EXPECTED_ISSUER + "/"
    if not isinstance(value, str) or not value.startswith(prefix):
        raise DependencyFailure(name)
    return value


def new_pkce() -> tuple[str, str, str]:
    verifier = secrets.token_urlsafe(64)
    if not 43 <= len(verifier) <= 128:
        raise RuntimeError("pkce verifier length")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    state = secrets.token_urlsafe(32)
    return state, verifier, challenge


def authorization_redirect(endpoint: str, *, state: str, challenge: str) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": DEMO_CLIENT_ID,
            "redirect_uri": DEMO_REDIRECT_URI,
            "scope": "openid",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    separator = "&" if "?" in endpoint else "?"
    return f"{endpoint}{separator}{query}"


def exchange_authorization_code(*, token_endpoint: str, code: str, code_verifier: str) -> dict:
    try:
        with httpx.Client(timeout=10.0, trust_env=False, follow_redirects=False) as client:
            response = client.post(
                token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": DEMO_REDIRECT_URI,
                    "client_id": DEMO_CLIENT_ID,
                    "code_verifier": code_verifier,
                },
                headers={"Accept": "application/json"},
            )
    except httpx.HTTPError as exc:
        raise DependencyFailure("token endpoint") from exc
    if response.status_code != 200:
        raise TokenRejected("code")
    try:
        body = response.json()
    except ValueError as exc:
        raise TokenRejected("code") from exc
    if not isinstance(body, dict) or not isinstance(body.get("id_token"), str):
        raise TokenRejected("code")
    return body


def signing_key_from_jwks(token: str, jwks_uri: str):
    if not isinstance(jwks_uri, str) or not jwks_uri.startswith(EXPECTED_ISSUER + "/"):
        raise DependencyFailure("jwks")
    try:
        client = PyJWKClient(jwks_uri, cache_keys=False, cache_jwk_set=False, timeout=5)
        return client.get_signing_key_from_jwt(token).key
    except jwt.PyJWKClientError as exc:
        raise TokenRejected("signature") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenRejected("malformed") from exc


def validate_id_token(
    token: str,
    *,
    verification_key: object,
    issuer: str,
    audience: str,
) -> dict:
    """Reject any alg other than RS256. issuer is the discovery document's issuer."""
    if issuer != EXPECTED_ISSUER:
        raise TokenRejected("issuer")
    if audience != DEMO_CLIENT_ID:
        raise TokenRejected("audience")
    if not isinstance(token, str) or token.count(".") != 2:
        raise TokenRejected("malformed")
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise TokenRejected("malformed") from exc
    if not isinstance(header, dict) or header.get("alg") != "RS256":
        raise TokenRejected("algorithm")
    try:
        claims = jwt.decode(
            token,
            verification_key,
            algorithms=["RS256"],
            audience=DEMO_CLIENT_ID,
            issuer=EXPECTED_ISSUER,
            leeway=0,
            options={
                "require": ["exp", "iss", "aud", "sub"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_iss": True,
                "verify_aud": True,
                "verify_nbf": True,
            },
        )
    except jwt.InvalidTokenError as exc:
        raise TokenRejected("rejected") from exc
    subject = claims.get("sub")
    if not isinstance(subject, str) or subject == "" or "\n" in subject or "\r" in subject:
        raise TokenRejected("subject")
    if claims.get("iss") != EXPECTED_ISSUER:
        raise TokenRejected("issuer")
    return claims
