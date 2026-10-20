"""T061-T063 — the sessions surface's four conditions (Feature 004, US3).

Driven through GET /api/sessions against the REAL watcher server over SSE.
The four conditions:

  live            the watcher answers and its heartbeat is fresh
  stale           the watcher answers; its data is old, and says how old
  never-observed  the watcher answers; it has never seen anything
  unreachable     the watcher is STOPPED — a real refused connection, not a
                  mocked exception (T063)

`reachable` is transport and `observability` is the watcher's own report; the
unreachable case has no `sessions` at all, not an empty list (T062, SC-006).
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests/, for the shared auth helper
from _router_auth_helpers import make_authed_test_app  # noqa: E402

SESSION = "sess-waiting"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _write_session(root: Path) -> None:
    now = datetime.now(UTC)
    base = {"sessionId": SESSION, "session_id": SESSION, "cwd": "/Users/dev/projects/darcy-repo", "gitBranch": "main", "isSidechain": False, "version": "2.0.0"}
    records = [
        {**base, "type": "user", "uuid": "u1", "timestamp": (now - timedelta(minutes=3)).isoformat(), "message": {"role": "user", "content": [{"type": "text", "text": "fix it"}]}},
        {
            **base,
            "type": "assistant",
            "uuid": "u2",
            "timestamp": (now - timedelta(minutes=2)).isoformat(),
            "message": {"role": "assistant", "stop_reason": "end_turn", "content": [{"type": "text", "text": "Pin the version or rewrite the fixture?"}]},
        },
    ]
    (root / "proj").mkdir(parents=True)
    (root / "proj" / f"{SESSION}.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")


def _serve_watcher(service, port):
    import uvicorn
    from session_watcher.server import build_app

    server = uvicorn.Server(uvicorn.Config(build_app(service), host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.02)
    return server


@pytest.fixture
def point_at(tmp_path, monkeypatch):
    from omniharness.config.extensions_config import reset_extensions_config

    def _point(port: int) -> None:
        ext = tmp_path / "ext.json"
        ext.write_text(json.dumps({"mcpServers": {"session-watcher": {"enabled": True, "type": "sse", "url": f"http://127.0.0.1:{port}/sse"}}, "skills": {}}))
        monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", str(ext))
        reset_extensions_config()

    yield _point
    reset_extensions_config()


def _get() -> dict:
    from app.gateway.routers import sessions

    app = make_authed_test_app()
    app.include_router(sessions.router)
    with TestClient(app) as client:
        resp = client.get("/api/sessions")
    assert resp.status_code == 200, resp.text
    return resp.json()


class _Frozen:
    """A WatcherService whose refresh does nothing, so the test owns the
    heartbeat. The SSE server, the tool handler and the envelope are real."""

    @staticmethod
    def make(root: Path, heartbeat_age: timedelta | None):
        from session_watcher.server import WatcherService

        service = WatcherService(root=root)
        if heartbeat_age is not None:
            service.refresh()
            service.registry.last_heartbeat_at = datetime.now(UTC) - heartbeat_age
        service.refresh = lambda **_: None  # type: ignore[method-assign]
        return service


def test_live(tmp_path, point_at) -> None:
    from session_watcher.server import WatcherService

    _write_session(tmp_path / "root")
    port = _free_port()
    server = _serve_watcher(WatcherService(root=tmp_path / "root"), port)
    point_at(port)
    try:
        body = _get()
    finally:
        server.should_exit = True

    assert body["reachable"] is True and body["observability"] == "live"
    [row] = body["sessions"]
    assert row["display_state"] == "waiting-on-user" and row["epistemic"] == "inferred"


def test_stale_says_how_stale(tmp_path, point_at) -> None:
    _write_session(tmp_path / "root")
    port = _free_port()
    server = _serve_watcher(_Frozen.make(tmp_path / "root", heartbeat_age=timedelta(hours=2)), port)
    point_at(port)
    try:
        body = _get()
    finally:
        server.should_exit = True

    assert body["reachable"] is True and body["observability"] == "stale"
    assert body["staleness_seconds"] >= 7000
    assert body["sessions"], "stale data is still shown, labelled as last-known"


def test_never_observed_is_not_unreachable(tmp_path, point_at) -> None:
    (tmp_path / "root").mkdir()
    port = _free_port()
    server = _serve_watcher(_Frozen.make(tmp_path / "root", heartbeat_age=None), port)
    point_at(port)
    try:
        body = _get()
    finally:
        server.should_exit = True

    assert body["reachable"] is True and body["observability"] == "never-observed"


def test_a_stopped_watcher_is_unreachable_and_has_no_session_list(tmp_path, point_at) -> None:
    """A real stopped server: started, then shut down, then asked."""
    from session_watcher.server import WatcherService

    (tmp_path / "root").mkdir()
    port = _free_port()
    server = _serve_watcher(WatcherService(root=tmp_path / "root"), port)
    point_at(port)
    server.should_exit = True
    deadline = time.monotonic() + 5
    while server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    time.sleep(0.2)

    body = _get()

    assert body["reachable"] is False and body["unreachable_kind"] == "unreachable"
    assert body["sessions"] is None, "an unreachable watcher rendered as an empty list (SC-006)"
    assert body["observability"] is None, "transport failure dressed up as a watcher state (T062)"


def test_the_gateway_serves_the_route() -> None:
    from app.gateway.app import create_app

    assert "/api/sessions" in {getattr(r, "path", None) for r in create_app().routes}


# --- a slow watcher answers fast, with what it last said (Phase 2.5) -----------


@pytest.fixture
def fresh_cache(monkeypatch):
    from app.gateway.routers import sessions

    monkeypatch.setattr(sessions, "_last_good", None)


def _black_hole(port: int):
    """Accepts connections and never answers: a watcher too busy to reply."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(16)
    held: list[socket.socket] = []
    stop = threading.Event()

    def accept() -> None:
        srv.settimeout(0.1)
        while not stop.is_set():
            try:
                held.append(srv.accept()[0])
            except OSError:
                continue

    threading.Thread(target=accept, daemon=True).start()

    def close() -> None:
        stop.set()
        for c in held:
            c.close()
        srv.close()

    return close


def test_a_silent_watcher_costs_about_two_seconds_not_ten(tmp_path, point_at, fresh_cache) -> None:
    port = _free_port()
    close = _black_hole(port)
    point_at(port)
    started = time.monotonic()
    try:
        body = _get()
    finally:
        close()

    assert time.monotonic() - started < 4, "the page waited for the watcher's old 10 s timeout"
    assert body["reachable"] is False and body["sessions"] is None, "nothing was ever seen, so nothing may be shown"
    assert body["last_known_age_seconds"] is None


def test_a_silent_watcher_shows_the_last_answer_labelled_with_its_age(tmp_path, point_at, fresh_cache) -> None:
    from session_watcher.server import WatcherService

    _write_session(tmp_path / "root")
    port = _free_port()
    server = _serve_watcher(WatcherService(root=tmp_path / "root"), port)
    point_at(port)
    try:
        assert _get()["reachable"] is True  # the last good answer
    finally:
        server.should_exit = True
    time.sleep(0.5)

    dead = _free_port()
    close = _black_hole(dead)
    point_at(dead)
    try:
        body = _get()
    finally:
        close()

    assert body["reachable"] is False, "a stale answer must not claim the watcher answered"
    assert body["unreachable_detail"], "and must say why it is stale"
    assert body["last_known_age_seconds"] is not None and body["last_known_age_seconds"] >= 0
    assert [r["display_state"] for r in body["sessions"]] == ["waiting-on-user"]


def test_claude_and_codex_sessions_reach_the_page_together(tmp_path, point_at) -> None:
    """Feature 005 US3, end to end: the watcher built as main() builds it
    (build_service, both roots), served over real SSE, read by the gateway
    route the Coding sessions page calls."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "session_watcher"))
    from codex_records import event, meta, plan_call, plan_ok, write
    from session_watcher.server import build_service

    _write_session(tmp_path / "claude")
    write(tmp_path / "codex", "2026/10/19", "codex-1", [meta(0, "codex-1"), plan_call(1, "c1", [("Parse", "completed"), ("Ship", "pending")]), plan_ok(1.1, "c1"), event(2, "task_started", turn_id="t")])
    port = _free_port()
    server = _serve_watcher(build_service(tmp_path / "claude", tmp_path / "codex"), port)
    point_at(port)
    try:
        body = _get()
    finally:
        server.should_exit = True

    by_agent = {row["agent"]: row for row in body["sessions"]}
    assert set(by_agent) == {"claude", "codex"}
    assert by_agent["codex"]["agent_label"] == "Codex"
    assert by_agent["codex"]["todos"] == [{"title": "Parse", "status": "completed"}, {"title": "Ship", "status": "pending"}]
    assert by_agent["claude"]["todos"] is None
    assert {a["agent"]: a["readable"] for a in body["agents"]} == {"claude": True, "codex": True}
