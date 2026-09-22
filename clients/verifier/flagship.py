"""Per-stage read and admin expectations for the flagship journey.

Pure data. This module does not collect observations, provision accounts,
or decide that a missing pre-provision probe failed the run. A coordinator
judges one stage at a time after the verifier has read status and reason.
"""

from __future__ import annotations

STAGES = ("unprovisioned", "reader", "administrator", "revoked", "disabled")

# (read status, read reason), (admin status, admin reason)
_EXPECTED: dict[str, tuple[tuple[int, str], tuple[int, str]]] = {
    "unprovisioned": ((403, "no_account"), (403, "no_account")),
    "reader": ((200, "allow"), (403, "not_an_administrator")),
    "administrator": ((200, "allow"), (200, "allow")),
    "revoked": ((200, "allow"), (403, "not_an_administrator")),
    "disabled": ((403, "disabled"), (403, "disabled")),
}


def flagship_expectations(stage: str) -> dict[str, dict[str, int | str]]:
    """Expected /api/read and /api/admin status and reason for one stage."""
    if not isinstance(stage, str) or stage not in _EXPECTED:
        raise ValueError("unknown flagship stage")
    read, admin = _EXPECTED[stage]
    return {
        "read": {"status": read[0], "reason": read[1]},
        "admin": {"status": admin[0], "reason": admin[1]},
    }


def judge_stage(
    stage: str,
    read_status: int | None,
    read_reason: str | None,
    admin_status: int | None,
    admin_reason: str | None,
) -> str:
    """PASSED or FAILED when every probe input is present. INDETERMINATE if any is None."""
    expected = flagship_expectations(stage)
    if any(value is None for value in (read_status, read_reason, admin_status, admin_reason)):
        return "INDETERMINATE"
    matched = (
        read_status == expected["read"]["status"]
        and read_reason == expected["read"]["reason"]
        and admin_status == expected["admin"]["status"]
        and admin_reason == expected["admin"]["reason"]
    )
    return "PASSED" if matched else "FAILED"
