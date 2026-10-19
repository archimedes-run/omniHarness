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
