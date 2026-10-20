"""Every tool source's state, so an agent's missing tool has a visible cause (FR-040, FR-041).

Four states for an MCP server, kept apart because each is fixed differently:

  not-configured  a source the product expects (the session watcher) has no entry
  disabled        configured, switched off
  unreachable     enabled, and loading it FAILED — with the error
  live            enabled, loaded, contributing N tools

Before this, a server that failed to load was logged and skipped, and the tool
catalog marked every local server `connected: true` regardless, so a dead
server and a source nobody configured looked the same: an agent without the
tool. The occasion for SC-024 is the connector half: Gmail was ACTIVE in
Composio while the assistant asked the user to grant OAuth access, because
connector tools load only when a conversation selects them. "Authorised but not
selected here" is a different fact from "not authorised", and is shown as one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

#: Sources the product expects to exist. Absent from extensions_config, they
#: are reported as NOT CONFIGURED rather than simply not listed — an absent row
#: is the empty state this surface exists to replace.
EXPECTED_LOCAL_SOURCES = ("session-watcher",)

LocalState = Literal["not-configured", "disabled", "unreachable", "live", "not-loaded"]
ConnectorState = Literal["not-authorised", "authorised-not-selected", "authorised-selected", "authorised"]


class ToolSource(BaseModel):
    id: str  # local:<server> or connector:<SLUG>, as the thread tool picker names them
    name: str
    kind: Literal["local", "connector"]
    state: str
    tool_count: int | None = None
    error: str | None = None
    #: Only meaningful when a conversation was asked about.
    selected: bool | None = None
    #: Feature 006: when a call to this source last came back without error
    #: (OBSERVED working), and when one last failed. None: never seen.
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    #: The last failure's error, redacted for display.
    last_error: str | None = None
    #: True when last_error could not be safely redacted and is withheld.
    last_error_withheld: bool = False


class ToolSourcesView(BaseModel):
    sources: list[ToolSource]
    #: How many sources are configured-and-enabled but not working. The sidebar
    #: shows it, so a load failure reaches the user rather than waiting for them
    #: to come and look (FR-041).
    failing: int
    #: None when no conversation was asked about.
    thread_id: str | None = None
    #: Composio is optional. Without an API key, connectors cannot be authorised
    #: here at all, which is stated rather than shown as eight "not authorised".
    connectors_available: bool = True


def describe_tool_sources(
    *,
    servers: dict[str, Any],
    last_loads: dict[str, Any],
    connector_toolkits: list[dict],
    authorised: set[str] | None,
    selected: set[str] | None,
    thread_id: str | None = None,
    health: dict[str, Any] | None = None,
) -> ToolSourcesView:
    """Pure: configured servers, what their last load did, and connector state.

    `servers` is extensions_config's mcpServers (name -> config with `enabled`);
    `last_loads` the harness load report; `authorised` the toolkit slugs with an
    ACTIVE connection, or None when Composio is not available; `selected` the
    conversation's namespaced source ids, or None for no conversation;
    `health` what the tool-call chokepoint observed per source id
    (ToolSourceHealthRepository.for_user), or None when it cannot be read.
    """
    out: list[ToolSource] = []
    for name in EXPECTED_LOCAL_SOURCES:
        if name not in servers:
            out.append(ToolSource(id=f"local:{name}", name=name, kind="local", state="not-configured"))

    for name, cfg in servers.items():
        if name.lower().startswith(("connector-", "composio-")):
            continue  # connectors are reported from Composio, below
        sid = f"local:{name}"
        sel = (sid in selected) if selected is not None else None
        if not getattr(cfg, "enabled", True):
            out.append(ToolSource(id=sid, name=name, kind="local", state="disabled", selected=sel))
            continue
        load = last_loads.get(name)
        if load is None:
            out.append(ToolSource(id=sid, name=name, kind="local", state="not-loaded", selected=sel))
        elif load.loaded:
            out.append(ToolSource(id=sid, name=name, kind="local", state="live", tool_count=load.tool_count, selected=sel))
        else:
            out.append(ToolSource(id=sid, name=name, kind="local", state="unreachable", error=load.error, selected=sel))

    for toolkit in connector_toolkits:
        slug = toolkit["slug"]
        sid = f"connector:{slug}"
        if authorised is None:
            continue
        if slug not in authorised:
            state = "not-authorised"
        elif selected is None:
            state = "authorised"
        else:
            state = "authorised-selected" if sid in selected else "authorised-not-selected"
        out.append(ToolSource(id=sid, name=toolkit.get("name", slug), kind="connector", state=state, selected=(sid in selected) if selected is not None else None))

    for source in out:
        observed = (health or {}).get(source.id)
        if observed is not None:
            source.last_success_at = observed.last_success_at
            source.last_failure_at = observed.last_failure_at
            if observed.last_error:
                from app.gateway.display_redaction import for_display

                source.last_error, source.last_error_withheld = for_display(observed.last_error)

    failing = sum(1 for s in out if s.state == "unreachable")
    return ToolSourcesView(sources=out, failing=failing, thread_id=thread_id, connectors_available=authorised is not None)
