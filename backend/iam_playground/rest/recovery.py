"""Crash windows for one in-flight legacy operation.

These functions are pure. They do not read the database. Each one reports the
operation row and target mutation a restart would see if the process died in
that window. None of the windows is exactly-once by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from iam_playground.rest.constants import STATE_ACCEPTED, STATE_CANCELLED, STATE_FAILED, STATE_RUNNING, STATE_SUCCEEDED


@dataclass(frozen=True)
class Operation:
    """Durable operation. Crash-window callers only need id, state, and applied."""

    id: str
    state: str
    applied: bool = False
    app_id: str = "rest-legacy"
    client_id: str = "rest-legacy"
    idempotency_key: str = ""
    payload_hash: str = ""
    kind: str = ""
    account_id: int | None = None
    role_name: str | None = None
    error: str | None = None
    generation: int = 0
    payload: str = ""
    created_at: datetime | None = None


@dataclass(frozen=True)
class RestartRows:
    """Row image after a crash. operation_state None means the operation row is absent."""

    in_flight_id: str
    operation_state: str | None
    mutation_visible: bool


def before_commit(op: Operation) -> RestartRows:
    """The acceptance insert has not committed. Restart does not see this attempt."""
    return RestartRows(op.id, None, False)


def after_acceptance(op: Operation) -> RestartRows:
    """The operation row is committed as accepted. The account change is not."""
    return RestartRows(op.id, STATE_ACCEPTED, False)


def after_mutation(op: Operation) -> RestartRows:
    """The account change is durable and the operation row is still running.

    Resume must not apply that change a second time. A later terminal update
    may still be missing.
    """
    return RestartRows(op.id, STATE_RUNNING, True)


def before_response(op: Operation) -> RestartRows:
    """The handler committed, then died before the client received the response.

    Restart sees that committed image. A succeeded row keeps its mutation.
    Cancellation does not remove a mutation that already committed.
    """
    return RestartRows(op.id, op.state, _mutation_visible(op.state, op.applied))


def _mutation_visible(state: str, applied: bool) -> bool:
    if state == STATE_SUCCEEDED:
        return True
    if state == STATE_FAILED or state == STATE_ACCEPTED:
        return False
    if state in {STATE_RUNNING, STATE_CANCELLED}:
        return applied
    return applied
