"""Errors that map to HTTP responses. Details are safe to return."""

from __future__ import annotations


class ScimError(Exception):
    def __init__(self, status: int, detail: str, scim_type: str | None = None) -> None:
        self.status = status
        self.detail = detail
        self.scim_type = scim_type
        super().__init__(detail)


class DependencyFailure(Exception):
    """Database or identity-provider dependency failed. Callers answer 503."""


class TokenRejected(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)
