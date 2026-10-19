"""GET /api/triggers/status — the engine's errors are readable (audit T-4).

Driven through the gateway's own `_start_trigger_engine`, so the handle the
route reads is the one the lifespan produces, including a FAILED one, which
the lifespan used to drop.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.app import _start_trigger_engine, _stop_trigger_engine
from app.gateway.routers import triggers
from app.trigger_engine.models import TriggerType

WATCHER_RULE = {"id": "blocked-session", "type": "watcher", "match": {"event": "waiting-on-user"}, "prompt": "{project}: {last_message}", "destination": "quiet"}
CALENDAR_RULE = {"id": "standup", "type": "calendar", "match": {"minutes_before": 10}, "prompt": "{summary} soon", "destination": "auto"}


@pytest.fixture(autouse=True)
def _no_ambient_extensions(tmp_path, monkeypatch):
    from omniharness.config.extensions_config import reset_extensions_config

    empty = tmp_path / "no_extensions.json"
    empty.write_text(json.dumps({"mcpServers": {}, "skills": {}}))
    monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", str(empty))
    reset_extensions_config()
    yield
    reset_extensions_config()


def _state(tmp_path: Path, rules: list[dict], *, enabled: bool = True) -> SimpleNamespace:
    from omniharness.runtime.runs.store.memory import MemoryRunStore

    rules_file = tmp_path / "rules.json"
    rules_file.write_text(json.dumps({"rules": rules}))
    config = SimpleNamespace(
        trigger_engine=SimpleNamespace(enabled=enabled, rules_path=str(rules_file), state_dir=str(tmp_path / "state"), actor="default", tick_seconds=30.0, remote=None),
        database=SimpleNamespace(backend="memory", postgres_url=""),
    )
    return SimpleNamespace(config=config, run_store=MemoryRunStore())


def _status(state) -> dict:
    app = make_authed_test_app()
    app.include_router(triggers.router)
    app.state.config = state.config
    app.state.trigger_engine = getattr(state, "trigger_engine", None)
    with TestClient(app) as client:
        resp = client.get("/api/triggers/status")
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_an_engine_that_refused_to_start_says_why(tmp_path) -> None:
    host = SimpleNamespace(state=_state(tmp_path, [CALENDAR_RULE]))

    host.state.trigger_engine = await _start_trigger_engine(host)

    status = await asyncio.to_thread(_status, host.state)
    assert status["role"] == "failed"
    assert "calendar feed" in status["error"], status


@pytest.mark.asyncio
async def test_a_running_engine_reports_its_rules_and_why_a_source_is_unreadable(tmp_path) -> None:
    host = SimpleNamespace(state=_state(tmp_path, [WATCHER_RULE]))
    host.state.trigger_engine = await _start_trigger_engine(host)
    try:
        # The engine's first cycle polls the watcher, which is not configured.
        watcher = host.state.trigger_engine.loop.runner.sources[TriggerType.WATCHER]
        for _ in range(100):
            if not watcher.reachable:
                break
            await asyncio.sleep(0.05)

        status = await asyncio.to_thread(_status, host.state)
    finally:
        await _stop_trigger_engine(host)

    assert status["role"] == "runner" and status["running"] is True, status
    assert [r["id"] for r in status["rules"]] == ["blocked-session"]
    assert "never been configured" in (status["sources"]["watcher"]["last_error"] or ""), status["sources"]


@pytest.mark.asyncio
async def test_a_disabled_engine_says_disabled(tmp_path) -> None:
    host = SimpleNamespace(state=_state(tmp_path, [WATCHER_RULE], enabled=False))
    host.state.trigger_engine = await _start_trigger_engine(host)

    assert (await asyncio.to_thread(_status, host.state))["role"] == "disabled"


def test_the_gateway_serves_the_status_route() -> None:
    """Registered on the app the gateway actually runs, not only on a test app."""
    from app.gateway.app import create_app

    paths = {getattr(r, "path", None) for r in create_app().routes}
    assert {"/api/triggers/status", "/api/triggers/rules", "/api/triggers/firings"} <= paths
