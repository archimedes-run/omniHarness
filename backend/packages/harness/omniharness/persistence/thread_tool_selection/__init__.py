"""Per-thread tool-selection persistence.

Stores which tool *sources* a conversation has enabled. Sources are always the
namespaced ids used by the assembly path (``local:<server>`` /
``connector:<SLUG>``) — never raw tool names — so the selection survives the
local-``github`` vs connector-``GITHUB`` collision at read time.
"""

from omniharness.persistence.thread_tool_selection.model import ThreadToolSelectionRow
from omniharness.persistence.thread_tool_selection.sql import ThreadToolSelectionRepository

__all__ = ["ThreadToolSelectionRow", "ThreadToolSelectionRepository"]
