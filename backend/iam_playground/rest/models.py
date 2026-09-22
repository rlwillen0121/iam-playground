"""Account row shared by the SQL store and the in-memory store."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Account:
    app_id: str
    id: int
    login: str
    employee_ref: str
    status: str
    first_name: str
    last_name: str
    department: str
    roles: tuple[str, ...] = ()

    def with_roles(self, roles: tuple[str, ...]) -> Account:
        return Account(
            app_id=self.app_id,
            id=self.id,
            login=self.login,
            employee_ref=self.employee_ref,
            status=self.status,
            first_name=self.first_name,
            last_name=self.last_name,
            department=self.department,
            roles=roles,
        )
