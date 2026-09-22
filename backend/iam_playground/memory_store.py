"""Process-local store. A failed transaction restores the snapshot."""

from __future__ import annotations

import copy
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from iam_playground.errors import ScimError
from iam_playground.records import GroupRecord, JournalEntry, LoginTxn, SessionRow, UserRecord
from iam_playground.scim_filter import EqFilter


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class MemoryStore:
    def __init__(self) -> None:
        self.users: dict[tuple[str, str], UserRecord] = {}
        self.groups: dict[tuple[str, str], GroupRecord] = {}
        self.members: set[tuple[str, str, str]] = set()
        self.bindings: dict[tuple[str, str, str], str] = {}
        self.journal: list[JournalEntry] = []
        self.logins: dict[str, LoginTxn] = {}
        self.sessions: dict[str, SessionRow] = {}
        self.generation = 1
        self.accepting = True
        self._lock = threading.RLock()

    def _snapshot(self) -> tuple:
        return (
            copy.deepcopy(self.users),
            copy.deepcopy(self.groups),
            copy.deepcopy(self.members),
            copy.deepcopy(self.bindings),
            copy.deepcopy(self.journal),
            copy.deepcopy(self.logins),
            copy.deepcopy(self.sessions),
            self.generation,
            self.accepting,
        )

    def _restore(self, snapshot: tuple) -> None:
        (
            self.users,
            self.groups,
            self.members,
            self.bindings,
            self.journal,
            self.logins,
            self.sessions,
            self.generation,
            self.accepting,
        ) = snapshot

    @contextmanager
    def transaction(self) -> Iterator[MemoryUnit]:
        with self._lock:
            snapshot = self._snapshot()
            try:
                yield MemoryUnit(self)
            except Exception:
                self._restore(snapshot)
                raise


class MemoryUnit:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def require_generation(self) -> int:
        if self.store.generation is None or not self.store.accepting:
            raise ScimError(409, "lab is not accepting")
        return self.store.generation

    def is_accepting(self) -> bool:
        return self.store.generation is not None and bool(self.store.accepting)

    def username_taken(self, app_id: str, user_name: str) -> bool:
        needle = user_name.lower()
        return any(
            user.app_id == app_id and user.user_name.lower() == needle for user in self.store.users.values()
        )

    def insert_user(self, user: UserRecord) -> None:
        if self.username_taken(user.app_id, user.user_name):
            raise ScimError(409, "userName is already in use", "uniqueness")
        self.store.users[(user.app_id, user.id)] = user

    def save_user(self, user: UserRecord) -> None:
        self.store.users[(user.app_id, user.id)] = user

    def get_user(self, app_id: str, user_id: str) -> UserRecord | None:
        return self.store.users.get((app_id, user_id))

    def delete_user(self, app_id: str, user_id: str) -> list[str] | None:
        if (app_id, user_id) not in self.store.users:
            return None
        removed = sorted(
            group_id
            for member_app, group_id, member_user in self.store.members
            if member_app == app_id and member_user == user_id
        )
        self.store.members = {
            member
            for member in self.store.members
            if not (member[0] == app_id and member[2] == user_id)
        }
        # Same effect as account_bindings ON DELETE CASCADE.
        self.store.bindings = {
            key: bound_user
            for key, bound_user in self.store.bindings.items()
            if not (key[0] == app_id and bound_user == user_id)
        }
        del self.store.users[(app_id, user_id)]
        return removed

    def list_users(
        self,
        app_id: str,
        filt: EqFilter | None,
        start_index: int,
        count: int,
    ) -> tuple[list[UserRecord], int]:
        rows = [
            user
            for user in self.store.users.values()
            if user.app_id == app_id and _user_matches(user, filt)
        ]
        rows.sort(key=lambda user: (user.user_name.lower(), user.id))
        offset = start_index - 1
        page = rows[offset : offset + count] if count else []
        return page, len(rows)

    def display_name_taken(self, app_id: str, display_name: str) -> bool:
        return any(
            group.app_id == app_id and group.display_name == display_name
            for group in self.store.groups.values()
        )

    def insert_group(self, group: GroupRecord) -> None:
        if self.display_name_taken(group.app_id, group.display_name):
            raise ScimError(409, "displayName is already in use", "uniqueness")
        self.store.groups[(group.app_id, group.id)] = group

    def get_group(self, app_id: str, group_id: str) -> GroupRecord | None:
        return self.store.groups.get((app_id, group_id))

    def delete_group(self, app_id: str, group_id: str) -> list[str] | None:
        if (app_id, group_id) not in self.store.groups:
            return None
        removed = sorted(
            user_id
            for member_app, member_group, user_id in self.store.members
            if member_app == app_id and member_group == group_id
        )
        self.store.members = {
            member
            for member in self.store.members
            if not (member[0] == app_id and member[1] == group_id)
        }
        del self.store.groups[(app_id, group_id)]
        return removed

    def list_groups(
        self,
        app_id: str,
        filt: EqFilter | None,
        start_index: int,
        count: int,
    ) -> tuple[list[tuple[GroupRecord, list[str]]], int]:
        rows = [
            group
            for group in self.store.groups.values()
            if group.app_id == app_id and _group_matches(group, filt)
        ]
        rows.sort(key=lambda group: (group.display_name, group.id))
        total = len(rows)
        offset = start_index - 1
        page = rows[offset : offset + count] if count else []
        return [(group, self.member_ids(app_id, group.id)) for group in page], total

    def member_ids(self, app_id: str, group_id: str) -> list[str]:
        return sorted(
            user_id
            for member_app, member_group, user_id in self.store.members
            if member_app == app_id and member_group == group_id
        )

    def add_member(self, app_id: str, group_id: str, user_id: str) -> bool:
        if not self.user_exists(app_id, user_id):
            raise ScimError(400, "member is not a user in this application", "invalidValue")
        if (app_id, group_id) not in self.store.groups:
            raise ScimError(404, "group not found")
        key = (app_id, group_id, user_id)
        if key in self.store.members:
            return False
        self.store.members.add(key)
        return True

    def remove_member(self, app_id: str, group_id: str, user_id: str) -> bool:
        key = (app_id, group_id, user_id)
        if key not in self.store.members:
            return False
        self.store.members.remove(key)
        return True

    def user_exists(self, app_id: str, user_id: str) -> bool:
        return (app_id, user_id) in self.store.users

    def user_in_group_named(self, app_id: str, user_id: str, display_name: str) -> bool:
        for member_app, group_id, member_user in self.store.members:
            if member_app != app_id or member_user != user_id:
                continue
            group = self.store.groups.get((app_id, group_id))
            if group is not None and group.display_name == display_name:
                return True
        return False

    def journal(self, generation: int, app_id: str, actor: str, op: str, subject_id: str) -> None:
        self.store.journal.append(
            JournalEntry(
                generation=generation,
                app_id=app_id,
                actor=actor,
                op=op,
                subject_id=subject_id,
                at=datetime.now(timezone.utc),
            )
        )

    def upsert_binding(self, app_id: str, issuer: str, subject: str, scim_user_id: str) -> None:
        self.store.bindings[(app_id, issuer, subject)] = scim_user_id

    def get_binding(self, app_id: str, issuer: str, subject: str) -> str | None:
        return self.store.bindings.get((app_id, issuer, subject))

    def insert_login(self, state: str, code_verifier: str, expires_at: datetime) -> None:
        self.store.logins[state] = LoginTxn(state, code_verifier, expires_at)

    def pop_login(self, state: str) -> LoginTxn | None:
        row = self.store.logins.pop(state, None)
        if row is None or _as_utc(row.expires_at) <= datetime.now(timezone.utc):
            return None
        return row

    def insert_session(self, session_id: str, issuer: str, subject: str, expires_at: datetime) -> None:
        self.store.sessions[session_id] = SessionRow(session_id, issuer, subject, expires_at)

    def get_session(self, session_id: str) -> SessionRow | None:
        return self.store.sessions.get(session_id)


def _user_matches(user: UserRecord, filt: EqFilter | None) -> bool:
    if filt is None:
        return True
    if filt.attribute == "userName":
        return user.user_name.lower() == str(filt.value).lower()
    if filt.attribute == "emails.value":
        return user.email.lower() == str(filt.value).lower()
    if filt.attribute == "active":
        return user.active is filt.value
    if filt.attribute == "externalId":
        return user.external_id == filt.value
    raise ScimError(400, "filter attribute is not supported", "invalidFilter")


def _group_matches(group: GroupRecord, filt: EqFilter | None) -> bool:
    if filt is None:
        return True
    if filt.attribute == "displayName":
        return group.display_name == filt.value
    raise ScimError(400, "filter attribute is not supported", "invalidFilter")
