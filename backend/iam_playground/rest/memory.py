"""Process-local REST store. A failed transaction restores the snapshot."""

from __future__ import annotations

import copy
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from iam_playground.rest.constants import APPLICATIONS, NOT_ACCEPTING, ROLES
from iam_playground.rest.errors import RestError
from iam_playground.rest.models import Account
from iam_playground.rest.recovery import Operation


class MemoryRestStore:
    def __init__(self) -> None:
        self.accounts: dict[tuple[str, int], Account] = {}
        self.assignments: set[tuple[str, int, str]] = set()
        self.roles: set[tuple[str, str]] = set()
        self.operations: dict[str, Operation] = {}
        self.idempotency: dict[tuple[str, str, str], str] = {}
        self.alloc: dict[str, int] = {}
        self.generation = 1
        self.accepting = True
        self._lock = threading.RLock()
        for app_id in APPLICATIONS:
            self.alloc[app_id] = 1
            for role in ROLES:
                self.roles.add((app_id, role))

    def _snapshot(self) -> tuple:
        return (
            copy.deepcopy(self.accounts),
            copy.deepcopy(self.assignments),
            copy.deepcopy(self.operations),
            copy.deepcopy(self.idempotency),
            dict(self.alloc),
            self.generation,
            self.accepting,
        )

    def _restore(self, snapshot: tuple) -> None:
        (
            self.accounts,
            self.assignments,
            self.operations,
            self.idempotency,
            self.alloc,
            self.generation,
            self.accepting,
        ) = snapshot

    @contextmanager
    def transaction(self) -> Iterator[MemoryRestUnit]:
        with self._lock:
            snapshot = self._snapshot()
            try:
                yield MemoryRestUnit(self)
            except Exception:
                self._restore(snapshot)
                raise


class MemoryRestUnit:
    def __init__(self, store: MemoryRestStore) -> None:
        self.store = store

    def lab_state(self) -> tuple[int, bool]:
        return self.store.generation, self.store.accepting

    def require_generation(self) -> int:
        generation, accepting = self.lab_state()
        if not accepting:
            raise RestError(409, NOT_ACCEPTING)
        return generation

    @contextmanager
    def savepoint(self) -> Iterator[None]:
        accounts = copy.deepcopy(self.store.accounts)
        assignments = copy.deepcopy(self.store.assignments)
        try:
            yield
        except Exception:
            self.store.accounts = accounts
            self.store.assignments = assignments
            raise

    def allocate_id(self, app_id: str) -> int:
        current = self.store.alloc[app_id]
        self.store.alloc[app_id] = current + 1
        return current

    def login_taken(self, app_id: str, login: str, except_id: int | None = None) -> bool:
        needle = login.lower()
        for account in self.store.accounts.values():
            if account.app_id != app_id or account.login.lower() != needle:
                continue
            if except_id is not None and account.id == except_id:
                continue
            return True
        return False

    def insert_account(self, account: Account) -> None:
        key = (account.app_id, account.id)
        if key in self.store.accounts or self.login_taken(account.app_id, account.login):
            raise RestError(409, "login is already in use")
        self.store.accounts[key] = account.with_roles(())

    def update_account(self, account: Account) -> None:
        key = (account.app_id, account.id)
        if key not in self.store.accounts:
            raise RestError(404, "account not found")
        self.store.accounts[key] = account.with_roles(())

    def get_account(self, app_id: str, account_id: int) -> Account | None:
        account = self.store.accounts.get((app_id, account_id))
        if account is None:
            return None
        return account.with_roles(self._roles(app_id, account_id))

    def delete_account(self, app_id: str, account_id: int) -> bool:
        if (app_id, account_id) not in self.store.accounts:
            return False
        del self.store.accounts[(app_id, account_id)]
        self.store.assignments = {
            item
            for item in self.store.assignments
            if not (item[0] == app_id and item[1] == account_id)
        }
        return True

    def list_accounts_after(self, app_id: str, after_id: int | None, limit: int) -> list[Account]:
        rows = [
            account
            for account in self._ordered(app_id)
            if after_id is None or account.id > after_id
        ]
        return rows[:limit]

    def count_accounts(self, app_id: str) -> int:
        return sum(1 for account in self.store.accounts.values() if account.app_id == app_id)

    def list_accounts_page(self, app_id: str, offset: int, limit: int) -> list[Account]:
        return self._ordered(app_id)[offset : offset + limit]

    def list_all_accounts(self, app_id: str) -> list[Account]:
        return self._ordered(app_id)

    def role_exists(self, app_id: str, name: str) -> bool:
        return (app_id, name) in self.store.roles

    def list_roles(self, app_id: str) -> list[str]:
        names = [name for (role_app, name) in self.store.roles if role_app == app_id]
        names.sort()
        return names

    def assignment_exists(self, app_id: str, account_id: int, role: str) -> bool:
        return (app_id, account_id, role) in self.store.assignments

    def assign_role(self, app_id: str, account_id: int, role: str) -> bool:
        item = (app_id, account_id, role)
        if item in self.store.assignments:
            return False
        self.store.assignments.add(item)
        return True

    def unassign_role(self, app_id: str, account_id: int, role: str) -> bool:
        item = (app_id, account_id, role)
        if item not in self.store.assignments:
            return False
        self.store.assignments.remove(item)
        return True

    def get_operation(self, app_id: str, operation_id: str) -> Operation | None:
        op = self.store.operations.get(operation_id)
        if op is None or op.app_id != app_id:
            return None
        return op

    def lock_operation(self, app_id: str, operation_id: str) -> Operation | None:
        return self.get_operation(app_id, operation_id)

    def find_by_idempotency(self, app_id: str, client_id: str, key: str) -> Operation | None:
        operation_id = self.store.idempotency.get((app_id, client_id, key))
        if operation_id is None:
            return None
        return self.get_operation(app_id, operation_id)

    def insert_operation(self, op: Operation) -> None:
        if op.id in self.store.operations:
            raise RestError(409, "operation already exists")
        key = (op.app_id, op.client_id, op.idempotency_key)
        if key in self.store.idempotency:
            raise RestError(409, "idempotency key was reused with a different payload")
        self.store.operations[op.id] = op
        self.store.idempotency[key] = op.id

    def update_operation(self, op: Operation) -> None:
        current = self.store.operations.get(op.id)
        if current is None or current.app_id != op.app_id:
            raise RuntimeError("operation update missed")
        self.store.operations[op.id] = op

    def list_resumable(self, app_id: str) -> list[Operation]:
        rows = [
            op
            for op in self.store.operations.values()
            if op.app_id == app_id and op.state in {"accepted", "running"}
        ]
        rows.sort(key=lambda op: (_stamp(op.created_at), op.id))
        return rows

    def _ordered(self, app_id: str) -> list[Account]:
        rows = [account for account in self.store.accounts.values() if account.app_id == app_id]
        rows.sort(key=lambda account: account.id)
        return [account.with_roles(self._roles(app_id, account.id)) for account in rows]

    def _roles(self, app_id: str, account_id: int) -> tuple[str, ...]:
        names = [
            role
            for (role_app, ident, role) in self.store.assignments
            if role_app == app_id and ident == account_id
        ]
        names.sort()
        return tuple(names)


def _stamp(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return value
