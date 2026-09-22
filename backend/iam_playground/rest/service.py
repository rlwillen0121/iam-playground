"""Account writes and legacy operations. Acceptance commits before a 202 is built.

A read credential must not call resume or execute. Those apply account changes.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from iam_playground.errors import DependencyFailure
from iam_playground.rest.codec import (
    account_json,
    apply_patch,
    canonical_payload,
    encode_cursor,
    parse_create,
    parse_patch,
    payload_hash,
)
from iam_playground.rest.constants import (
    APPLICATIONS,
    APP_LEGACY,
    ASYNC_FAILURE_ERROR,
    IDEMPOTENCY_CONFLICT,
    KIND_ASSIGN,
    KIND_CREATE,
    KIND_DELETE,
    KIND_DISABLE,
    KIND_ENABLE,
    KIND_PATCH,
    KIND_REMOVE,
    LOGIN_CONFLICT,
    STALE_GENERATION,
    STATE_ACCEPTED,
    STATE_CANCELLED,
    STATE_FAILED,
    STATE_RUNNING,
    STATE_SUCCEEDED,
    STATUS_DISABLED,
    STATUS_ENABLED,
    TERMINAL_STATES,
)
from iam_playground.rest.errors import RestError
from iam_playground.rest.models import Account
from iam_playground.rest.recovery import Operation
from iam_playground.rest.snapshots import AccountSnapshots

ACCOUNT_MISSING = "account not found"
ROLE_MISSING = "role not found"
ROLE_UNASSIGNED = "role is not assigned"
PAYLOAD_INVALID = "operation payload is invalid"


def rest_tx(store: object, work):
    try:
        with store.transaction() as unit:
            return work(unit)
    except RestError:
        raise
    except Exception as exc:
        raise DependencyFailure("database") from exc


def list_accounts_cursor(store: object, app_id: str, after_id: int | None, limit: int) -> dict:
    _known(app_id)

    def work(unit: object) -> dict:
        unit.require_generation()
        rows = unit.list_accounts_after(app_id, after_id, limit + 1)
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = encode_cursor(page[-1].id) if has_more else None
        return {"accounts": [account_json(row) for row in page], "nextCursor": next_cursor}

    return rest_tx(store, work)


def list_accounts_page(store: object, app_id: str, page: int, page_size: int) -> dict:
    _known(app_id)

    def work(unit: object) -> dict:
        unit.require_generation()
        total = unit.count_accounts(app_id)
        offset = (page - 1) * page_size
        rows = unit.list_accounts_page(app_id, offset, page_size)
        return {
            "accounts": [account_json(row) for row in rows],
            "page": page,
            "pageSize": page_size,
            "total": total,
        }

    return rest_tx(store, work)


def get_account(store: object, app_id: str, account_id: int) -> dict:
    _known(app_id)

    def work(unit: object) -> dict:
        unit.require_generation()
        account = unit.get_account(app_id, account_id)
        if account is None:
            raise RestError(404, ACCOUNT_MISSING)
        return account_json(account)

    return rest_tx(store, work)


def list_roles(store: object, app_id: str) -> dict:
    _known(app_id)

    def work(unit: object) -> dict:
        unit.require_generation()
        return {"roles": unit.list_roles(app_id)}

    return rest_tx(store, work)


def create_account(
    store: object,
    snapshots: AccountSnapshots | None,
    app_id: str,
    body: dict,
) -> dict:
    _known(app_id)

    def work(unit: object) -> tuple[dict, list[Account]]:
        unit.require_generation()
        if unit.login_taken(app_id, body["login"]):
            raise RestError(409, LOGIN_CONFLICT)
        before = unit.list_all_accounts(app_id)
        account_id = unit.allocate_id(app_id)
        account = _account_from_body(app_id, account_id, body)
        _insert_account(unit, account)
        stored = unit.get_account(app_id, account_id)
        if stored is None:
            raise RuntimeError("account insert missed")
        return account_json(stored), before

    payload, before = rest_tx(store, work)
    _remember(snapshots, app_id, before)
    return payload


def patch_account(
    store: object,
    snapshots: AccountSnapshots | None,
    app_id: str,
    account_id: int,
    patch: dict,
) -> dict:
    _known(app_id)

    def work(unit: object) -> tuple[dict, list[Account]]:
        unit.require_generation()
        account = _require_account(unit, app_id, account_id)
        updated = apply_patch(account, patch)
        if unit.login_taken(app_id, updated.login, except_id=account.id):
            raise RestError(409, LOGIN_CONFLICT)
        before = unit.list_all_accounts(app_id)
        _save_account(unit, updated)
        stored = unit.get_account(app_id, account_id)
        if stored is None:
            raise RuntimeError("account update missed")
        return account_json(stored), before

    payload, before = rest_tx(store, work)
    _remember(snapshots, app_id, before)
    return payload


def set_status(
    store: object,
    snapshots: AccountSnapshots | None,
    app_id: str,
    account_id: int,
    status: str,
) -> dict:
    return patch_account(
        store,
        snapshots,
        app_id,
        account_id,
        {"status": status},
    )


def delete_account(
    store: object,
    snapshots: AccountSnapshots | None,
    app_id: str,
    account_id: int,
) -> None:
    _known(app_id)

    def work(unit: object) -> list[Account]:
        unit.require_generation()
        _require_account(unit, app_id, account_id)
        before = unit.list_all_accounts(app_id)
        if not unit.delete_account(app_id, account_id):
            raise RestError(404, ACCOUNT_MISSING)
        return before

    before = rest_tx(store, work)
    _remember(snapshots, app_id, before)


def assign_role(
    store: object,
    snapshots: AccountSnapshots | None,
    app_id: str,
    account_id: int,
    role: str,
) -> dict:
    _known(app_id)

    def work(unit: object) -> tuple[dict, list[Account]]:
        unit.require_generation()
        _require_account(unit, app_id, account_id)
        _require_role(unit, app_id, role)
        before = unit.list_all_accounts(app_id)
        unit.assign_role(app_id, account_id, role)
        stored = unit.get_account(app_id, account_id)
        if stored is None:
            raise RestError(404, ACCOUNT_MISSING)
        return account_json(stored), before

    payload, before = rest_tx(store, work)
    _remember(snapshots, app_id, before)
    return payload


def remove_role(
    store: object,
    snapshots: AccountSnapshots | None,
    app_id: str,
    account_id: int,
    role: str,
) -> None:
    _known(app_id)

    def work(unit: object) -> list[Account]:
        unit.require_generation()
        _require_account(unit, app_id, account_id)
        _require_role(unit, app_id, role)
        if not unit.assignment_exists(app_id, account_id, role):
            raise RestError(404, ROLE_UNASSIGNED)
        before = unit.list_all_accounts(app_id)
        unit.unassign_role(app_id, account_id, role)
        return before

    before = rest_tx(store, work)
    _remember(snapshots, app_id, before)


def accept_operation(
    store: object,
    *,
    app_id: str,
    client_id: str,
    kind: str,
    idempotency_key: str,
    account_id: int | None,
    role_name: str | None,
    body: dict | None,
) -> tuple[Operation, bool]:
    """Insert the operation row and commit before the caller builds a response."""
    if app_id != APP_LEGACY:
        raise RestError(404, "application not found")
    if kind == KIND_CREATE:
        body = parse_create(body)
    elif kind == KIND_PATCH:
        body = parse_patch(body)
    canonical = canonical_payload(kind, account_id, role_name, body)
    digest = payload_hash(canonical)

    def work(unit: object) -> tuple[Operation, bool]:
        generation = unit.require_generation()
        existing = unit.find_by_idempotency(app_id, client_id, idempotency_key)
        if existing is not None:
            _same_payload(existing, digest)
            return existing, False
        _reject_unworkable(unit, app_id, kind, account_id, role_name, body)
        op = Operation(
            id=str(uuid.uuid4()),
            state=STATE_ACCEPTED,
            applied=False,
            app_id=app_id,
            client_id=client_id,
            idempotency_key=idempotency_key,
            payload_hash=digest,
            kind=kind,
            account_id=account_id,
            role_name=role_name,
            error=None,
            generation=generation,
            payload=canonical,
            created_at=datetime.now(timezone.utc),
        )
        try:
            with unit.savepoint():
                unit.insert_operation(op)
        except IntegrityError:
            raced = unit.find_by_idempotency(app_id, client_id, idempotency_key)
            if raced is None:
                raise
            _same_payload(raced, digest)
            return raced, False
        return op, True

    return rest_tx(store, work)


def get_operation(store: object, app_id: str, operation_id: str) -> Operation:
    if app_id != APP_LEGACY:
        raise RestError(404, "application not found")

    def work(unit: object) -> Operation:
        unit.require_generation()
        op = unit.get_operation(app_id, operation_id)
        if op is None:
            raise RestError(404, "operation not found")
        return op

    return rest_tx(store, work)


def execute_operation(
    store: object,
    snapshots: AccountSnapshots | None,
    app_id: str,
    operation_id: str,
) -> Operation:
    """Move accepted work to a terminal state without applying a mutation twice."""
    current = _claim(store, app_id, operation_id)
    if current.state != STATE_RUNNING:
        return current
    if current.kind == KIND_CREATE and current.account_id is None:
        current = _reserve_create_id(store, app_id, operation_id)
        if current.state != STATE_RUNNING:
            return current
    return _finish(store, snapshots, app_id, operation_id)


def fail_unapplied(store: object, app_id: str, operation_id: str, error: str) -> Operation:
    """Record failure without inserting or changing an account."""

    def work(unit: object) -> Operation:
        op = unit.lock_operation(app_id, operation_id)
        if op is None:
            raise RestError(404, "operation not found")
        if op.state in TERMINAL_STATES or op.applied:
            return op
        failed = _replace(op, state=STATE_FAILED, error=error, applied=False)
        unit.update_operation(failed)
        return failed

    return rest_tx(store, work)


def cancel_operation(store: object, app_id: str, operation_id: str) -> tuple[Operation, str]:
    """Cancel only accepted or running work. A succeeded mutation stays in place."""

    def work(unit: object) -> tuple[Operation, str]:
        unit.require_generation()
        op = unit.lock_operation(app_id, operation_id)
        if op is None:
            raise RestError(404, "operation not found")
        if op.state in {STATE_ACCEPTED, STATE_RUNNING}:
            cancelled = _replace(op, state=STATE_CANCELLED, error=None)
            unit.update_operation(cancelled)
            return cancelled, "cancelled"
        if op.state == STATE_CANCELLED:
            return op, "cancelled"
        if op.state == STATE_SUCCEEDED:
            return op, "succeeded"
        return op, "finished"

    return rest_tx(store, work)


def resume(store: object, snapshots: AccountSnapshots | None, app_id: str) -> list[Operation]:
    """Finish accepted and running operations. Do not call this from a read."""
    if app_id != APP_LEGACY:
        raise RestError(404, "application not found")

    def work(unit: object) -> list[str]:
        _generation, accepting = unit.lab_state()
        if not accepting:
            return []
        return [op.id for op in unit.list_resumable(app_id)]

    identifiers = rest_tx(store, work)
    return [execute_operation(store, snapshots, app_id, operation_id) for operation_id in identifiers]


def _claim(store: object, app_id: str, operation_id: str) -> Operation:
    def work(unit: object) -> Operation:
        op = _locked(unit, app_id, operation_id)
        stopped = _stop(unit, op)
        if stopped is not None:
            return stopped
        if op.state == STATE_ACCEPTED:
            running = _replace(op, state=STATE_RUNNING)
            unit.update_operation(running)
            return running
        return op

    return rest_tx(store, work)


def _reserve_create_id(store: object, app_id: str, operation_id: str) -> Operation:
    def work(unit: object) -> Operation:
        op = _locked(unit, app_id, operation_id)
        stopped = _stop(unit, op)
        if stopped is not None:
            return stopped
        if op.account_id is not None:
            return op
        reserved = _replace(op, account_id=unit.allocate_id(app_id))
        unit.update_operation(reserved)
        return reserved

    return rest_tx(store, work)


def _finish(
    store: object,
    snapshots: AccountSnapshots | None,
    app_id: str,
    operation_id: str,
) -> Operation:
    def work(unit: object) -> tuple[Operation, list[Account] | None]:
        op = _locked(unit, app_id, operation_id)
        stopped = _stop(unit, op)
        if stopped is not None:
            return stopped, None
        if op.state != STATE_RUNNING:
            return op, None
        before = unit.list_all_accounts(app_id)
        try:
            with unit.savepoint():
                _apply(unit, op)
        except RestError as exc:
            failed = _replace(op, state=STATE_FAILED, error=exc.detail, applied=False)
            unit.update_operation(failed)
            return failed, None
        done = _replace(op, state=STATE_SUCCEEDED, error=None, applied=True)
        unit.update_operation(done)
        return done, before

    result, before = rest_tx(store, work)
    if result.applied:
        _remember(snapshots, app_id, before)
    return result


def _apply(unit: object, op: Operation) -> None:
    material = _material(op)
    body = material.get("body")
    if op.kind == KIND_CREATE:
        _apply_create(unit, op, body)
        return
    if op.account_id is None:
        raise RestError(409, PAYLOAD_INVALID)
    if op.kind == KIND_DELETE:
        if unit.get_account(op.app_id, op.account_id) is not None:
            unit.delete_account(op.app_id, op.account_id)
        return
    account = unit.get_account(op.app_id, op.account_id)
    if account is None:
        raise RestError(404, ACCOUNT_MISSING)
    if op.kind == KIND_PATCH:
        if not isinstance(body, dict):
            raise RestError(409, PAYLOAD_INVALID)
        updated = apply_patch(account, body)
        if unit.login_taken(op.app_id, updated.login, except_id=account.id):
            raise RestError(409, LOGIN_CONFLICT)
        _save_account(unit, updated)
        return
    if op.kind == KIND_ENABLE:
        _save_account(unit, _account_status(account, STATUS_ENABLED))
        return
    if op.kind == KIND_DISABLE:
        _save_account(unit, _account_status(account, STATUS_DISABLED))
        return
    if op.kind == KIND_ASSIGN:
        _require_role(unit, op.app_id, op.role_name)
        unit.assign_role(op.app_id, op.account_id, op.role_name)
        return
    if op.kind == KIND_REMOVE:
        _require_role(unit, op.app_id, op.role_name)
        unit.unassign_role(op.app_id, op.account_id, op.role_name)
        return
    raise RestError(409, PAYLOAD_INVALID)


def _apply_create(unit: object, op: Operation, body: object) -> None:
    if op.account_id is None or not isinstance(body, dict):
        raise RestError(409, PAYLOAD_INVALID)
    if unit.get_account(op.app_id, op.account_id) is not None:
        return
    if unit.login_taken(op.app_id, str(body.get("login", ""))):
        raise RestError(409, LOGIN_CONFLICT)
    _insert_account(unit, _account_from_body(op.app_id, op.account_id, body))


def _stop(unit: object, op: Operation) -> Operation | None:
    if op.state in TERMINAL_STATES:
        return op
    generation, accepting = unit.lab_state()
    if not accepting:
        return op
    if generation != op.generation:
        if op.applied:
            done = _replace(op, state=STATE_SUCCEEDED, error=None)
            unit.update_operation(done)
            return done
        failed = _replace(op, state=STATE_FAILED, error=STALE_GENERATION, applied=False)
        unit.update_operation(failed)
        return failed
    return None


def _reject_unworkable(
    unit: object,
    app_id: str,
    kind: str,
    account_id: int | None,
    role_name: str | None,
    body: dict | None,
) -> None:
    if kind == KIND_CREATE:
        if not isinstance(body, dict) or "login" not in body:
            raise RestError(400, "request body must be an object")
        if unit.login_taken(app_id, body["login"]):
            raise RestError(409, LOGIN_CONFLICT)
        return
    account = _require_account(unit, app_id, account_id)
    if kind == KIND_PATCH and isinstance(body, dict) and "login" in body:
        if unit.login_taken(app_id, body["login"], except_id=account.id):
            raise RestError(409, LOGIN_CONFLICT)
    if kind in {KIND_ASSIGN, KIND_REMOVE}:
        _require_role(unit, app_id, role_name)
    if kind == KIND_REMOVE and not unit.assignment_exists(app_id, account.id, role_name or ""):
        raise RestError(404, ROLE_UNASSIGNED)


def _require_account(unit: object, app_id: str, account_id: int | None) -> Account:
    if account_id is None:
        raise RestError(400, "account id is invalid")
    account = unit.get_account(app_id, account_id)
    if account is None:
        raise RestError(404, ACCOUNT_MISSING)
    return account


def _require_role(unit: object, app_id: str, role: str | None) -> None:
    if role is None or not unit.role_exists(app_id, role):
        raise RestError(404, ROLE_MISSING)


def _insert_account(unit: object, account: Account) -> None:
    try:
        with unit.savepoint():
            unit.insert_account(account)
    except IntegrityError as exc:
        raise RestError(409, LOGIN_CONFLICT) from exc


def _save_account(unit: object, account: Account) -> None:
    try:
        with unit.savepoint():
            unit.update_account(account)
    except IntegrityError as exc:
        raise RestError(409, LOGIN_CONFLICT) from exc


def _account_from_body(app_id: str, account_id: int, body: dict) -> Account:
    try:
        profile = body["profile"]
        return Account(
            app_id=app_id,
            id=account_id,
            login=body["login"],
            employee_ref=body["employeeRef"],
            status=body["status"],
            first_name=profile["firstName"],
            last_name=profile["lastName"],
            department=profile["department"],
        )
    except (KeyError, TypeError) as exc:
        raise RestError(409, PAYLOAD_INVALID) from exc


def _account_status(account: Account, status: str) -> Account:
    return Account(
        app_id=account.app_id,
        id=account.id,
        login=account.login,
        employee_ref=account.employee_ref,
        status=status,
        first_name=account.first_name,
        last_name=account.last_name,
        department=account.department,
        roles=account.roles,
    )


def _material(op: Operation) -> dict:
    try:
        material = json.loads(op.payload)
    except json.JSONDecodeError as exc:
        raise RestError(409, PAYLOAD_INVALID) from exc
    if not isinstance(material, dict) or material.get("kind") != op.kind:
        raise RestError(409, PAYLOAD_INVALID)
    return material


def _same_payload(existing: Operation, digest: str) -> None:
    if existing.payload_hash != digest:
        raise RestError(409, IDEMPOTENCY_CONFLICT)


def _locked(unit: object, app_id: str, operation_id: str) -> Operation:
    op = unit.lock_operation(app_id, operation_id)
    if op is None:
        raise RestError(404, "operation not found")
    return op


def _replace(op: Operation, **changes: object) -> Operation:
    data = {
        "id": op.id,
        "state": op.state,
        "applied": op.applied,
        "app_id": op.app_id,
        "client_id": op.client_id,
        "idempotency_key": op.idempotency_key,
        "payload_hash": op.payload_hash,
        "kind": op.kind,
        "account_id": op.account_id,
        "role_name": op.role_name,
        "error": op.error,
        "generation": op.generation,
        "payload": op.payload,
        "created_at": op.created_at,
    }
    data.update(changes)
    return Operation(**data)


def _remember(snapshots: AccountSnapshots | None, app_id: str, before: list[Account] | None) -> None:
    if snapshots is None or before is None:
        return
    snapshots.rotate(app_id, [account_json(row) for row in before])


def _known(app_id: str) -> None:
    if app_id not in APPLICATIONS:
        raise RestError(404, "application not found")
