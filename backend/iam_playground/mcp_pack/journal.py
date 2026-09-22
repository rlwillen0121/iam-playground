"""Allowlisted mutation_event writer. The SCIM service does not call this yet."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.engine import Connection

from iam_playground.constants import APPLICATIONS

# Ops the SCIM service already journals. Anything else is refused.
_OPS = frozenset({"create", "replace", "delete", "member.add", "member.remove"})
_MAX_GENERATION = 1_000_000_000


def record_event(
    connection: Connection,
    generation: int,
    app_id: str,
    actor: str,
    op: str,
    subject_id: str,
) -> None:
    """Insert one mutation_event on the caller's open transaction.

    Does not commit or roll back. A later rollback writes neither this row
    nor the SCIM change that shares the transaction. Pass the SCIM unit's
    connection, not a new one.
    """
    if type(generation) is not int or generation < 0 or generation > _MAX_GENERATION:
        raise ValueError("generation is invalid")
    if app_id not in APPLICATIONS:
        raise ValueError("app_id is not an application")
    if op not in _OPS:
        raise ValueError("op is not allowlisted")
    actor = _actor(actor)
    subject_id = _subject(subject_id)
    connection.execute(
        text(
            """
            INSERT INTO mutation_journal (generation, app_id, actor, op, subject_id, at)
            VALUES (:generation, :app_id, :actor, :op, :subject_id, :at)
            """
        ),
        {
            "generation": generation,
            "app_id": app_id,
            "actor": actor,
            "op": op,
            "subject_id": subject_id,
            "at": datetime.now(timezone.utc),
        },
    )


def _actor(value: object) -> str:
    if not isinstance(value, str) or value == "" or value != value.strip() or len(value) > 128:
        raise ValueError("actor is invalid")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("actor is invalid")
    return value


def _subject(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("subject_id is not allowlisted")
    parts = value.split(":")
    if len(parts) not in {1, 2}:
        raise ValueError("subject_id is not allowlisted")
    canonical: list[str] = []
    for part in parts:
        try:
            canonical.append(str(uuid.UUID(part)))
        except ValueError:
            raise ValueError("subject_id is not allowlisted") from None
    return ":".join(canonical)
