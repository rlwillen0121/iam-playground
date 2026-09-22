"""Browser sign-in and enforced demo routes. The cookie is an opaque session id."""

from __future__ import annotations

import html
import json
import secrets
from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import Cookie, FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from iam_playground.access import decisions_for, load_session, me_document
from iam_playground.constants import (
    COOKIE_POLICY_HEADER,
    COOKIE_POLICY_VALUE,
    DEMO_APP_ID,
    DEMO_CLIENT_ID,
    SESSION_COOKIE,
)
from iam_playground.errors import DependencyFailure, TokenRejected
from iam_playground.oidc import (
    LOGIN_TTL,
    SESSION_TTL,
    authorization_redirect,
    exchange_authorization_code,
    fetch_discovery,
    issuer_endpoint,
    new_pkce,
    signing_key_from_jwks,
    validate_id_token,
)

StoreFactory = Callable[[], object]
DiscoveryFetcher = Callable[[], dict]
CodeExchanger = Callable[..., dict]
SigningKeyFor = Callable[[str, str], object]


class AccessView:
    def __init__(self, status: int, reason: str | None = None, document: dict | None = None) -> None:
        self.status = status
        self.reason = reason
        self.document = document


def mount_demo(
    app: FastAPI,
    *,
    store_factory: StoreFactory,
    discovery_fetcher: DiscoveryFetcher | None = None,
    code_exchanger: CodeExchanger | None = None,
    signing_key_for: SigningKeyFor | None = None,
) -> None:
    discover = discovery_fetcher or fetch_discovery
    exchange = code_exchanger or exchange_authorization_code
    signing_key = signing_key_for or signing_key_from_jwks

    @app.get("/login", response_model=None)
    def login():
        try:
            document = discover()
            endpoint = issuer_endpoint(document, "authorization_endpoint")
            state, verifier, challenge = new_pkce()
            expires_at = datetime.now(timezone.utc) + LOGIN_TTL
            with store_factory().transaction() as unit:
                unit.insert_login(state, verifier, expires_at)
            location = authorization_redirect(endpoint, state=state, challenge=challenge)
        except Exception:
            return JSONResponse(status_code=503, content={"reason": "dependency"})
        return RedirectResponse(location, status_code=302)

    @app.get("/session/callback", response_model=None)
    def callback(code: str | None = None, state: str | None = None, error: str | None = None):
        if error or not code or not state:
            return JSONResponse(status_code=400, content={"detail": "authorization code was not accepted"})
        try:
            with store_factory().transaction() as unit:
                transaction = unit.pop_login(state)
        except Exception:
            return JSONResponse(status_code=503, content={"reason": "dependency"})
        if transaction is None:
            return JSONResponse(
                status_code=400,
                content={"detail": "login transaction is missing or expired"},
            )
        try:
            document = discover()
            token_endpoint = issuer_endpoint(document, "token_endpoint")
            jwks_uri = issuer_endpoint(document, "jwks_uri")
            token_body = exchange(
                token_endpoint=token_endpoint,
                code=code,
                code_verifier=transaction.code_verifier,
            )
            id_token = token_body["id_token"]
            key = signing_key(id_token, jwks_uri)
            claims = validate_id_token(
                id_token,
                verification_key=key,
                issuer=str(document.get("issuer")),
                audience=DEMO_CLIENT_ID,
            )
            session_id = secrets.token_urlsafe(32)
            with store_factory().transaction() as unit:
                unit.insert_session(
                    session_id,
                    str(claims["iss"]),
                    str(claims["sub"]),
                    datetime.now(timezone.utc) + SESSION_TTL,
                )
        except TokenRejected:
            return JSONResponse(status_code=401, content={"reason": "rejected"})
        except Exception:
            return JSONResponse(status_code=503, content={"reason": "dependency"})
        response = RedirectResponse("/", status_code=302)
        response.set_cookie(
            SESSION_COOKIE,
            session_id,
            httponly=True,
            samesite="lax",
            path="/",
            secure=False,
        )
        # Local HTTP cannot set Secure. The header records that exception.
        response.headers[COOKIE_POLICY_HEADER] = COOKIE_POLICY_VALUE
        return response

    @app.get("/api/me")
    def me(lab_session: str | None = Cookie(default=None)):
        view = evaluate(store_factory(), lab_session)
        if view.document is None:
            return JSONResponse(status_code=view.status, content={"reason": view.reason})
        return view.document

    @app.get("/api/read")
    def read(lab_session: str | None = Cookie(default=None)):
        return _protected(store_factory(), lab_session, "read", "read")

    @app.post("/api/write")
    def write(lab_session: str | None = Cookie(default=None)):
        return _protected(store_factory(), lab_session, "write", "write")

    @app.get("/api/admin")
    def admin(lab_session: str | None = Cookie(default=None)):
        return _protected(store_factory(), lab_session, "admin", "admin")

    @app.get("/", response_class=HTMLResponse)
    def index(lab_session: str | None = Cookie(default=None)):
        view = evaluate(store_factory(), lab_session)
        if view.document is not None:
            decision = json.dumps(view.document, sort_keys=True)
        else:
            decision = json.dumps({"reason": view.reason}, sort_keys=True)
        return HTMLResponse(_page(decision))


def evaluate(store: object, session_id: str | None) -> AccessView:
    if not session_id:
        return AccessView(401, "no_session")
    try:
        with store.transaction() as unit:
            if not unit.is_accepting():
                raise DependencyFailure()
            session = load_session(unit, session_id)
            if session is None:
                return AccessView(401, "no_session")
            document = me_document(
                session.issuer,
                session.subject,
                decisions_for(unit, session.issuer, session.subject),
            )
            return AccessView(200, document=document)
    except Exception:
        return AccessView(503, "dependency")


def _protected(store: object, session_id: str | None, action: str, decision_key: str) -> object:
    view = evaluate(store, session_id)
    if view.document is None:
        return JSONResponse(status_code=view.status, content={"reason": view.reason})
    reason = view.document[decision_key]
    if reason != "allow":
        return JSONResponse(status_code=403, content={"reason": reason})
    return {"allowed": True, "reason": "allow", "app_id": DEMO_APP_ID, "action": action}


def _page(decision: str) -> str:
    safe = html.escape(decision, quote=True)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head><meta charset=\"utf-8\"><title>IAM Playground demo</title></head>\n"
        "<body>\n"
        "<h1>Demo application</h1>\n"
        '<p><a href="/login">Sign in</a></p>\n'
        '<p><a href="/api/read">Read</a></p>\n'
        '<form method="post" action="/api/write"><button type="submit">Write</button></form>\n'
        '<p><a href="/api/admin">Admin</a></p>\n'
        "<h2>Server decision</h2>\n"
        f'<pre id="decision">{safe}</pre>\n'
        "</body>\n"
        "</html>\n"
    )
