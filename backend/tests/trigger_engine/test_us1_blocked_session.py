"""T058-T060 — US1: a blocked session reaches your phone, once (SC-001, SC-002)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.trigger_engine.audit import AuditLog
from app.trigger_engine.compose import compose_proactive, render_prompt
from app.trigger_engine.config import EngineConfig
from app.trigger_engine.destinations.base import DestinationRegistry, QuietDestination
from app.trigger_engine.fingerprint import FingerprintStore
from app.trigger_engine.injector import TurnInjector
from app.trigger_engine.models import Destination, Rule, TriggerType
from app.trigger_engine.politeness.release import Releaser
from app.trigger_engine.presence import PresenceSignal
from app.trigger_engine.runner import RuleRunner
from app.trigger_engine.sources.watcher import WatcherSource
from app.trigger_engine.threads import RuleThreadMap

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
pytestmark = pytest.mark.asyncio

RULE = Rule(
    id="blocked-session",
    type=TriggerType.WATCHER,
    match={"event": "waiting-on-user"},
    prompt="The session in {project} appears to be waiting on you. It last said: {last_message}",
    destination=Destination.QUIET,
)


def _payload(summary="Should I pin the version or rewrite the fixture?", state="waiting-on-user"):
    return {
        "observable": True,
        "observability": "live",
        "sessions": [
            {
                "session_id": "sess-1",
                "project": "darcy-repo@main",
                "state": state,
                "idle_reason": None,
                "summary": summary,
                "quiet_seconds": 480,
            }
        ],
    }


def _runner(tmp_path, payload_fn, gateway=None):
    gw = gateway or _Gateway()
    dest = QuietDestination()
    audit = AuditLog(path=tmp_path / "audit.jsonl", actor="default")
    return (
        RuleRunner(
            sources={TriggerType.WATCHER: WatcherSource(fetch_sessions=payload_fn)},
            fingerprints=FingerprintStore(path=tmp_path / "fp.json"),
            threads=RuleThreadMap(path=tmp_path / "th.json", create_thread=lambda r: f"thread-{r}"),
            injector=TurnInjector(post=gw.post, put=gw.put, get=gw.get),
            releaser=Releaser(redact=lambda t: (t, True), still_true=lambda f: True, audit=lambda f, n: audit.record(f, n)),
            registry=DestinationRegistry(remote=dest, quiet=dest),
            presence=PresenceSignal(),
            audit=audit,
            config=EngineConfig(),
        ),
        dest,
        audit,
        gw,
    )


class _Gateway:
    def __init__(self, reply="It's asking whether to pin the dependency or rewrite the fixture."):
        self.reply, self.runs = reply, []

    def post(self, path, body):
        if path == "/api/threads":
            return {"thread_id": "t-1"}
        self.runs.append(body)
        return {"messages": [{"type": "ai", "content": self.reply}]}

    def put(self, path, body):
        return {"sources": body["sources"]}

    def get(self, path):
        return {}


async def test_a_blocked_session_delivers_one_message(tmp_path) -> None:
    """SC-001."""
    runner, dest, audit, _ = _runner(tmp_path, _payload)
    fired = await runner.run(RULE, NOW)
    assert len(fired) == 1
    assert len(dest.delivered) == 1
    assert "darcy-repo@main" in dest.delivered[0]
    assert audit.entries()[0]["outcome"] == "delivered"


async def test_it_does_not_deliver_again_while_still_blocked(tmp_path) -> None:
    """SC-002 — the failure that gets a proactive feature muted."""
    runner, dest, _, _ = _runner(tmp_path, _payload)
    for _ in range(25):
        await runner.run(RULE, NOW)
    assert len(dest.delivered) == 1, f"{len(dest.delivered)} messages for one unchanged block"


async def test_a_different_question_delivers_again(tmp_path) -> None:
    """SC-002a — answered, then blocked again on something else."""
    state = {"q": "Roll it back?"}
    runner, dest, _, _ = _runner(tmp_path, lambda: _payload(summary=state["q"]))
    await runner.run(RULE, NOW)
    await runner.run(RULE, NOW)
    state["q"] = "Pin the version instead?"
    await runner.run(RULE, NOW)
    assert len(dest.delivered) == 2


async def test_a_non_matching_state_does_not_fire(tmp_path) -> None:
    """Story 1 scenario 4."""
    runner, dest, _, _ = _runner(tmp_path, lambda: _payload(state="working"))
    assert await runner.run(RULE, NOW) == []
    assert dest.delivered == []


async def test_an_unreachable_watcher_fires_nothing_and_is_not_an_error(tmp_path) -> None:
    """FR-029 — not firing is correct; crashing or claiming silence is not."""

    def boom():
        raise ConnectionError("watcher down")

    runner, dest, _, _ = _runner(tmp_path, boom)
    assert await runner.run(RULE, NOW) == []
    assert dest.delivered == []


async def test_a_failed_injection_is_recorded_not_swallowed(tmp_path) -> None:
    class Broken(_Gateway):
        def post(self, path, body):
            if path == "/api/threads":
                return {"thread_id": "t-1"}
            raise RuntimeError("gateway refused the run")

    runner, dest, audit, _ = _runner(tmp_path, _payload, gateway=Broken())
    await runner.run(RULE, NOW)
    entries = audit.entries()
    assert entries and entries[0]["outcome"] == "failed"
    assert "gateway refused" in entries[0]["reason"]


async def test_the_fingerprint_is_recorded_before_delivery(tmp_path) -> None:
    """A crash between injection and delivery must not re-fire the event.

    A missed message is recoverable; a repeat is what gets the feature muted.
    """

    class FailingDest(QuietDestination):
        def deliver(self, text):
            raise RuntimeError("telegram down")

    runner, _, _, _ = _runner(tmp_path, _payload)
    runner.registry = DestinationRegistry(remote=FailingDest(), quiet=FailingDest())
    with pytest.raises(RuntimeError):
        await runner.run(RULE, NOW)
    # The event is remembered, so the next cycle does not send a duplicate.
    runner.registry = DestinationRegistry(remote=QuietDestination(), quiet=QuietDestination())
    await runner.run(RULE, NOW)
    assert runner.registry.quiet.delivered == []


# --- wording -----------------------------------------------------------------


def test_the_prompt_interpolates_event_fields() -> None:
    from app.trigger_engine.models import TriggerEvent

    ev = TriggerEvent(type=TriggerType.WATCHER, event_id="s", at=NOW, fields={"project": "darcy-repo", "last_message": "Roll back?"})
    assert render_prompt(RULE, ev) == ("The session in darcy-repo appears to be waiting on you. It last said: Roll back?")


def test_a_missing_field_is_visible_not_silent() -> None:
    from app.trigger_engine.models import TriggerEvent

    ev = TriggerEvent(type=TriggerType.WATCHER, event_id="s", at=NOW, fields={"project": "p"})
    out = render_prompt(RULE, ev)
    assert "<last_message unavailable>" in out


def test_the_delivered_message_leads_with_the_hedge() -> None:
    """FR-016a — waiting-on-user is INFERRED, so it must sound inferred."""
    from app.trigger_engine.models import TriggerEvent

    ev = TriggerEvent(type=TriggerType.WATCHER, event_id="s", at=NOW, fields={"project": "darcy-repo@main", "state": "waiting-on-user"})
    msg = compose_proactive(RULE, ev, "It wants to know whether to pin the dependency.")
    assert msg.startswith("darcy-repo@main looks like it's waiting on you")
    for forbidden in ("It is waiting for your input", "is waiting for your input"):
        assert forbidden not in msg


def test_an_observed_failure_is_stated_without_a_hedge() -> None:
    """Hedging a fact is its own dishonesty."""
    from app.trigger_engine.models import TriggerEvent

    ev = TriggerEvent(type=TriggerType.WATCHER, event_id="s", at=NOW, fields={"project": "atlas", "state": "failed"})
    msg = compose_proactive(RULE, ev, "The build failed on the type check.")
    assert msg.startswith("atlas failed.")
    assert "looks like" not in msg
