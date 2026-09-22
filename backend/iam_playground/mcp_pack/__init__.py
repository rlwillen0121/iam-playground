"""Bounded MCP tool service for the lab SCIM target."""

from iam_playground.mcp_pack.app import create_app
from iam_playground.mcp_pack.journal import record_event

__all__ = ["create_app", "record_event"]
