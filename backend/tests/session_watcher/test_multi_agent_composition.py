"""Claude Code and Codex sessions together, through the production wiring.

FR-071 (Article XI): the service is built by `build_service`, the function
`main()` uses, and queried through the real MCP tool handler. The structural
difference this defends against: a hand-built Discovery with one adapter,
which is how every watcher test was written before Feature 005 and why the
single-adapter wiring in server.py was never questioned.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta

import codex_records
import mcp.types as types
from codex_records import T0, event, meta, plan_call, plan_ok, write
from session_watcher.server import build_server, build_service

NOW = T0 + timedelta(minutes=10)


def _claude(root, sid: str) -> None:
    folder = root / "-Users-dev-projects-omniHarness"
    folder.mkdir(parents=True)
    rec = {"type": "user", "sessionId": sid, "timestamp": (T0 + timedelta(minutes=1)).isoformat(), "cwd": "/Users/dev/projects/omniHarness", "message": {"role": "user", "content": "go"}}
    (folder / f"{sid}.jsonl").write_text(json.dumps(rec) + "\n")


def _call(server, name: str, args: dict) -> dict:
    req = types.CallToolRequest(method="tools/call", params=types.CallToolRequestParams(name=name, arguments=args))
    res = asyncio.run(server.request_handlers[types.CallToolRequest](req))
    return json.loads(res.root.content[0].text)


def test_both_agents_appear_in_the_same_tool_labelled_with_progress(tmp_path, monkeypatch) -> None:
    # The tool lists against the real clock, so the records must be recent:
    # pinned to 2026-10-19 this test began failing once that day had passed.
    t0 = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)
    monkeypatch.setattr(codex_records, "T0", t0)
    monkeypatch.setattr(sys.modules[__name__], "T0", t0)
    _claude(tmp_path / "claude", "claude-1")
    write(tmp_path / "codex", t0.strftime("%Y/%m/%d"), "codex-1", [meta(0, "codex-1"), plan_call(1, "c1", [("Parse", "completed"), ("Test", "in_progress"), ("Ship", "pending")]), plan_ok(1.1, "c1"), event(2, "task_started", turn_id="t")])
    service = build_service(tmp_path / "claude", tmp_path / "codex")
    service.refresh(now=t0 + timedelta(minutes=10))

    payload = _call(build_server(service), "list_coding_sessions", {})

    by_agent = {s["agent"]: s for s in payload["sessions"]}
    assert set(by_agent) == {"claude", "codex"}
    assert by_agent["codex"]["todos"] == [{"title": "Parse", "status": "completed"}, {"title": "Test", "status": "in_progress"}, {"title": "Ship", "status": "pending"}]
    assert by_agent["claude"]["todos"] is None
    assert "beta-site (Codex)" in payload["reply"] and "omniHarness (Claude Code)" in payload["reply"]
    assert "Plan 1/3 done." in payload["reply"]
    assert [a["agent"] for a in payload["agents"]] == ["claude", "codex"] and all(a["readable"] for a in payload["agents"])


def test_a_configured_but_unmounted_codex_root_is_cant_tell_not_none(tmp_path) -> None:
    (tmp_path / "claude").mkdir()
    service = build_service(tmp_path / "claude", tmp_path / "not-mounted" / "sessions")
    service.refresh(now=NOW)
    payload = _call(build_server(service), "list_coding_sessions", {})
    codex = next(a for a in payload["agents"] if a["agent"] == "codex")
    assert codex["readable"] is False
    assert "I can't read Codex sessions" in payload["reply"]


def test_without_a_codex_root_codex_is_not_mentioned(tmp_path) -> None:
    (tmp_path / "claude").mkdir()
    service = build_service(tmp_path / "claude", None)
    service.refresh(now=NOW)
    payload = _call(build_server(service), "list_coding_sessions", {})
    assert [a["agent"] for a in payload["agents"]] == ["claude"]
    assert payload["reply"] == "No coding sessions are running."


def test_a_codex_home_with_no_sessions_folder_is_none_not_cant_tell(tmp_path) -> None:
    """Codex installed (or the mount created empty) but never run: nothing to
    report, and nothing to apologise for."""
    (tmp_path / "claude").mkdir()
    (tmp_path / "codex-home").mkdir()
    service = build_service(tmp_path / "claude", tmp_path / "codex-home" / "sessions")
    service.refresh(now=NOW)
    payload = _call(build_server(service), "list_coding_sessions", {})
    assert payload["reply"] == "No coding sessions are running."
