"""Which tool source a tool came from, carried on the tool itself.

Set where tools are assembled (local MCP servers in tools.get_available_tools,
connector toolkits in connector_tools), read at the tool-call chokepoint by
ToolSourceHealthMiddleware. A tool with no tag (a built-in) has no source and
is never recorded.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool

_SOURCE = "omniharness_source"
_OWNER = "omniharness_source_owner"


def tag_source(tool: BaseTool, source_id: str, owner_id: str = "") -> None:
    """Mark *tool* as coming from *source_id*; *owner_id* is the user for a connector."""
    meta = dict(tool.metadata or {})
    meta[_SOURCE] = source_id
    meta[_OWNER] = owner_id
    tool.metadata = meta


def source_of(tool: BaseTool | None) -> tuple[str, str] | None:
    """(source_id, owner_id) for a tagged tool, else None."""
    meta = getattr(tool, "metadata", None) or {}
    source = meta.get(_SOURCE)
    if not isinstance(source, str) or not source:
        return None
    return source, str(meta.get(_OWNER) or "")
