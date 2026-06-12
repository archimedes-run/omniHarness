"""MCPBuildController port: harness-layer protocol for MCP server build operations.

This module is the ONLY place the harness layer knows about MCP build operations.
It defines the protocol and the module-level singleton accessors.

The concrete implementation lives in app/gateway/mcp_build_controller_adapter.py and
must never be imported here. The harness → app boundary must not be crossed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable


@dataclass
class MCPBuildStatus:
    """Snapshot of a single MCP server's build/run state.

    Contains phase and error only — never secret values or env-var contents.
    Key names (not values) may appear in required_key_names for UI display.
    tools_discovered and test_results hold tool schemas and test outcomes, not secret values.
    """

    server_id: str
    phase: Literal["idle", "building", "testing", "verified", "ready", "failed", "stopped"]
    error: str | None = None
    required_key_names: list[str] = field(default_factory=list)
    tools_discovered: list[dict] = field(default_factory=list)
    test_results: list[dict] = field(default_factory=list)
    last_verified_at: str | None = None


@runtime_checkable
class MCPBuildController(Protocol):
    """Protocol the app layer implements so the harness can trigger MCP builds
    without a direct dependency on app.gateway."""

    async def request_build(self, *, server_id: str, user_id: str) -> MCPBuildStatus:
        """Enqueue a build for *server_id*. Non-raising on scheduling success."""
        ...

    async def test_server(self, *, server_id: str, user_id: str) -> MCPBuildStatus:
        """Run scanner + secrets check + egress validation. No execution in Phase 2."""
        ...

    async def get_status(self, *, server_id: str, user_id: str) -> MCPBuildStatus:
        """Return current build/run phase for *server_id*."""
        ...

    async def register(self, *, server_id: str, user_id: str) -> MCPBuildStatus:
        """Register an approved server for agent use. Raises if not approved."""
        ...

    async def submit_source_and_test(self, *, server_id: str, user_id: str, source_code: str) -> MCPBuildStatus:
        """Save source_code for server_id and run the full test pipeline."""
        ...

    async def stop(self, *, server_id: str, user_id: str) -> MCPBuildStatus:
        """Stop a running server."""
        ...


# ---------------------------------------------------------------------------
# Module-level singleton (mirrors omniharness.preview.preview_controller)
# ---------------------------------------------------------------------------

_default_controller: MCPBuildController | None = None


def get_mcp_build_controller() -> MCPBuildController | None:
    """Return the active MCPBuildController, or None if not configured."""
    return _default_controller


def set_mcp_build_controller(controller: MCPBuildController) -> None:
    """Register the active MCPBuildController (called during app startup)."""
    global _default_controller
    _default_controller = controller


def reset_mcp_build_controller() -> None:
    """Clear the registered controller (used in tests)."""
    global _default_controller
    _default_controller = None
