"""T066-T068 — the MCP surface contract (FR-018b, FR-023, FR-015, FR-016)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from mcp import types as t
from session_watcher.models import Session, SessionState
from session_watcher.registry import SessionRegistry
from session_watcher.server import WatcherService, build_server

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
EXPECTED_TOOLS = {"list_coding_sessions", "get_session_status"}


def _tools():
    server = build_server(WatcherService(root=None))  # type: ignore[arg-type]
    res = asyncio.run(server.request_handlers[t.ListToolsRequest](t.ListToolsRequest(method="tools/list")))
    return res.root.tools


def test_tool_set_matches_the_contract_exactly() -> None:
    """Adding an adapter must not change this set (FR-023, FR-018b)."""
    assert {x.name for x in _tools()} == EXPECTED_TOOLS


def test_tool_arguments_match_the_contract() -> None:
    by = {x.name: x.inputSchema for x in _tools()}
    assert by["list_coding_sessions"].get("properties") == {}
    props = by["get_session_status"]["properties"]
    assert set(props) == {"session_id"}
    assert by["get_session_status"]["required"] == ["session_id"]


def test_no_mutation_argument_and_no_third_tool() -> None:
    """FR-015, Article IV — observe-only enforced by ABSENCE, not by policy."""
    tools = _tools()
    assert len(tools) == 2
    forbidden = ("answer", "reply", "send", "approve", "intervene", "write", "kill", "stop")
    for x in tools:
        assert not any(f in x.name.lower() for f in forbidden)
        for prop in x.inputSchema.get("properties") or {}:
            assert not any(f in prop.lower() for f in forbidden)


def test_tool_descriptions_carry_the_wording_rules_for_a_rephrasing_caller() -> None:
    by = {x.name: (x.description or "") for x in _tools()}
    roll = by["list_coding_sessions"]
    assert "observable" in roll and "does NOT mean no" in roll
    detail = by["get_session_status"]
    assert "OBSERVED" in detail and "INFERRED" in detail


def test_sole_reachability_disabling_the_source_removes_the_capability() -> None:
    """SC-008a — no residual path exists outside the MCP surface."""
    import session_watcher.server as mod

    public = {n for n in dir(mod) if not n.startswith("_")}
    # The service is importable (tests use it), but nothing registers a second
    # transport or a side-channel entry point.
    assert "main" in public
    assert not any(n.lower().startswith(("http_", "rest_", "grpc_")) for n in public)


def test_honest_absence_unobserved_fields_are_null_not_estimated() -> None:
    """T068 / FR-016 — absent is stated as absent, never filled with a guess."""
    svc = WatcherService(root=None)  # type: ignore[arg-type]
    svc.registry = SessionRegistry()
    svc.registry.replace_all(
        [
            Session(
                session_id="s1",
                project="p",
                state=SessionState.WORKING,
                started_at=NOW - timedelta(hours=1),
                last_activity_at=NOW - timedelta(minutes=1),
                last_message="",  # nothing observed
            )
        ],
        NOW,
    )
    row = svc.list_sessions(now=NOW)["sessions"][0]
    assert row["idle_reason"] is None, "idle_reason invented for a non-idle session"
    assert row["summary"] == "", "a summary was fabricated from an empty message"

    empty = SessionRegistry()
    payload = WatcherService.__new__(WatcherService)
    payload.registry = empty
    assert empty.staleness_seconds(NOW) == -1, "never-observed reported as 0s fresh"
