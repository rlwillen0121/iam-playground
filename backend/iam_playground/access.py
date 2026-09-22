"""App-a authorization. Every call reads the database. Nothing is cached."""

from __future__ import annotations

from datetime import datetime, timezone

from iam_playground.constants import DEMO_APP_ID
from iam_playground.records import SessionRow

READERS = "Readers"
EDITORS = "Editors"
ADMINISTRATORS = "Administrators"


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def load_session(unit: object, session_id: str) -> SessionRow | None:
    row = unit.get_session(session_id)
    if row is None or as_utc(row.expires_at) <= datetime.now(timezone.utc):
        return None
    return row


def decisions_for(unit: object, issuer: str, subject: str) -> dict[str, str]:
    user_id = unit.get_binding(DEMO_APP_ID, issuer, subject)
    user = unit.get_user(DEMO_APP_ID, user_id) if user_id else None
    if user is None:
        return {"read": "no_account", "write": "no_account", "admin": "no_account"}
    if user.active is not True:
        return {"read": "disabled", "write": "disabled", "admin": "disabled"}
    read = "allow" if unit.user_in_group_named(DEMO_APP_ID, user.id, READERS) else "not_a_reader"
    write = "allow" if unit.user_in_group_named(DEMO_APP_ID, user.id, EDITORS) else "not_an_editor"
    admin = (
        "allow"
        if unit.user_in_group_named(DEMO_APP_ID, user.id, ADMINISTRATORS)
        else "not_an_administrator"
    )
    return {"read": read, "write": write, "admin": admin}


def me_document(issuer: str, subject: str, decisions: dict[str, str]) -> dict[str, str]:
    return {
        "issuer": issuer,
        "subject": subject,
        "app_id": DEMO_APP_ID,
        "read": decisions["read"],
        "write": decisions["write"],
        "admin": decisions["admin"],
    }
