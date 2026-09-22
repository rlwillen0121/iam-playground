"""Lifecycle versus manual grant ledger.

The ledger is not a target account store. remove_obsolete drops lifecycle
ownership only. Manual grants stay. If both owners remain conceptually,
the manual owner is left in place and that entitlement is not returned for
native removal. Rehire grants only the entitlements it is given and does
not copy historical privileges. Rename keeps the employee number and does
not create a second person. Rename does not replace a trusted binding;
this ledger has no binding to replace.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

LIFECYCLE = "lifecycle"
MANUAL = "manual"
_OWNERS = frozenset({LIFECYCLE, MANUAL})


@dataclass(frozen=True)
class Grant:
    employee_number: str
    target: str
    entitlement: str
    owner: str

    def __post_init__(self) -> None:
        if self.owner not in _OWNERS:
            raise ValueError("owner must be lifecycle or manual")
        _text(self.employee_number, "employee_number")
        _text(self.target, "target")
        _text(self.entitlement, "entitlement")


class OwnershipLedger:
    def __init__(self) -> None:
        self._people: dict[str, dict[str, str]] = {}
        self._grants: dict[tuple[str, str, str, str], Grant] = {}
        self._history: dict[tuple[str, str], set[str]] = {}

    def add_person(self, employee_number: str, *, user_name: str, email: str) -> dict[str, str]:
        employee_number = _text(employee_number, "employee_number")
        user_name = _text(user_name, "user_name")
        email = _text(email, "email")
        if employee_number in self._people:
            raise ValueError("person already exists")
        person = {
            "employeeNumber": employee_number,
            "userName": user_name,
            "email": email,
        }
        self._people[employee_number] = person
        return dict(person)

    def grant(self, employee_number: str, entitlement: str, owner: str, *, target: str) -> Grant:
        """Record one owner. Does not read current target membership."""
        if employee_number not in self._people:
            raise KeyError(employee_number)
        if owner not in _OWNERS:
            raise ValueError("owner must be lifecycle or manual")
        grant = Grant(
            employee_number,
            _text(target, "target"),
            _text(entitlement, "entitlement"),
            owner,
        )
        key = (grant.employee_number, grant.target, grant.entitlement, grant.owner)
        existing = self._grants.get(key)
        if existing is not None:
            return existing
        self._grants[key] = grant
        if owner == LIFECYCLE:
            self._history.setdefault((grant.employee_number, grant.target), set()).add(grant.entitlement)
        return grant

    def remove_obsolete(
        self,
        employee_number: str,
        entitlements: Iterable[str],
        *,
        target: str,
    ) -> list[str]:
        """Remove lifecycle ownership for these entitlements.

        Manual grants stay, including a manual grant for the same entitlement.
        The returned entitlements have no owner left. Do not remove a native
        membership for an entitlement that is not returned.
        """
        if employee_number not in self._people:
            raise KeyError(employee_number)
        target = _text(target, "target")
        obsolete = _names(entitlements)
        removed: list[str] = []
        for entitlement in sorted(obsolete):
            key = (employee_number, target, entitlement, LIFECYCLE)
            if key not in self._grants:
                continue
            del self._grants[key]
            if not self._owners(employee_number, entitlement, target):
                removed.append(entitlement)
        return removed

    def rehire(self, employee_number: str, current: Iterable[str], *, target: str) -> None:
        """Grant current lifecycle access only.

        Historical privileges are not copied. Manual grants stay.
        This does not create a person or a target account.
        """
        if employee_number not in self._people:
            raise KeyError(employee_number)
        target = _text(target, "target")
        authorized = _names(current)
        # `authorized` is the only grant source. self._history is not read.
        stale = [
            grant.entitlement
            for grant in self._grants.values()
            if grant.employee_number == employee_number
            and grant.target == target
            and grant.owner == LIFECYCLE
            and grant.entitlement not in authorized
        ]
        self.remove_obsolete(employee_number, stale, target=target)
        for entitlement in sorted(authorized):
            self.grant(employee_number, entitlement, LIFECYCLE, target=target)

    def rename(self, employee_number: str, *, user_name: str, email: str | None = None) -> dict[str, str]:
        """Keep employee_number. Do not insert another person."""
        if employee_number not in self._people:
            raise KeyError(employee_number)
        user_name = _text(user_name, "user_name")
        if email is not None:
            email = _text(email, "email")
        person = self._people[employee_number]
        person["userName"] = user_name
        if email is not None:
            person["email"] = email
        person["employeeNumber"] = employee_number
        return dict(person)

    def people(self) -> list[dict[str, str]]:
        return [dict(self._people[number]) for number in sorted(self._people)]

    def grants_for(self, employee_number: str, *, target: str | None = None) -> list[Grant]:
        found = [
            grant
            for grant in self._grants.values()
            if grant.employee_number == employee_number and (target is None or grant.target == target)
        ]
        return sorted(found, key=lambda grant: (grant.target, grant.entitlement, grant.owner))

    def owners(self, employee_number: str, entitlement: str, *, target: str) -> set[str]:
        return self._owners(employee_number, _text(entitlement, "entitlement"), _text(target, "target"))

    def historical_privileges(self, employee_number: str, *, target: str) -> frozenset[str]:
        """Lifecycle entitlements once granted. Not a source for rehire."""
        target = _text(target, "target")
        return frozenset(self._history.get((employee_number, target), ()))

    def _owners(self, employee_number: str, entitlement: str, target: str) -> set[str]:
        return {
            grant.owner
            for grant in self._grants.values()
            if grant.employee_number == employee_number
            and grant.entitlement == entitlement
            and grant.target == target
        }


def _names(values: Iterable[str]) -> set[str]:
    if isinstance(values, (str, bytes)):
        raise ValueError("entitlements must be a sequence of strings")
    return {_text(item, "entitlement") for item in values}


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or value == "" or value != value.strip():
        raise ValueError(f"{name} is required")
    if len(value) > 200 or any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} is invalid")
    return value
