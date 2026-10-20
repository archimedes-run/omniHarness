"""Feature 005 FR-020 (001 FR-018b, FR-023): a second agent changes no tool.

tool_surface.snapshot.json was captured from the watcher BEFORE Codex support
was added. Codex sessions must appear in the same tools' replies; any change
to the tools' names or arguments fails here.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import mcp.types as types
from session_watcher.server import build_server, build_service

SNAPSHOT = Path(__file__).with_name("tool_surface.snapshot.json")


def test_the_tool_surface_is_the_snapshot_taken_before_codex(tmp_path) -> None:
    service = build_service(tmp_path / "claude", tmp_path / "codex")  # as main builds it
    server = build_server(service)
    res = asyncio.run(server.request_handlers[types.ListToolsRequest](types.ListToolsRequest(method="tools/list")))
    tools = [{"name": t.name, "inputSchema": t.inputSchema} for t in res.root.tools]
    assert json.loads(json.dumps(tools, sort_keys=True)) == json.loads(SNAPSHOT.read_text())
