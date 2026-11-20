"""Which run may build an MCP server: only one MCP Studio started.

MCP servers are developed in MCP Studio, never from a chat. The Studio router
(``app.gateway.routers.mcp_studio``) starts a build run for ONE server and
writes that server's id into the run's runtime context under
``STUDIO_BUILD_KEY``. Nothing else writes that key:

- a run request from a client cannot carry it: the gateway keeps only an
  allowlist of client context keys, and this key is also listed as
  server-owned (``app.gateway.services.SERVER_OWNED_RUN_KEYS``);
- a resumed run is started from the recorded surface without it
  (``app.gateway.resume``), and delegated, invited, @-called, scheduled and
  workflow runs are refused below by their own server-set markers.

Two places read the decision:

1. the lead's tool assembly: the ``mcp_build`` tool and the
   ``mcp-server-builder`` skill are offered only to such a run, and that run
   gets a reduced tool list (``STUDIO_BUILD_TOOL_GROUPS``, no delegation, no
   connectors or MCP tools, no builder, ledger, preview or coding-job tools);
2. the ``mcp_build`` tool itself, at dispatch: it refuses a run without the
   key, a call for any other server id, and a key the server's own record does
   not confirm (the record links the server to the thread the router opened
   for it, and to its owner).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

#: Runtime-context key the Studio router sets on the build run it starts.
STUDIO_BUILD_KEY = "mcp_studio_server_id"

#: Skills listed only to a Studio build run.
STUDIO_ONLY_SKILLS: frozenset[str] = frozenset({"mcp-server-builder"})

#: config.yaml tool groups a Studio build run keeps: reading (the skill, docs)
#: and the web (API documentation). The skill hands code over through
#: ``mcp_build`` and writes nothing to the sandbox.
STUDIO_BUILD_TOOL_GROUPS: tuple[str, ...] = ("web", "file:read")

#: In-process built-ins a Studio build run is not given.
STUDIO_BUILD_EXCLUDED_TOOLS: frozenset[str] = frozenset({"preview", "code_job", "ledger_read", "ledger_apply"})

#: What an ordinary chat is told, and what a refused call returns.
STUDIO_ONLY_MESSAGE = "MCP servers are built in MCP Studio, not in a chat. Open MCP Studio to create or change one."


def studio_build_server_id(context: Mapping[str, Any] | None) -> str | None:
    """The server this run was started by MCP Studio to build, or None.

    None for any run that carries a marker of not being the Studio build run
    itself: a custom agent, the bootstrap flow, a delegated or invited agent,
    an @-called agent, a resumed, continued, scheduled or workflow run.
    """
    from omniharness.agents.invitation import INVITED_ORIGIN_KEY
    from omniharness.agents.tool_surface import TOOL_SURFACE_KEY
    from omniharness.runtime.builder.surface import NOT_THE_OWNERS_CHAT_KEYS

    ctx = context or {}
    value = ctx.get(STUDIO_BUILD_KEY)
    if not isinstance(value, str) or not value:
        return None
    if ctx.get("turn_provenance") == "synthetic-trigger" or any(ctx.get(key) for key in NOT_THE_OWNERS_CHAT_KEYS):
        return None
    if INVITED_ORIGIN_KEY in ctx or TOOL_SURFACE_KEY in ctx:
        return None
    if ctx.get("agent_name") or ctx.get("is_bootstrap"):
        return None
    return value


def without_studio_only_skills(names: Iterable[str]) -> set[str]:
    return {name for name in names if name not in STUDIO_ONLY_SKILLS}
