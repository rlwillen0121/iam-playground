"""Target API. Health requires a real query and an accepting generation."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from iam_playground.db import database_url_from_env, get_engine, target_ready
from iam_playground.demo_http import mount_demo
from iam_playground.hr.http import mount_hr
from iam_playground.rest import create_router
from iam_playground.scim_http import env_scim_read_tokens, env_scim_tokens, mount_scim
from iam_playground.sql_store import SqlStore

ReadyCheck = Callable[[], tuple[bool, str]]


def create_app(
    ready_check: ReadyCheck | None = None,
    *,
    store: object | None = None,
    token_provider: Callable[[], dict[str, str]] | None = None,
    read_token_provider: Callable[[], dict[str, str]] | None = None,
    discovery_fetcher: Callable[[], dict] | None = None,
    code_exchanger: Callable[..., dict] | None = None,
    signing_key_for: Callable[[str, str], object] | None = None,
) -> FastAPI:
    check = ready_check or target_ready
    app = FastAPI(title="IAM Playground target")

    def health():
        ok, detail = check()
        if not ok:
            return JSONResponse(status_code=503, content={"ok": False, "check": detail})
        return {"ok": True}

    app.add_api_route("/healthz", health, methods=["GET"])
    app.add_api_route("/readyz", health, methods=["GET"])

    def store_factory() -> object:
        if store is not None:
            return store
        return SqlStore(get_engine(database_url_from_env()))

    mount_scim(
        app,
        store_factory=store_factory,
        token_provider=token_provider or env_scim_tokens,
        read_token_provider=read_token_provider or env_scim_read_tokens,
    )
    mount_demo(
        app,
        store_factory=store_factory,
        discovery_fetcher=discovery_fetcher,
        code_exchanger=code_exchanger,
        signing_key_for=signing_key_for,
    )
    # HR routes do not receive the account store. POST /hr/people is not an account write.
    mount_hr(app)
    # One router. Its default store is the REST tables, not scim_users.
    app.include_router(create_router())
    return app


app = create_app()
