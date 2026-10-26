"""OpenCode coding jobs in the session watcher (spec 009 FR-010).

The gateway's relay writer (app.gateway.code_jobs.relay) writes the files;
the watcher is built by `build_service` (what `main()` uses) and queried
through the real MCP tool handler. Observe-only: the adapter only reads.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import mcp.types as types
from session_watcher.server import build_server, build_service


def _call(server, name: str, args: dict) -> dict:
    req = types.CallToolRequest(method="tools/call", params=types.CallToolRequestParams(name=name, arguments=args))
    res = asyncio.run(server.request_handlers[types.CallToolRequest](req))
    return json.loads(res.root.content[0].text)


def _sessions(tmp_path) -> dict:
    (tmp_path / "claude").mkdir(exist_ok=True)
    service = build_service(tmp_path / "claude", None, tmp_path / "relay")
    service.refresh(now=datetime.now(UTC) + timedelta(seconds=1))
    return _call(build_server(service), "list_coding_sessions", {})


def test_a_running_job_is_listed_as_an_opencode_session_and_its_end_is_observed(tmp_path):
    from app.gateway.code_jobs.relay import Relay

    relay = Relay(tmp_path / "relay", "job12345abc")
    relay.session()
    relay.command(0)
    payload = _sessions(tmp_path)
    session = next(s for s in payload["sessions"] if s["agent"] == "opencode")
    # Content-free: an opaque label, never the request or the project's name.
    assert session["agent_label"] == "OpenCode" and session["project"] == "coding job job12345"
    assert session["state"] == "working"
    assert [a["agent"] for a in payload["agents"]] == ["claude", "opencode"]

    relay.files(2)
    relay.end(status="verified")
    payload = _sessions(tmp_path)
    session = next(s for s in payload["sessions"] if s["agent"] == "opencode")
    assert session["state"] == "idle" and len(session["files_changed"]) == 2


def test_a_relay_line_of_an_unknown_type_is_drift_not_a_crash(tmp_path):
    from app.gateway.code_jobs.relay import Relay

    relay = Relay(tmp_path / "relay", "job9")
    relay.session()
    with relay.path.open("a") as handle:
        handle.write(json.dumps({"type": "surprise", "timestamp": datetime.now(UTC).isoformat()}) + "\n")
    payload = _sessions(tmp_path)
    agent = next(a for a in payload["agents"] if a["agent"] == "opencode")
    assert agent["drift"] >= 1
