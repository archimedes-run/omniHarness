"""Verify the MCPBuildController port satisfies the harness/app boundary.

1. The controller module lives in omniharness.runtime.mcp — harness layer.
2. It must not import from app.* (enforced separately by test_harness_boundary.py).
3. GatewayMCPBuildController (app layer) satisfies the Protocol at runtime.
4. Singleton accessor round-trip works.
"""

from __future__ import annotations


def test_controller_module_importable() -> None:
    from omniharness.runtime.mcp.controller import MCPBuildController, MCPBuildStatus  # noqa: F401


def test_controller_module_does_not_import_app() -> None:
    """The controller module source must not reference app.* at the top level."""
    import importlib.util

    spec = importlib.util.find_spec("omniharness.runtime.mcp.controller")
    assert spec is not None and spec.origin is not None
    with open(spec.origin) as f:
        source = f.read()
    assert "from app" not in source, "omniharness.runtime.mcp.controller imports from app.*"
    assert "import app" not in source, "omniharness.runtime.mcp.controller imports from app.*"


def test_mcp_build_status_has_no_secret_fields() -> None:
    """MCPBuildStatus must not have fields that could carry secret values."""
    from omniharness.runtime.mcp.controller import MCPBuildStatus

    fields = set(MCPBuildStatus.__dataclass_fields__)
    forbidden = {"secret", "value", "ciphertext", "token", "password", "key_value"}
    overlap = fields & forbidden
    assert not overlap, f"MCPBuildStatus has secret-looking fields: {overlap}"


def test_gateway_adapter_satisfies_protocol() -> None:
    """GatewayMCPBuildController is an instance of the MCPBuildController Protocol."""
    from unittest.mock import AsyncMock

    from app.gateway.mcp_build_controller_adapter import GatewayMCPBuildController
    from app.gateway.mcp_server_manager import MCPServerManager
    from omniharness.runtime.mcp.controller import MCPBuildController

    mock_manager = AsyncMock(spec=MCPServerManager)
    ctrl = GatewayMCPBuildController(mock_manager)
    assert isinstance(ctrl, MCPBuildController)


def test_singleton_set_get_reset() -> None:
    from unittest.mock import AsyncMock

    from app.gateway.mcp_build_controller_adapter import GatewayMCPBuildController
    from app.gateway.mcp_server_manager import MCPServerManager
    from omniharness.runtime.mcp.controller import (
        get_mcp_build_controller,
        reset_mcp_build_controller,
        set_mcp_build_controller,
    )

    try:
        mock_manager = AsyncMock(spec=MCPServerManager)
        ctrl = GatewayMCPBuildController(mock_manager)
        assert get_mcp_build_controller() is None
        set_mcp_build_controller(ctrl)
        assert get_mcp_build_controller() is ctrl
    finally:
        reset_mcp_build_controller()
        assert get_mcp_build_controller() is None
