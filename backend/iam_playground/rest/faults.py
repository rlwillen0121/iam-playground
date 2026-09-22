"""In-memory fault rules. Match only after the caller has authenticated.

Counters live in this process. A restart starts them over. Default is no rules.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from iam_playground.rest.constants import (
    APP_LEGACY,
    APPLICATIONS,
    FAULT_429,
    FAULT_503,
    FAULT_ASYNC_FAILURE,
    FAULT_COMMIT_TIMEOUT,
    FAULT_MALFORMED_LIST,
    FAULT_STALE_READ,
    FAULTS,
    KIND_ASSIGN,
    KIND_CREATE,
    KIND_DELETE,
    KIND_DISABLE,
    KIND_ENABLE,
    KIND_PATCH,
    KIND_REMOVE,
    OP_GET_ACCOUNT,
    OP_LIST_ACCOUNTS,
    OPERATIONS,
)

_ACCOUNT_WRITES = frozenset(
    {
        KIND_CREATE,
        KIND_PATCH,
        KIND_DELETE,
        KIND_ENABLE,
        KIND_DISABLE,
        KIND_ASSIGN,
        KIND_REMOVE,
    }
)
_READ_ACCOUNT = frozenset({OP_GET_ACCOUNT, OP_LIST_ACCOUNTS})


@dataclass(frozen=True)
class FaultHit:
    rule_id: int
    revision: int
    name: str
    app_id: str
    operation: str
    remaining_after: int


@dataclass
class _Rule:
    rule_id: int
    name: str
    app_id: str
    operation: str
    remaining: int
    revision: int


class FaultStore:
    """First matching rule with remaining budget wins. Insertion order is priority."""

    def __init__(self) -> None:
        self._rules: list[_Rule] = []
        self._hits: list[FaultHit] = []
        self._next_id = 1
        self._lock = threading.Lock()

    def add(self, name: str, app_id: str, operation: str, times: int, *, revision: int = 1) -> int:
        if name not in FAULTS:
            raise ValueError(f"unknown fault {name}")
        if app_id not in APPLICATIONS and app_id != "*":
            raise ValueError(f"unknown application {app_id}")
        if operation not in OPERATIONS and operation != "*":
            raise ValueError(f"unknown operation {operation}")
        if times < 0:
            raise ValueError("times must be zero or greater")
        if revision < 1:
            raise ValueError("revision must be positive")
        with self._lock:
            rule_id = self._next_id
            self._next_id += 1
            self._rules.append(
                _Rule(
                    rule_id=rule_id,
                    name=name,
                    app_id=app_id,
                    operation=operation,
                    remaining=times,
                    revision=revision,
                )
            )
        return rule_id

    def match(
        self,
        *,
        authenticated: bool,
        app_id: str,
        operation: str,
        only: frozenset[str] | None = None,
    ) -> str | None:
        """Return a fault name and consume one count, or None.

        Unauthenticated calls do not match and do not consume a count.
        A rule whose fault does not apply to this request is left unchanged.
        """
        if not authenticated:
            return None
        with self._lock:
            for rule in self._rules:
                if rule.remaining <= 0:
                    continue
                if only is not None and rule.name not in only:
                    continue
                if rule.app_id not in {app_id, "*"}:
                    continue
                if rule.operation not in {operation, "*"}:
                    continue
                if not _applies(rule.name, app_id, operation):
                    continue
                rule.remaining -= 1
                self._hits.append(
                    FaultHit(
                        rule_id=rule.rule_id,
                        revision=rule.revision,
                        name=rule.name,
                        app_id=app_id,
                        operation=operation,
                        remaining_after=rule.remaining,
                    )
                )
                return rule.name
        return None

    def remaining(self, rule_id: int) -> int | None:
        with self._lock:
            for rule in self._rules:
                if rule.rule_id == rule_id:
                    return rule.remaining
        return None

    def hits(self) -> tuple[FaultHit, ...]:
        with self._lock:
            return tuple(self._hits)


def _applies(name: str, app_id: str, operation: str) -> bool:
    if name in {FAULT_429, FAULT_503}:
        return True
    if name == FAULT_STALE_READ:
        return operation in _READ_ACCOUNT
    if name == FAULT_MALFORMED_LIST:
        return operation == OP_LIST_ACCOUNTS
    if name == FAULT_ASYNC_FAILURE:
        return app_id == APP_LEGACY and operation in _ACCOUNT_WRITES
    if name == FAULT_COMMIT_TIMEOUT:
        return operation in _ACCOUNT_WRITES
    return False
