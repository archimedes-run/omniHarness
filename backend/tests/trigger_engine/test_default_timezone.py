"""Feature 006: a rule that names no zone runs in the user's zone
(America/New_York), not UTC. Through build_loop, the production builder, and a
full TriggerLoop.cycle(). A rule that names a zone keeps it."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.gateway.trigger_engine_wiring import build_loop
from app.trigger_engine.scheduler import DEFAULT_TIMEZONE

pytestmark = pytest.mark.asyncio

#: 13:30 UTC on a Tuesday in October: 09:30 in New York (EDT, UTC-4).
NOW = datetime(2026, 10, 20, 13, 30, tzinfo=UTC)


class _Gateway:
    def __init__(self):
        self.prompts = []

    def post(self, path, body):
        if path == "/api/threads":
            return {"thread_id": "t-1"}
        self.prompts.append(body["input"]["messages"][0]["content"])
        return {"messages": [{"type": "ai", "content": "ok"}]}

    def put(self, path, body):
        return {"sources": []}

    def get(self, path):
        return {"status": "idle"}


def _loop(tmp_path, match: dict):
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"quiet_hours": {"enabled": False}, "defaults": {"coalesce_window_seconds": 0}, "rules": [{"id": "nine", "type": "cron", "match": match, "prompt": "It is {scheduled_at}.", "destination": "quiet"}]}))
    cfg = SimpleNamespace(trigger_engine=SimpleNamespace(rules_path=str(rules), state_dir=str(tmp_path / "state"), actor="default", tick_seconds=30.0))
    gw = _Gateway()
    loop = build_loop(cfg, gateway_post=gw.post, gateway_put=gw.put, gateway_get=gw.get, fetch_sessions=lambda: {"observable": True, "sessions": []}, exchange_state=lambda tid: {"status": "idle"}, remote=None)
    loop.now = lambda: NOW
    return loop, gw


async def test_a_rule_without_a_zone_fires_at_its_clock_time_in_new_york(tmp_path) -> None:
    assert DEFAULT_TIMEZONE == "America/New_York"
    loop, gw = _loop(tmp_path, {"schedule": "0 9 * * *"})

    await loop.cycle()

    # 09:00 New York today has passed (it is 09:30 there); 09:00 UTC would be
    # 05:00 New York. The instant fired is the New York one.
    assert gw.prompts == ["It is 2026-10-20T09:00:00-04:00."]


async def test_a_rule_that_names_a_zone_keeps_it(tmp_path) -> None:
    loop, gw = _loop(tmp_path, {"schedule": "0 9 * * *", "timezone": "UTC"})

    await loop.cycle()

    assert gw.prompts == ["It is 2026-10-20T09:00:00+00:00."]
