"""PostgreSQL store for REST accounts and legacy operations. Not SCIM tables."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from iam_playground.rest.constants import NOT_ACCEPTING
from iam_playground.rest.errors import RestError
from iam_playground.rest.models import Account
from iam_playground.rest.recovery import Operation

_ACCOUNT_COLUMNS = """
    id, login, employee_ref, status, first_name, last_name, department
"""

_OPERATION_COLUMNS = """
    id, app_id, client_id, idempotency_key, payload_hash, payload, kind, state,
    account_id, role_name, applied, error, generation, created_at
"""


class SqlRestStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @contextmanager
    def transaction(self) -> Iterator[SqlRestUnit]:
        with self.engine.begin() as connection:
            yield SqlRestUnit(connection)


class SqlRestUnit:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def lab_state(self) -> tuple[int, bool]:
        row = self.connection.execute(text("SELECT generation, accepting FROM lab_meta")).first()
        if row is None:
            return 0, False
        return int(row[0]), bool(row[1])

    def require_generation(self) -> int:
        generation, accepting = self.lab_state()
        if not accepting:
            raise RestError(409, NOT_ACCEPTING)
        return generation

    @contextmanager
    def savepoint(self) -> Iterator[None]:
        with self.connection.begin_nested():
            yield

    def allocate_id(self, app_id: str) -> int:
        row = self.connection.execute(
            text(
                """
                UPDATE rest_id_alloc
                SET next_id = next_id + 1
                WHERE app_id = :app_id
                RETURNING next_id - 1
                """
            ),
            {"app_id": app_id},
        ).first()
        if row is None:
            raise RuntimeError("id allocator missing")
        return int(row[0])

    def login_taken(self, app_id: str, login: str, except_id: int | None = None) -> bool:
        row = self.connection.execute(
            text(
                """
                SELECT 1 FROM rest_accounts
                WHERE app_id = :app_id
                  AND lower(login) = lower(:login)
                  AND (CAST(:except_id AS integer) IS NULL OR id <> CAST(:except_id AS integer))
                LIMIT 1
                """
            ),
            {"app_id": app_id, "login": login, "except_id": except_id},
        ).first()
        return row is not None

    def insert_account(self, account: Account) -> None:
        self.connection.execute(
            text(
                """
                INSERT INTO rest_accounts (
                    app_id, id, login, employee_ref, status,
                    first_name, last_name, department
                ) VALUES (
                    :app_id, :id, :login, :employee_ref, :status,
                    :first_name, :last_name, :department
                )
                """
            ),
            _account_params(account),
        )

    def update_account(self, account: Account) -> None:
        row = self.connection.execute(
            text(
                """
                UPDATE rest_accounts SET
                    login = :login,
                    employee_ref = :employee_ref,
                    status = :status,
                    first_name = :first_name,
                    last_name = :last_name,
                    department = :department
                WHERE app_id = :app_id AND id = :id
                RETURNING id
                """
            ),
            _account_params(account),
        ).first()
        if row is None:
            raise RestError(404, "account not found")

    def get_account(self, app_id: str, account_id: int) -> Account | None:
        row = self.connection.execute(
            text(
                f"""
                SELECT {_ACCOUNT_COLUMNS}
                FROM rest_accounts
                WHERE app_id = :app_id AND id = :id
                """
            ),
            {"app_id": app_id, "id": account_id},
        ).first()
        if row is None:
            return None
        return self._hydrate(app_id, [_account_from_row(app_id, row)])[0]

    def delete_account(self, app_id: str, account_id: int) -> bool:
        row = self.connection.execute(
            text(
                """
                DELETE FROM rest_accounts
                WHERE app_id = :app_id AND id = :id
                RETURNING id
                """
            ),
            {"app_id": app_id, "id": account_id},
        ).first()
        return row is not None

    def list_accounts_after(self, app_id: str, after_id: int | None, limit: int) -> list[Account]:
        rows = self.connection.execute(
            text(
                f"""
                SELECT {_ACCOUNT_COLUMNS}
                FROM rest_accounts
                WHERE app_id = :app_id
                  AND (CAST(:after_id AS integer) IS NULL OR id > CAST(:after_id AS integer))
                ORDER BY id
                LIMIT :limit
                """
            ),
            {"app_id": app_id, "after_id": after_id, "limit": limit},
        ).all()
        return self._hydrate(app_id, [_account_from_row(app_id, row) for row in rows])

    def count_accounts(self, app_id: str) -> int:
        return int(
            self.connection.execute(
                text("SELECT count(*) FROM rest_accounts WHERE app_id = :app_id"),
                {"app_id": app_id},
            ).scalar_one()
        )

    def list_accounts_page(self, app_id: str, offset: int, limit: int) -> list[Account]:
        rows = self.connection.execute(
            text(
                f"""
                SELECT {_ACCOUNT_COLUMNS}
                FROM rest_accounts
                WHERE app_id = :app_id
                ORDER BY id
                LIMIT :limit OFFSET :offset
                """
            ),
            {"app_id": app_id, "limit": limit, "offset": offset},
        ).all()
        return self._hydrate(app_id, [_account_from_row(app_id, row) for row in rows])

    def list_all_accounts(self, app_id: str) -> list[Account]:
        rows = self.connection.execute(
            text(
                f"""
                SELECT {_ACCOUNT_COLUMNS}
                FROM rest_accounts
                WHERE app_id = :app_id
                ORDER BY id
                """
            ),
            {"app_id": app_id},
        ).all()
        return self._hydrate(app_id, [_account_from_row(app_id, row) for row in rows])

    def role_exists(self, app_id: str, name: str) -> bool:
        row = self.connection.execute(
            text("SELECT 1 FROM rest_roles WHERE app_id = :app_id AND name = :name"),
            {"app_id": app_id, "name": name},
        ).first()
        return row is not None

    def list_roles(self, app_id: str) -> list[str]:
        rows = self.connection.execute(
            text("SELECT name FROM rest_roles WHERE app_id = :app_id ORDER BY name"),
            {"app_id": app_id},
        ).all()
        return [str(row[0]) for row in rows]

    def assignment_exists(self, app_id: str, account_id: int, role: str) -> bool:
        row = self.connection.execute(
            text(
                """
                SELECT 1 FROM rest_account_roles
                WHERE app_id = :app_id AND account_id = :account_id AND role_name = :role
                """
            ),
            {"app_id": app_id, "account_id": account_id, "role": role},
        ).first()
        return row is not None

    def assign_role(self, app_id: str, account_id: int, role: str) -> bool:
        row = self.connection.execute(
            text(
                """
                INSERT INTO rest_account_roles (app_id, account_id, role_name)
                VALUES (:app_id, :account_id, :role)
                ON CONFLICT (app_id, account_id, role_name) DO NOTHING
                RETURNING role_name
                """
            ),
            {"app_id": app_id, "account_id": account_id, "role": role},
        ).first()
        return row is not None

    def unassign_role(self, app_id: str, account_id: int, role: str) -> bool:
        row = self.connection.execute(
            text(
                """
                DELETE FROM rest_account_roles
                WHERE app_id = :app_id AND account_id = :account_id AND role_name = :role
                RETURNING role_name
                """
            ),
            {"app_id": app_id, "account_id": account_id, "role": role},
        ).first()
        return row is not None

    def get_operation(self, app_id: str, operation_id: str) -> Operation | None:
        return self._operation(
            f"""
            SELECT {_OPERATION_COLUMNS}
            FROM rest_operations
            WHERE app_id = :app_id AND id = :id
            """,
            {"app_id": app_id, "id": operation_id},
        )

    def lock_operation(self, app_id: str, operation_id: str) -> Operation | None:
        return self._operation(
            f"""
            SELECT {_OPERATION_COLUMNS}
            FROM rest_operations
            WHERE app_id = :app_id AND id = :id
            FOR UPDATE
            """,
            {"app_id": app_id, "id": operation_id},
        )

    def find_by_idempotency(self, app_id: str, client_id: str, key: str) -> Operation | None:
        return self._operation(
            f"""
            SELECT {_OPERATION_COLUMNS}
            FROM rest_operations
            WHERE app_id = :app_id
              AND client_id = :client_id
              AND idempotency_key = :idempotency_key
            """,
            {"app_id": app_id, "client_id": client_id, "idempotency_key": key},
        )

    def insert_operation(self, op: Operation) -> None:
        self.connection.execute(
            text(
                """
                INSERT INTO rest_operations (
                    id, app_id, client_id, idempotency_key, payload_hash, payload,
                    kind, state, account_id, role_name, applied, error, generation,
                    created_at, updated_at
                ) VALUES (
                    :id, :app_id, :client_id, :idempotency_key, :payload_hash, :payload,
                    :kind, :state, :account_id, :role_name, :applied, :error, :generation,
                    :created_at, :created_at
                )
                """
            ),
            _operation_params(op),
        )

    def update_operation(self, op: Operation) -> None:
        row = self.connection.execute(
            text(
                """
                UPDATE rest_operations SET
                    state = :state,
                    applied = :applied,
                    error = :error,
                    account_id = :account_id,
                    updated_at = now()
                WHERE app_id = :app_id AND id = :id
                RETURNING id
                """
            ),
            _operation_params(op),
        ).first()
        if row is None:
            raise RuntimeError("operation update missed")

    def list_resumable(self, app_id: str) -> list[Operation]:
        rows = self.connection.execute(
            text(
                f"""
                SELECT {_OPERATION_COLUMNS}
                FROM rest_operations
                WHERE app_id = :app_id AND state IN ('accepted', 'running')
                ORDER BY created_at, id
                """
            ),
            {"app_id": app_id},
        ).all()
        return [_operation_from_row(row) for row in rows]

    def _hydrate(self, app_id: str, accounts: list[Account]) -> list[Account]:
        if not accounts:
            return []
        roles = self._role_map(app_id)
        return [account.with_roles(roles.get(account.id, ())) for account in accounts]

    def _role_map(self, app_id: str) -> dict[int, tuple[str, ...]]:
        rows = self.connection.execute(
            text(
                """
                SELECT account_id, role_name
                FROM rest_account_roles
                WHERE app_id = :app_id
                ORDER BY account_id, role_name
                """
            ),
            {"app_id": app_id},
        ).all()
        grouped: dict[int, list[str]] = {}
        for account_id, role_name in rows:
            grouped.setdefault(int(account_id), []).append(str(role_name))
        return {account_id: tuple(names) for account_id, names in grouped.items()}

    def _operation(self, sql: str, params: dict) -> Operation | None:
        row = self.connection.execute(text(sql), params).first()
        if row is None:
            return None
        return _operation_from_row(row)


def _account_params(account: Account) -> dict:
    return {
        "app_id": account.app_id,
        "id": account.id,
        "login": account.login,
        "employee_ref": account.employee_ref,
        "status": account.status,
        "first_name": account.first_name,
        "last_name": account.last_name,
        "department": account.department,
    }


def _account_from_row(app_id: str, row: object) -> Account:
    return Account(
        app_id=app_id,
        id=int(row[0]),
        login=str(row[1]),
        employee_ref=str(row[2]),
        status=str(row[3]),
        first_name=str(row[4]),
        last_name=str(row[5]),
        department=str(row[6]),
    )


def _operation_params(op: Operation) -> dict:
    return {
        "id": op.id,
        "app_id": op.app_id,
        "client_id": op.client_id,
        "idempotency_key": op.idempotency_key,
        "payload_hash": op.payload_hash,
        "payload": op.payload,
        "kind": op.kind,
        "state": op.state,
        "account_id": op.account_id,
        "role_name": op.role_name,
        "applied": op.applied,
        "error": op.error,
        "generation": op.generation,
        "created_at": op.created_at,
    }


def _operation_from_row(row: object) -> Operation:
    account_id = row[8]
    return Operation(
        id=str(row[0]),
        app_id=str(row[1]),
        client_id=str(row[2]),
        idempotency_key=str(row[3]),
        payload_hash=str(row[4]),
        payload=str(row[5]),
        kind=str(row[6]),
        state=str(row[7]),
        account_id=None if account_id is None else int(account_id),
        role_name=None if row[9] is None else str(row[9]),
        applied=bool(row[10]),
        error=None if row[11] is None else str(row[11]),
        generation=int(row[12]),
        created_at=row[13],
    )
