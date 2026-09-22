"""Grant ownership for the managed mover.

A grant's source is ``lifecycle`` or ``manual``. The mover may remove only a
lifecycle-owned department entitlement. A manual grant stays. When both sources
share an entitlement, the native membership stays after the lifecycle row is
released. Observed membership is not copied into the ledger.

This module has no agent tool. ``seed``, ``note_lifecycle``, ``release_lifecycle``,
and ``forget`` are fixture and dispatcher bookkeeping.
"""

from __future__ import annotations

from dataclasses import dataclass

LIFECYCLE = "lifecycle"
MANUAL = "manual"
SOURCES = frozenset({LIFECYCLE, MANUAL})

# Fixture groups that are department access. Not every HR department string.
DEPARTMENT_ENTITLEMENTS = frozenset({"Engineering", "Sales", "Support", "Finance"})

FORBID = "forbid"
REMOVE_NATIVE = "remove_native"
RETAIN_NATIVE = "retain_native"


@dataclass(frozen=True)
class Grant:
    """One ownership row: account, entitlement, and lifecycle or manual source."""

    account_id: str
    entitlement: str
    source: str

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise ValueError("grant source must be lifecycle or manual")
        if self.account_id == "" or self.entitlement == "":
            raise ValueError("grant requires an account id and an entitlement")


class OwnershipLedger:
    """In-memory ownership rows. Not exposed through the agent tool API."""

    def __init__(self) -> None:
        self._grants: set[Grant] = set()

    def grants(self) -> tuple[Grant, ...]:
        return tuple(sorted(self._grants, key=lambda grant: (grant.account_id, grant.entitlement, grant.source)))

    def sources(self, account_id: str, entitlement: str) -> frozenset[str]:
        return frozenset(
            grant.source
            for grant in self._grants
            if grant.account_id == account_id and grant.entitlement == entitlement
        )

    def seed(self, grant: Grant) -> None:
        """Insert a fixture row. Idempotent. Not an agent tool."""
        self._grants.add(grant)

    def note_lifecycle(self, account_id: str, entitlement: str) -> None:
        """Record lifecycle ownership after an authorized department grant."""
        if entitlement not in DEPARTMENT_ENTITLEMENTS:
            return
        self._grants.add(Grant(account_id, entitlement, LIFECYCLE))

    def release_lifecycle(self, account_id: str, entitlement: str) -> bool:
        """Drop only the lifecycle row. Manual ownership is left in place."""
        grant = Grant(account_id, entitlement, LIFECYCLE)
        if grant not in self._grants:
            return False
        self._grants.remove(grant)
        return True

    def forget(self, account_id: str, entitlement: str) -> None:
        """Drop every source after a leaver removes that native membership."""
        self._grants = {
            grant
            for grant in self._grants
            if not (grant.account_id == account_id and grant.entitlement == entitlement)
        }

    def mover_effect(self, account_id: str, entitlement: str) -> str:
        """How a mover removal applies.

        ``remove_native`` only for a lifecycle-only department entitlement.
        ``retain_native`` when a manual owner overlaps that department entitlement.
        ``forbid`` for manual-only, unknown, or non-department grants.
        """
        sources = self.sources(account_id, entitlement)
        if LIFECYCLE not in sources or entitlement not in DEPARTMENT_ENTITLEMENTS:
            return FORBID
        if MANUAL in sources:
            return RETAIN_NATIVE
        return REMOVE_NATIVE
