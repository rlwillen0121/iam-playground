"""Finite fault counters. Names and rules match infra/postgres/packs/mcp.sql."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Protocol

from iam_playground.mcp_pack.errors import FaultStoreError, PackError

MAX_REMAINING = 1000

# Match order is the tuple order. commit-before-response applies to writes only.
FAULT_RULES = (
    ("429", "finite-429", False, 429),
    ("503", "finite-503", False, 503),
    ("commit_before_response", "commit-before-response", True, 504),
)
_RULE_BY_NAME = {
    name: (rule, mutation_only, status)
    for name, rule, mutation_only, status in FAULT_RULES
}


@dataclass(frozen=True)
class FaultCounter:
    name: str
    remaining: int
    rule: str


class FaultStore(Protocol):
    def list_counters(self) -> list[FaultCounter]:
        """Return stored counters. Does not insert defaults."""

    def put_counter(self, name: str, remaining: int, rule: str) -> None:
        """Replace one counter."""

    def consume(self, name: str) -> FaultCounter | None:
        """Decrement when remaining > 0. Return the row after decrement."""


class MemoryFaultStore:
    """Same methods as the Postgres store. Counters die with the process."""

    def __init__(self) -> None:
        self._rows: dict[str, FaultCounter] = {}
        self._lock = threading.Lock()

    def list_counters(self) -> list[FaultCounter]:
        with self._lock:
            return [self._rows[name] for name in sorted(self._rows)]

    def put_counter(self, name: str, remaining: int, rule: str) -> None:
        _validate_counter(name, remaining, rule)
        with self._lock:
            self._rows[name] = FaultCounter(name, remaining, rule)

    def consume(self, name: str) -> FaultCounter | None:
        with self._lock:
            row = self._rows.get(name)
            if row is None or row.remaining <= 0:
                return None
            updated = FaultCounter(row.name, row.remaining - 1, row.rule)
            self._rows[name] = updated
            return updated


class PostgresFaultStore:
    """Uses fault_counters. The DSN is never returned or logged."""

    def __init__(self, dsn: str) -> None:
        self._dsn = _libpq_dsn(dsn)

    def __repr__(self) -> str:
        return "PostgresFaultStore(dsn='[redacted]')"

    def list_counters(self) -> list[FaultCounter]:
        def work(cursor: object) -> list[FaultCounter]:
            cursor.execute(
                "SELECT name, remaining, rule FROM fault_counters ORDER BY name"
            )
            return [_counter_row(row) for row in cursor.fetchall()]

        return self._run(work)

    def put_counter(self, name: str, remaining: int, rule: str) -> None:
        _validate_counter(name, remaining, rule)

        def work(cursor: object) -> None:
            cursor.execute(
                """
                INSERT INTO fault_counters (name, remaining, rule)
                VALUES (%s, %s, %s)
                ON CONFLICT (name) DO UPDATE
                SET remaining = EXCLUDED.remaining, rule = EXCLUDED.rule
                """,
                (name, remaining, rule),
            )

        self._run(work)

    def consume(self, name: str) -> FaultCounter | None:
        def work(cursor: object) -> FaultCounter | None:
            cursor.execute(
                """
                UPDATE fault_counters
                SET remaining = remaining - 1
                WHERE name = %s AND remaining > 0
                RETURNING name, remaining, rule
                """,
                (name,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return _counter_row(row)

        return self._run(work)

    def _run(self, work):
        try:
            import psycopg
        except ImportError:
            raise FaultStoreError("fault store unavailable") from None
        try:
            with psycopg.connect(
                self._dsn,
                connect_timeout=3,
                application_name="iam_playground_mcp",
            ) as connection:
                with connection.cursor() as cursor:
                    return work(cursor)
        except FaultStoreError:
            raise
        except Exception:
            raise FaultStoreError("fault store unavailable") from None


def fault_store_from_env() -> FaultStore:
    dsn = os.environ.get("MCP_FAULT_DSN", "").strip()
    if dsn == "":
        return MemoryFaultStore()
    return PostgresFaultStore(dsn)


def snapshot(store: FaultStore) -> list[dict[str, object]]:
    """Show the three known faults. Missing rows stay at remaining 0 and are not written."""
    stored = {row.name: row for row in store.list_counters()}
    visible: list[dict[str, object]] = []
    for name, rule, _mutation_only, _status in FAULT_RULES:
        row = stored.get(name)
        visible.append(
            {
                "name": name,
                "remaining": row.remaining if row is not None else 0,
                "rule": row.rule if row is not None else rule,
            }
        )
    return visible


def apply_matched_fault(store: FaultStore, *, mutation: bool) -> FaultCounter | None:
    """Consume the first matching counter. Caller must already have authorized the tool."""
    for name, _rule, mutation_only, _status in FAULT_RULES:
        if mutation_only and not mutation:
            continue
        taken = store.consume(name)
        if taken is not None:
            return taken
    return None


def fault_status(name: str) -> int:
    found = _RULE_BY_NAME.get(name)
    if found is None:
        raise FaultStoreError("fault store unavailable")
    return found[2]


def parse_fault_body(body: dict[str, object]) -> tuple[str, int, str]:
    unknown = [key for key in body if key not in {"name", "remaining", "rule"}]
    if unknown:
        raise PackError(400, "unsupported field")
    for key in ("name", "remaining", "rule"):
        if key not in body:
            raise PackError(400, f"{key} is required")
    name = body["name"]
    rule = body["rule"]
    remaining = body["remaining"]
    if not isinstance(name, str) or not isinstance(rule, str):
        raise PackError(400, "fault is not allowed")
    if type(remaining) is not int:
        raise PackError(400, "remaining must be an integer")
    try:
        _validate_counter(name, remaining, rule)
    except ValueError:
        raise PackError(400, "fault is not allowed") from None
    return name, remaining, rule


def _validate_counter(name: str, remaining: int, rule: str) -> None:
    if type(remaining) is not int or remaining < 0 or remaining > MAX_REMAINING:
        raise ValueError("remaining is invalid")
    expected = _RULE_BY_NAME.get(name)
    if expected is None or expected[0] != rule:
        raise ValueError("fault is not allowed")


def _counter_row(row: object) -> FaultCounter:
    if not isinstance(row, tuple) or len(row) != 3:
        raise FaultStoreError("fault store unavailable")
    name, remaining, rule = row
    if not isinstance(name, str) or not isinstance(rule, str) or type(remaining) is not int:
        raise FaultStoreError("fault store unavailable")
    return FaultCounter(name, remaining, rule)


def _libpq_dsn(dsn: str) -> str:
    for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://"):
        if dsn.startswith(prefix):
            return "postgresql://" + dsn[len(prefix) :]
    return dsn
