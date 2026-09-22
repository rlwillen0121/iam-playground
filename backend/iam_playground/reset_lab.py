"""Generation reset. Does not touch the Keycloak realm or its database."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from iam_playground.constants import FIXTURE_ID
from iam_playground.db import database_url_from_env, get_engine
from iam_playground.fixture import group_rows, load_fixture

TRUNCATE_SQL = """
TRUNCATE TABLE
    account_bindings,
    scim_members,
    scim_users,
    scim_groups,
    mutation_journal,
    runs,
    evidence,
    sessions,
    login_transactions
"""

INSERT_GROUPS_SQL = """
INSERT INTO scim_groups (id, app_id, display_name, external_id)
VALUES (CAST(:id AS uuid), :app_id, :display_name, NULL)
"""

UPDATE_GENERATION_SQL = """
UPDATE lab_meta
SET generation = generation + 1,
    fixture_id = :fixture_id,
    seeded_at = now(),
    accepting = true
RETURNING generation
"""


class ResetError(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


def _require_one_row(result: object) -> None:
    # RETURNING is checked instead of rowcount. psycopg does not always report it.
    if result.first() is None:
        raise ResetError("lab_meta row missing")


def apply_reset(engine: Engine, fixture_id: str) -> None:
    if fixture_id != FIXTURE_ID:
        raise ResetError("fixture is not in this checkpoint")
    # Commit the fence before deleting rows so other workers observe it.
    with engine.begin() as connection:
        _mark_not_accepting(connection)
    with engine.begin() as connection:
        _replace_generation(connection, fixture_id)


def _mark_not_accepting(connection: Connection) -> None:
    result = connection.execute(
        text("UPDATE lab_meta SET accepting = false RETURNING generation")
    )
    _require_one_row(result)


def _replace_generation(connection: Connection, fixture_id: str) -> None:
    connection.execute(text(TRUNCATE_SQL))
    rows = group_rows(load_fixture())
    connection.execute(text(INSERT_GROUPS_SQL), rows)
    result = connection.execute(
        text(UPDATE_GENERATION_SQL),
        {"fixture_id": fixture_id},
    )
    _require_one_row(result)


def reset_from_env(fixture_id: str) -> None:
    apply_reset(get_engine(database_url_from_env()), fixture_id)
