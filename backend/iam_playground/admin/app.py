"""Admin API. Readiness includes the Keycloak discovery issuer."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import httpx
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from iam_playground.auth import bearer_matches
from iam_playground.constants import APPLICATIONS, DISCOVERY_URL, FIXTURE_ID, LOOPBACK_ENDPOINTS
from iam_playground.db import admin_db_ready, database_url_from_env, get_engine
from iam_playground.mcp_pack.app import create_app as create_mcp_app
from iam_playground.readiness import admin_status
from iam_playground.reset_lab import ResetError, reset_from_env
from iam_playground.scim_codec import canonical_uuid
from iam_playground.sql_store import SqlStore

ReadyCheck = Callable[[], tuple[bool, str]]
ResetFn = Callable[[str], None]


class ResetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fixture_id: str


class BindingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app_id: str
    issuer: str
    subject: str
    scim_user_id: str


class ScenarioRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    mode: str


_REFERENCE_DRIVER = "clients/reference/scenario_scim_login_revoke.py"
_FLAGSHIP_SCENARIO = "scim-login-revoke"
_JDBC_SCENARIO = "transaction-rollback"


def _scenarios_dir() -> Path:
    root = os.environ.get("LAB_ROOT", "").strip()
    if root:
        candidate = Path(root) / "scenarios"
        if candidate.is_dir():
            return candidate
    return Path(__file__).resolve().parents[3] / "scenarios"


def _known_scenario_ids() -> set[str]:
    folder = _scenarios_dir()
    found: set[str] = set()
    if not folder.is_dir():
        return found
    for path in folder.glob("*.json"):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(document, dict):
            continue
        scenario_id = document.get("id")
        if isinstance(scenario_id, str) and scenario_id:
            found.add(scenario_id)
    return found


def _read_meta() -> tuple[str, int] | None:
    try:
        engine = get_engine(database_url_from_env())
        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT fixture_id, generation FROM lab_meta")
            ).first()
    except Exception:
        return None
    if row is None or row[0] != FIXTURE_ID:
        return None
    generation = row[1]
    if isinstance(generation, bool) or not isinstance(generation, int):
        try:
            generation = int(generation)
        except (TypeError, ValueError):
            return None
    return FIXTURE_ID, generation


def _activity_rows() -> list[dict[str, object]]:
    try:
        engine = get_engine(database_url_from_env())
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT id::text, scenario_id, generation, created_at
                    FROM runs
                    ORDER BY created_at, id
                    """
                )
            ).all()
    except Exception:
        return []
    items: list[dict[str, object]] = []
    for row in rows:
        created = row[3]
        if hasattr(created, "isoformat"):
            stamp: object = created.isoformat()
        elif created is None:
            stamp = None
        else:
            stamp = str(created)
        items.append(
            {
                "id": row[0],
                "scenario_id": row[1],
                "generation": row[2],
                "created_at": stamp,
            }
        )
    return items


def fetch_discovery() -> object:
    with httpx.Client(timeout=5.0, trust_env=False, follow_redirects=False) as client:
        response = client.get(DISCOVERY_URL, headers={"Accept": "application/json"})
        response.raise_for_status()
        return response.json()


def admin_ready() -> tuple[bool, str]:
    ok, detail = admin_db_ready()
    if not ok:
        return admin_status(False, detail, None, fetch_failed=False)
    try:
        document = fetch_discovery()
    except Exception:
        return admin_status(True, "ok", None, fetch_failed=True)
    return admin_status(True, "ok", document, fetch_failed=False)


def create_app(
    *,
    ready_check: ReadyCheck | None = None,
    token_provider: Callable[[], str] | None = None,
    reset_fn: ResetFn | None = None,
    store: object | None = None,
) -> FastAPI:
    check = ready_check or admin_ready
    tokens = token_provider or (lambda: os.environ.get("LAB_ADMIN_TOKEN", ""))
    do_reset = reset_fn or reset_from_env
    app = FastAPI(title="IAM Playground admin")

    def store_factory() -> object:
        if store is not None:
            return store
        return SqlStore(get_engine(database_url_from_env()))

    @app.get("/healthz", response_model=None)
    def health():
        ok, detail = check()
        if not ok:
            return JSONResponse(status_code=503, content={"ok": False, "check": detail})
        return {"ok": True}

    @app.get("/endpoints")
    def endpoints():
        return dict(LOOPBACK_ENDPOINTS)

    @app.post("/reset", response_model=None)
    def reset(
        body: ResetBody,
        authorization: str | None = Header(default=None),
    ):
        if not bearer_matches(authorization, tokens()):
            return JSONResponse(status_code=401, content={"detail": "admin token required"})
        if body.fixture_id != FIXTURE_ID:
            return JSONResponse(
                status_code=422,
                content={"detail": "fixture is not in this checkpoint"},
            )
        try:
            do_reset(body.fixture_id)
        except ResetError as exc:
            return JSONResponse(status_code=409, content={"detail": exc.detail})
        except Exception:
            return JSONResponse(status_code=500, content={"detail": "reset failed"})
        return {"fixture_id": body.fixture_id, "accepting": True}

    @app.post("/bindings", response_model=None)
    def bind(
        body: BindingBody,
        authorization: str | None = Header(default=None),
    ):
        if not bearer_matches(authorization, tokens()):
            return JSONResponse(status_code=401, content={"detail": "admin token required"})
        if body.app_id not in APPLICATIONS:
            return JSONResponse(status_code=404, content={"detail": "application not found"})
        issuer = body.issuer.strip()
        subject = body.subject.strip()
        if not issuer or not subject:
            return JSONResponse(status_code=422, content={"detail": "issuer and subject are required"})
        user_id = canonical_uuid(body.scim_user_id)
        if user_id is None:
            return JSONResponse(status_code=422, content={"detail": "scim user not found in application"})
        try:
            with store_factory().transaction() as unit:
                if not unit.is_accepting():
                    return JSONResponse(status_code=409, content={"detail": "lab is not accepting"})
                if not unit.user_exists(body.app_id, user_id):
                    return JSONResponse(
                        status_code=422,
                        content={"detail": "scim user not found in application"},
                    )
                unit.upsert_binding(body.app_id, issuer, subject, user_id)
        except Exception:
            return JSONResponse(status_code=503, content={"detail": "dependency"})
        return {
            "app_id": body.app_id,
            "issuer": issuer,
            "subject": subject,
            "scim_user_id": user_id,
        }

    @app.get("/meta", response_model=None)
    def meta():
        found = _read_meta()
        if found is None:
            return JSONResponse(status_code=503, content={"detail": "database query failed"})
        fixture_id, generation = found
        return {"fixture_id": fixture_id, "generation": generation}

    @app.get("/activity", response_model=None)
    def activity():
        return _activity_rows()

    @app.post("/scenarios/run", response_model=None)
    def run_scenario(body: ScenarioRunBody):
        # Accepts the request. Does not execute a driver in this process.
        if body.id == _JDBC_SCENARIO:
            return JSONResponse(
                status_code=409,
                content={"reason": "unavailable until JDBC"},
            )
        if body.id == _FLAGSHIP_SCENARIO and body.mode == "reference":
            return JSONResponse(
                status_code=202,
                content={
                    "id": body.id,
                    "mode": body.mode,
                    "driver": _REFERENCE_DRIVER,
                    "detail": (
                        "The reference driver is "
                        "clients/reference/scenario_scim_login_revoke.py"
                        " and this endpoint does not execute it inline."
                    ),
                },
            )
        if body.id == _FLAGSHIP_SCENARIO or body.id in _known_scenario_ids():
            return JSONResponse(
                status_code=202,
                content={"id": body.id, "mode": body.mode},
            )
        return JSONResponse(status_code=404, content={"detail": "unknown scenario"})

    app.mount("/mcp", create_mcp_app())
    return app


app = create_app()
