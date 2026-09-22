"""Pure readiness decisions shared by the admin service and ./lab doctor."""

from __future__ import annotations

from iam_playground.constants import EXPECTED_ISSUER


def discovery_is_ready(document: object) -> bool:
    """True only when the discovery issuer is the lab issuer, exactly."""
    if not isinstance(document, dict):
        return False
    return document.get("issuer") == EXPECTED_ISSUER


def evaluate_target_row(row: tuple | None) -> tuple[bool, str]:
    if row is None:
        return False, "lab_meta has no generation row"
    generation, accepting = row[0], row[1]
    if generation is None:
        return False, "lab_meta generation is missing"
    if accepting is not True:
        return False, "lab_meta is not accepting"
    return True, "ok"


def evaluate_admin_row(row: tuple | None) -> tuple[bool, str]:
    if row is None:
        return False, "lab_meta has no generation row"
    if row[0] is None:
        return False, "lab_meta generation is missing"
    return True, "ok"


def admin_status(
    db_ok: bool,
    db_detail: str,
    document: object,
    *,
    fetch_failed: bool,
) -> tuple[bool, str]:
    if not db_ok:
        return False, db_detail
    if fetch_failed:
        return False, "keycloak discovery fetch failed"
    if not discovery_is_ready(document):
        return False, "keycloak issuer does not match"
    return True, "ok"
