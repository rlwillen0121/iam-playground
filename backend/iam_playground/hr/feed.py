"""In-memory HR feed.

Reads fixtures/enterprise-small-v1.json when that file is present.
Each change gets the next sequence number. occurredAt is not unique and
is not an order key: two changes with the same timestamp both stay.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

from iam_playground.constants import FIXTURE_ID

FEED_COLUMNS = (
    "employeeNumber",
    "userName",
    "email",
    "department",
    "managerEmployeeNumber",
)

# One timestamp for the whole fixture load, so equal timestamps are the normal case.
FIXTURE_SNAPSHOT_AT = "2020-01-01T00:00:00Z"

_EMPLOYEE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class FeedError(ValueError):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class Person(TypedDict):
    employeeNumber: str
    userName: str
    email: str
    department: str
    managerEmployeeNumber: str | None
    sequence: int


class Change(TypedDict):
    sequence: int
    occurredAt: str
    employeeNumber: str
    operation: str
    person: Person


def default_fixture_path() -> Path:
    # backend/iam_playground/hr/feed.py: parents[3] is the repository root.
    return Path(__file__).resolve().parents[3] / "fixtures" / f"{FIXTURE_ID}.json"


def normalize_person(raw: object) -> dict[str, Any]:
    """Copy the feed columns. Password and account fields are not kept.

    A managerEmployeeNumber is a reference. It does not create a person.
    """
    if not isinstance(raw, dict):
        raise FeedError("person must be an object")
    employee = _required_text(raw.get("employeeNumber"), "employeeNumber")
    if _EMPLOYEE.fullmatch(employee) is None:
        raise FeedError("employeeNumber is invalid")
    user_name = _required_text(raw.get("userName"), "userName")
    email = _required_text(raw.get("email"), "email")
    if "department" not in raw or not isinstance(raw.get("department"), str):
        raise FeedError("department must be a string")
    if "managerEmployeeNumber" not in raw or raw.get("managerEmployeeNumber") in {None, ""}:
        manager = None
    else:
        manager_value = raw.get("managerEmployeeNumber")
        if not isinstance(manager_value, str):
            raise FeedError("managerEmployeeNumber must be a string or null")
        if _EMPLOYEE.fullmatch(manager_value) is None:
            raise FeedError("managerEmployeeNumber is invalid")
        manager = manager_value
    return {
        "employeeNumber": employee,
        "userName": user_name,
        "email": email,
        "department": raw["department"],
        "managerEmployeeNumber": manager,
    }


class HrFeed:
    """People keyed by employee number, changes keyed by sequence."""

    def __init__(self, fixture_path: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._people: dict[str, Person] = {}
        self._order: list[str] = []
        self._changes: list[Change] = []
        self._next = 1
        self.fixture_id: str | None = None
        path = default_fixture_path() if fixture_path is None else fixture_path
        self.fixture_path = path
        if path.is_file():
            self._load(path)

    def people(self) -> list[Person]:
        with self._lock:
            return [dict(self._people[number]) for number in self._order]

    def person(self, employee_number: str) -> Person | None:
        with self._lock:
            found = self._people.get(employee_number)
            if found is None:
                return None
            return dict(found)

    def changes_after(self, after: int) -> list[Change]:
        """Changes with sequence greater than after, in sequence order.

        Equal occurredAt values are not collapsed and are not the sort key.
        """
        if type(after) is not int or after < 0:
            raise FeedError("after must be a non-negative integer")
        with self._lock:
            selected = [_copy_change(change) for change in self._changes if change["sequence"] > after]
        selected.sort(key=lambda change: change["sequence"])
        return selected

    def last_sequence(self) -> int:
        with self._lock:
            return self._next - 1

    def upsert(self, fields: dict[str, Any], *, occurred_at: str | None = None) -> tuple[Person, bool]:
        """Insert or replace one HR person. Does not rewrite the fixture file.

        The same employeeNumber updates the existing person. A new userName
        does not create a second person. The same occurredAt as an earlier
        change still allocates a new sequence.
        """
        clean = normalize_person(fields)
        when = _utc_now() if occurred_at is None else _occurred_at(occurred_at)
        with self._lock:
            created = clean["employeeNumber"] not in self._people
            operation = "create" if created else "update"
            return self._write(clean, when, operation), created

    def _load(self, path: Path) -> None:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or not isinstance(document.get("people"), list):
            raise ValueError("fixture people must be a list")
        fixture_id = document.get("fixtureId")
        if isinstance(fixture_id, str) and fixture_id != "":
            self.fixture_id = fixture_id
        for index, item in enumerate(document["people"]):
            try:
                fields = normalize_person(item)
            except FeedError as exc:
                raise ValueError(f"fixture person {index} is invalid") from exc
            self._write(fields, FIXTURE_SNAPSHOT_AT, "load")

    def _write(self, fields: dict[str, Any], occurred_at: str, operation: str) -> Person:
        # Append-only. occurred_at is stored as given and is not a dedupe key.
        number = fields["employeeNumber"]
        created = number not in self._people
        sequence = self._next
        self._next += 1
        person = _public(fields, sequence)
        change: Change = {
            "sequence": sequence,
            "occurredAt": occurred_at,
            "employeeNumber": number,
            "operation": operation,
            "person": dict(person),
        }
        self._changes.append(change)
        self._people[number] = person
        if created:
            self._order.append(number)
        return dict(person)


def _public(fields: dict[str, Any], sequence: int) -> Person:
    return {
        "employeeNumber": fields["employeeNumber"],
        "userName": fields["userName"],
        "email": fields["email"],
        "department": fields["department"],
        "managerEmployeeNumber": fields.get("managerEmployeeNumber"),
        "sequence": sequence,
    }


def _copy_change(change: Change) -> Change:
    return {
        "sequence": change["sequence"],
        "occurredAt": change["occurredAt"],
        "employeeNumber": change["employeeNumber"],
        "operation": change["operation"],
        "person": dict(change["person"]),
    }


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or value == "" or value != value.strip():
        raise FeedError(f"{name} must be a non-empty string")
    if len(value) > 200 or any(ord(char) < 32 for char in value):
        raise FeedError(f"{name} is invalid")
    return value


def _occurred_at(value: object) -> str:
    if not isinstance(value, str) or value == "" or any(ord(char) < 32 for char in value):
        raise FeedError("occurredAt must be a non-empty string")
    if len(value) > 64:
        raise FeedError("occurredAt is invalid")
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
