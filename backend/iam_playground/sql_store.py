"""PostgreSQL store. One engine.begin() is one SCIM or session transaction."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from iam_playground.errors import ScimError
from iam_playground.records import GroupRecord, LoginTxn, SessionRow, UserRecord
from iam_playground.scim_filter import EqFilter

_USER_COLUMNS = """
    id::text, external_id, user_name, active, given_name, family_name,
    email, employee_number, department
"""


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class SqlStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @contextmanager
    def transaction(self) -> Iterator[SqlUnit]:
        with self.engine.begin() as connection:
            yield SqlUnit(connection)


class SqlUnit:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def require_generation(self) -> int:
        generation, accepting = self._lab_row()
        if generation is None or not accepting:
            raise ScimError(409, "lab is not accepting")
        return int(generation)

    def is_accepting(self) -> bool:
        generation, accepting = self._lab_row()
        return generation is not None and accepting

    def username_taken(self, app_id: str, user_name: str) -> bool:
        row = self.connection.execute(
            text(
                """
                SELECT 1 FROM scim_users
                WHERE app_id = :app_id AND lower(user_name) = lower(:user_name)
                LIMIT 1
                """
            ),
            {"app_id": app_id, "user_name": user_name},
        ).first()
        return row is not None

    def insert_user(self, user: UserRecord) -> None:
        self.connection.execute(
            text(
                """
                INSERT INTO scim_users (
                    id, app_id, external_id, user_name, active,
                    given_name, family_name, email, employee_number, department
                ) VALUES (
                    CAST(:id AS uuid), :app_id, :external_id, :user_name, :active,
                    :given_name, :family_name, :email, :employee_number, :department
                )
                """
            ),
            _user_params(user),
        )

    def save_user(self, user: UserRecord) -> None:
        self.connection.execute(
            text(
                """
                UPDATE scim_users SET
                    active = :active,
                    given_name = :given_name,
                    family_name = :family_name,
                    email = :email,
                    employee_number = :employee_number,
                    department = :department
                WHERE app_id = :app_id AND id = CAST(:id AS uuid)
                """
            ),
            _user_params(user),
        )

    def get_user(self, app_id: str, user_id: str) -> UserRecord | None:
        row = self.connection.execute(
            text(
                f"""
                SELECT {_USER_COLUMNS}
                FROM scim_users
                WHERE app_id = :app_id AND id = CAST(:id AS uuid)
                """
            ),
            {"app_id": app_id, "id": user_id},
        ).first()
        if row is None:
            return None
        return _user_from_row(app_id, row)

    def delete_user(self, app_id: str, user_id: str) -> list[str] | None:
        # Memberships have no ON DELETE CASCADE. Bindings do: PostgreSQL runs
        # that cascade as the binding-table owner, so this role only deletes users.
        exists = self.connection.execute(
            text("SELECT 1 FROM scim_users WHERE app_id = :app_id AND id = CAST(:id AS uuid)"),
            {"app_id": app_id, "id": user_id},
        ).first()
        if exists is None:
            return None
        removed = self.connection.execute(
            text(
                """
                DELETE FROM scim_members
                WHERE app_id = :app_id AND user_id = CAST(:id AS uuid)
                RETURNING group_id::text
                """
            ),
            {"app_id": app_id, "id": user_id},
        ).all()
        deleted = self.connection.execute(
            text(
                """
                DELETE FROM scim_users
                WHERE app_id = :app_id AND id = CAST(:id AS uuid)
                RETURNING id::text
                """
            ),
            {"app_id": app_id, "id": user_id},
        ).first()
        if deleted is None:
            return None
        return [str(row[0]) for row in removed]

    def list_users(
        self,
        app_id: str,
        filt: EqFilter | None,
        start_index: int,
        count: int,
    ) -> tuple[list[UserRecord], int]:
        clause, params = _user_filter_sql(filt)
        params["app_id"] = app_id
        total = self.connection.execute(
            text(f"SELECT count(*) FROM scim_users WHERE app_id = :app_id{clause}"),
            params,
        ).scalar_one()
        page_params = dict(params)
        page_params["limit"] = count
        page_params["offset"] = start_index - 1
        rows = self.connection.execute(
            text(
                f"""
                SELECT {_USER_COLUMNS}
                FROM scim_users
                WHERE app_id = :app_id{clause}
                ORDER BY lower(user_name), id
                LIMIT :limit OFFSET :offset
                """
            ),
            page_params,
        ).all()
        return [_user_from_row(app_id, row) for row in rows], int(total)

    def display_name_taken(self, app_id: str, display_name: str) -> bool:
        row = self.connection.execute(
            text(
                """
                SELECT 1 FROM scim_groups
                WHERE app_id = :app_id AND display_name = :display_name
                LIMIT 1
                """
            ),
            {"app_id": app_id, "display_name": display_name},
        ).first()
        return row is not None

    def insert_group(self, group: GroupRecord) -> None:
        self.connection.execute(
            text(
                """
                INSERT INTO scim_groups (id, app_id, display_name, external_id)
                VALUES (CAST(:id AS uuid), :app_id, :display_name, :external_id)
                """
            ),
            {
                "id": group.id,
                "app_id": group.app_id,
                "display_name": group.display_name,
                "external_id": group.external_id,
            },
        )

    def get_group(self, app_id: str, group_id: str) -> GroupRecord | None:
        row = self.connection.execute(
            text(
                """
                SELECT id::text, display_name, external_id
                FROM scim_groups
                WHERE app_id = :app_id AND id = CAST(:id AS uuid)
                """
            ),
            {"app_id": app_id, "id": group_id},
        ).first()
        if row is None:
            return None
        return GroupRecord(id=str(row[0]), app_id=app_id, display_name=row[1], external_id=row[2])

    def delete_group(self, app_id: str, group_id: str) -> list[str] | None:
        exists = self.connection.execute(
            text("SELECT 1 FROM scim_groups WHERE app_id = :app_id AND id = CAST(:id AS uuid)"),
            {"app_id": app_id, "id": group_id},
        ).first()
        if exists is None:
            return None
        removed = self.connection.execute(
            text(
                """
                DELETE FROM scim_members
                WHERE app_id = :app_id AND group_id = CAST(:id AS uuid)
                RETURNING user_id::text
                """
            ),
            {"app_id": app_id, "id": group_id},
        ).all()
        deleted = self.connection.execute(
            text(
                """
                DELETE FROM scim_groups
                WHERE app_id = :app_id AND id = CAST(:id AS uuid)
                RETURNING id::text
                """
            ),
            {"app_id": app_id, "id": group_id},
        ).first()
        if deleted is None:
            return None
        return [str(row[0]) for row in removed]

    def list_groups(
        self,
        app_id: str,
        filt: EqFilter | None,
        start_index: int,
        count: int,
    ) -> tuple[list[tuple[GroupRecord, list[str]]], int]:
        clause, params = _group_filter_sql(filt)
        params["app_id"] = app_id
        total = self.connection.execute(
            text(f"SELECT count(*) FROM scim_groups WHERE app_id = :app_id{clause}"),
            params,
        ).scalar_one()
        page_params = dict(params)
        page_params["limit"] = count
        page_params["offset"] = start_index - 1
        rows = self.connection.execute(
            text(
                f"""
                SELECT id::text, display_name, external_id
                FROM scim_groups
                WHERE app_id = :app_id{clause}
                ORDER BY display_name, id
                LIMIT :limit OFFSET :offset
                """
            ),
            page_params,
        ).all()
        groups = [
            GroupRecord(id=str(row[0]), app_id=app_id, display_name=row[1], external_id=row[2])
            for row in rows
        ]
        return [(group, self.member_ids(app_id, group.id)) for group in groups], int(total)

    def member_ids(self, app_id: str, group_id: str) -> list[str]:
        rows = self.connection.execute(
            text(
                """
                SELECT user_id::text FROM scim_members
                WHERE app_id = :app_id AND group_id = CAST(:group_id AS uuid)
                ORDER BY user_id::text
                """
            ),
            {"app_id": app_id, "group_id": group_id},
        ).all()
        return [str(row[0]) for row in rows]

    def add_member(self, app_id: str, group_id: str, user_id: str) -> bool:
        if not self.user_exists(app_id, user_id):
            raise ScimError(400, "member is not a user in this application", "invalidValue")
        try:
            inserted = self.connection.execute(
                text(
                    """
                    INSERT INTO scim_members (app_id, group_id, user_id)
                    VALUES (:app_id, CAST(:group_id AS uuid), CAST(:user_id AS uuid))
                    ON CONFLICT (app_id, group_id, user_id) DO NOTHING
                    RETURNING user_id::text
                    """
                ),
                {"app_id": app_id, "group_id": group_id, "user_id": user_id},
            ).first()
        except IntegrityError as exc:
            raise ScimError(400, "member is not a user in this application", "invalidValue") from exc
        return inserted is not None

    def remove_member(self, app_id: str, group_id: str, user_id: str) -> bool:
        removed = self.connection.execute(
            text(
                """
                DELETE FROM scim_members
                WHERE app_id = :app_id
                  AND group_id = CAST(:group_id AS uuid)
                  AND user_id = CAST(:user_id AS uuid)
                RETURNING user_id::text
                """
            ),
            {"app_id": app_id, "group_id": group_id, "user_id": user_id},
        ).first()
        return removed is not None

    def user_exists(self, app_id: str, user_id: str) -> bool:
        row = self.connection.execute(
            text("SELECT 1 FROM scim_users WHERE app_id = :app_id AND id = CAST(:id AS uuid)"),
            {"app_id": app_id, "id": user_id},
        ).first()
        return row is not None

    def user_in_group_named(self, app_id: str, user_id: str, display_name: str) -> bool:
        row = self.connection.execute(
            text(
                """
                SELECT 1
                FROM scim_members AS member
                JOIN scim_groups AS grp
                  ON grp.app_id = member.app_id AND grp.id = member.group_id
                WHERE member.app_id = :app_id
                  AND member.user_id = CAST(:user_id AS uuid)
                  AND grp.display_name = :display_name
                LIMIT 1
                """
            ),
            {"app_id": app_id, "user_id": user_id, "display_name": display_name},
        ).first()
        return row is not None

    def journal(self, generation: int, app_id: str, actor: str, op: str, subject_id: str) -> None:
        self.connection.execute(
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

    def upsert_binding(self, app_id: str, issuer: str, subject: str, scim_user_id: str) -> None:
        self.connection.execute(
            text(
                """
                INSERT INTO account_bindings (app_id, issuer, subject, scim_user_id)
                VALUES (:app_id, :issuer, :subject, CAST(:scim_user_id AS uuid))
                ON CONFLICT (app_id, issuer, subject)
                DO UPDATE SET scim_user_id = EXCLUDED.scim_user_id
                """
            ),
            {
                "app_id": app_id,
                "issuer": issuer,
                "subject": subject,
                "scim_user_id": scim_user_id,
            },
        )

    def get_binding(self, app_id: str, issuer: str, subject: str) -> str | None:
        row = self.connection.execute(
            text(
                """
                SELECT scim_user_id::text FROM account_bindings
                WHERE app_id = :app_id AND issuer = :issuer AND subject = :subject
                """
            ),
            {"app_id": app_id, "issuer": issuer, "subject": subject},
        ).first()
        if row is None:
            return None
        return str(row[0])

    def insert_login(self, state: str, code_verifier: str, expires_at: datetime) -> None:
        self.connection.execute(
            text(
                """
                INSERT INTO login_transactions (state, code_verifier, expires_at)
                VALUES (:state, :code_verifier, :expires_at)
                """
            ),
            {"state": state, "code_verifier": code_verifier, "expires_at": expires_at},
        )

    def pop_login(self, state: str) -> LoginTxn | None:
        row = self.connection.execute(
            text(
                """
                DELETE FROM login_transactions
                WHERE state = :state
                RETURNING code_verifier, expires_at
                """
            ),
            {"state": state},
        ).first()
        if row is None or _as_utc(row[1]) <= datetime.now(timezone.utc):
            return None
        return LoginTxn(state=state, code_verifier=row[0], expires_at=row[1])

    def insert_session(self, session_id: str, issuer: str, subject: str, expires_at: datetime) -> None:
        self.connection.execute(
            text(
                """
                INSERT INTO sessions (id, issuer, subject, expires_at)
                VALUES (:id, :issuer, :subject, :expires_at)
                """
            ),
            {"id": session_id, "issuer": issuer, "subject": subject, "expires_at": expires_at},
        )

    def get_session(self, session_id: str) -> SessionRow | None:
        row = self.connection.execute(
            text("SELECT issuer, subject, expires_at FROM sessions WHERE id = :id"),
            {"id": session_id},
        ).first()
        if row is None:
            return None
        return SessionRow(id=session_id, issuer=row[0], subject=row[1], expires_at=row[2])

    def _lab_row(self) -> tuple[object, bool]:
        row = self.connection.execute(text("SELECT generation, accepting FROM lab_meta")).first()
        if row is None:
            return None, False
        return row[0], row[1] is True


def _user_params(user: UserRecord) -> dict[str, object]:
    return {
        "id": user.id,
        "app_id": user.app_id,
        "external_id": user.external_id,
        "user_name": user.user_name,
        "active": user.active,
        "given_name": user.given_name,
        "family_name": user.family_name,
        "email": user.email,
        "employee_number": user.employee_number,
        "department": user.department,
    }


def _user_from_row(app_id: str, row: object) -> UserRecord:
    return UserRecord(
        id=str(row[0]),
        app_id=app_id,
        external_id=row[1],
        user_name=row[2],
        active=bool(row[3]),
        given_name=row[4],
        family_name=row[5],
        email=row[6],
        employee_number=row[7],
        department=row[8],
    )


def _user_filter_sql(filt: EqFilter | None) -> tuple[str, dict[str, object]]:
    if filt is None:
        return "", {}
    if filt.attribute == "userName":
        return " AND lower(user_name) = lower(:filter_value)", {"filter_value": filt.value}
    if filt.attribute == "emails.value":
        return " AND lower(email) = lower(:filter_value)", {"filter_value": filt.value}
    if filt.attribute == "active":
        return " AND active = :filter_value", {"filter_value": filt.value}
    if filt.attribute == "externalId":
        return " AND external_id = :filter_value", {"filter_value": filt.value}
    raise ScimError(400, "filter attribute is not supported", "invalidFilter")


def _group_filter_sql(filt: EqFilter | None) -> tuple[str, dict[str, object]]:
    if filt is None:
        return "", {}
    if filt.attribute == "displayName":
        return " AND display_name = :filter_value", {"filter_value": filt.value}
    raise ScimError(400, "filter attribute is not supported", "invalidFilter")
