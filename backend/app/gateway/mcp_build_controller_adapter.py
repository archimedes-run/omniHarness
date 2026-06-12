"""GatewayMCPBuildController — app-layer adapter implementing the MCPBuildController port.

Mirrors GatewayPreviewController: this class is the only place that bridges
the MCPBuildController protocol (harness layer) to MCPServerManager (app layer).

The harness never imports from app.gateway; it only calls
``get_mcp_build_controller()`` and uses the protocol interface. This adapter
registers itself via ``set_mcp_build_controller()`` in the app lifespan.
"""

from __future__ import annotations

from app.gateway.mcp_server_manager import MCPBuildRecord, MCPServerManager
from omniharness.runtime.mcp.controller import MCPBuildStatus


def _to_status(record: MCPBuildRecord) -> MCPBuildStatus:
    return MCPBuildStatus(
        server_id=record.server_id,
        phase=record.phase,
        error=record.error,
        required_key_names=record.required_key_names,
        tools_discovered=record.tools_discovered,
        test_results=record.test_results,
        last_verified_at=record.last_verified_at,
    )


class GatewayMCPBuildController:
    """Implements MCPBuildController by delegating to MCPServerManager."""

    def __init__(self, manager: MCPServerManager) -> None:
        self._manager = manager

    async def request_build(self, *, server_id: str, user_id: str) -> MCPBuildStatus:
        record = await self._manager.get_status(server_id=server_id, user_id=user_id)
        return _to_status(record)

    async def test_server(self, *, server_id: str, user_id: str) -> MCPBuildStatus:
        record = await self._manager.test_server(server_id=server_id, user_id=user_id)
        return _to_status(record)

    async def get_status(self, *, server_id: str, user_id: str) -> MCPBuildStatus:
        record = await self._manager.get_status(server_id=server_id, user_id=user_id)
        return _to_status(record)

    async def register(self, *, server_id: str, user_id: str) -> MCPBuildStatus:
        record = await self._manager.register(server_id=server_id, user_id=user_id)
        return _to_status(record)

    async def submit_source_and_test(self, *, server_id: str, user_id: str, source_code: str) -> MCPBuildStatus:
        record = await self._manager.submit_source_and_test(server_id=server_id, user_id=user_id, source_code=source_code)
        return _to_status(record)

    async def stop(self, *, server_id: str, user_id: str) -> MCPBuildStatus:
        record = await self._manager.stop(server_id=server_id, user_id=user_id)
        return _to_status(record)
