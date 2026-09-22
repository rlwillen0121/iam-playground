"""Proprietary REST profiles. The target app includes create_router()."""

from __future__ import annotations

from collections.abc import Callable

from iam_playground.rest.faults import FaultStore
from iam_playground.rest.snapshots import AccountSnapshots

__all__ = ["create_router"]


def create_router(
    store_factory: Callable[[], object] | None = None,
    *,
    modern_token: Callable[[], str] | None = None,
    modern_read_token: Callable[[], str] | None = None,
    legacy_key: Callable[[], str] | None = None,
    legacy_read_key: Callable[[], str] | None = None,
    fault_store: FaultStore | None = None,
    snapshots: AccountSnapshots | None = None,
):
    from iam_playground.rest.router import create_router as build

    return build(
        store_factory,
        modern_token=modern_token,
        modern_read_token=modern_read_token,
        legacy_key=legacy_key,
        legacy_read_key=legacy_read_key,
        fault_store=fault_store,
        snapshots=snapshots,
    )
