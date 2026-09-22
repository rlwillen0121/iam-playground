"""Database engines. Connections are opened on use, not at import."""

from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from iam_playground.readiness import evaluate_admin_row, evaluate_target_row


def database_url_from_env() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("database is not configured")
    return url


@lru_cache(maxsize=4)
def get_engine(url: str) -> Engine:
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=0,
        connect_args={"connect_timeout": 3},
    )


def _select_lab_state(connection: Connection) -> tuple[object, tuple | None]:
    one = connection.execute(text("SELECT 1")).scalar_one()
    row = connection.execute(
        text("SELECT generation, accepting, fixture_id FROM lab_meta")
    ).first()
    return one, (tuple(row) if row is not None else None)


def target_ready() -> tuple[bool, str]:
    try:
        engine = get_engine(database_url_from_env())
        with engine.connect() as connection:
            one, row = _select_lab_state(connection)
    except Exception:
        return False, "database query failed"
    if one != 1:
        return False, "database query failed"
    return evaluate_target_row(row)


def admin_db_ready() -> tuple[bool, str]:
    try:
        engine = get_engine(database_url_from_env())
        with engine.connect() as connection:
            one, row = _select_lab_state(connection)
    except Exception:
        return False, "database query failed"
    if one != 1:
        return False, "database query failed"
    return evaluate_admin_row(row)
