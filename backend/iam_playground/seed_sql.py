"""SQL seed for an empty lab database. No passwords and no SCIM users."""

from __future__ import annotations

from iam_playground.constants import FIXTURE_ID
from iam_playground.fixture import build_fixture, group_rows, validate_fixture


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def render_seed_sql(fixture: dict | None = None) -> str:
    document = fixture or build_fixture()
    validate_fixture(document)
    values = []
    for row in group_rows(document):
        values.append(
            "("
            + sql_literal(row["id"])
            + "::uuid, "
            + sql_literal(row["app_id"])
            + ", "
            + sql_literal(row["display_name"])
            + ")"
        )
    joined = ",\n    ".join(values)
    return (
        f"-- Groups for {FIXTURE_ID}. Inserted only when lab_meta has no row.\n"
        "-- This file does not insert scim_users. A restart must not reseed them.\n"
        "INSERT INTO scim_groups (id, app_id, display_name, external_id)\n"
        "SELECT id, app_id, display_name, NULL\n"
        "FROM (VALUES\n"
        f"    {joined}\n"
        ") AS seed(id, app_id, display_name)\n"
        "WHERE NOT EXISTS (SELECT 1 FROM lab_meta);\n"
        "\n"
        "INSERT INTO lab_meta (generation, fixture_id, seeded_at, accepting)\n"
        f"SELECT 1, {sql_literal(FIXTURE_ID)}, now(), true\n"
        "WHERE NOT EXISTS (SELECT 1 FROM lab_meta);\n"
    )
