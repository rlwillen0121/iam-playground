"""HTTP errors for the MCP pack. Details are safe to return."""

from __future__ import annotations


class PackError(Exception):
    def __init__(self, status: int, detail: str, *, source: str | None = None) -> None:
        self.status = status
        self.detail = detail
        self.source = source
        super().__init__(detail)


class FaultStoreError(Exception):
    """The fault counter store could not be read or written."""

    def __init__(self, detail: str = "fault store unavailable") -> None:
        self.detail = detail
        super().__init__(detail)
