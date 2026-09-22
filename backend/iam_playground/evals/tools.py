"""Agent tool names for the in-memory evaluation dispatcher.

Trusted binding and ledger edits are not tools. They are absent from
``AGENT_TOOLS`` on purpose.
"""

from __future__ import annotations

LOOKUP_ACCOUNT = "lookup_account"
LIST_GROUPS = "list_groups"
CREATE_ACCOUNT = "create_account"
UPDATE_ACCOUNT = "update_account"
ADD_MEMBERSHIP = "add_membership"
REMOVE_MEMBERSHIP = "remove_membership"
DISABLE_ACCOUNT = "disable_account"

TRUSTED_BINDING = "trusted_binding"
EDIT_LEDGER = "edit_ledger"

READ_TOOLS = frozenset({LOOKUP_ACCOUNT, LIST_GROUPS})
WRITE_TOOLS = frozenset(
    {
        CREATE_ACCOUNT,
        UPDATE_ACCOUNT,
        ADD_MEMBERSHIP,
        REMOVE_MEMBERSHIP,
        DISABLE_ACCOUNT,
    }
)
AGENT_TOOLS = READ_TOOLS | WRITE_TOOLS
NON_TOOLS = frozenset({TRUSTED_BINDING, EDIT_LEDGER})
# Ledger methods are not dispatcher operations. Naming them in a call does not edit rows.
LEDGER_CALLS = frozenset(
    {
        EDIT_LEDGER,
        "note_lifecycle",
        "release_lifecycle",
        "forget",
        "seed",
        "seed_grant",
    }
)

ADMINISTRATORS = "Administrators"
READERS = "Readers"


def agent_tool_names() -> frozenset[str]:
    """Tools the dispatcher can run. Binding and ledger edits are not included."""
    return AGENT_TOOLS
