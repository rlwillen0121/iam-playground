"""In-memory shapes shared by the SQL store and the test double."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class UserRecord:
    id: str
    app_id: str
    external_id: str | None
    user_name: str
    active: bool
    given_name: str
    family_name: str
    email: str
    employee_number: str
    department: str


@dataclass
class UserInput:
    external_id: str | None
    user_name: str
    active: bool
    given_name: str
    family_name: str
    email: str
    employee_number: str
    department: str


@dataclass
class GroupRecord:
    id: str
    app_id: str
    display_name: str
    external_id: str | None


@dataclass
class JournalEntry:
    generation: int
    app_id: str
    actor: str
    op: str
    subject_id: str
    at: datetime


@dataclass
class LoginTxn:
    state: str
    code_verifier: str
    expires_at: datetime


@dataclass
class SessionRow:
    id: str
    issuer: str
    subject: str
    expires_at: datetime
