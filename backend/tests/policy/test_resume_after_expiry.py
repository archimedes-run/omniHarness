"""Owner decision M2 (spec 009 review): one resume once no lead card of the
turn is open, whether the last ones were answered or EXPIRED, so the lead is
never stranded. The resumed lead is told which cards were answered and which
expired (and did not run). Nothing runs twice; never two resumes.
"""

from __future__ import annotations

import asyncio
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_web_research as wr  # noqa: E402
from test_web_research import LEAD_SAW, LEAD_SCRIPT, SENT, _private_turn_with_fetches, _thread, gateway  # noqa: E402, F401

URLS = ["https://food1.example/philly", "https://food2.example/philly"]
#: The loop's own sleep, before any fixture runs.
_REAL_SLEEP = asyncio.sleep


def _store():
    from app.policy.registration import build
    from omniharness.config import get_app_config

    return build(get_app_config()).pending


def _expire(action_id: str) -> None:
    store = _store()
    action = store.get(action_id)
    action.expires_at = datetime.now(UTC) - timedelta(seconds=5)
    store.save(action)


def _sweep(gateway) -> list[str]:  # noqa: F811
    from app.gateway.resume import resume_expired

    app = gateway.client.app
    return gateway.client.portal.call(resume_expired, app)


def _settle(gateway, thread_id: str) -> None:  # noqa: F811
    deadline = time.time() + 20
    while time.time() < deadline:
        runs = gateway.client.get(f"/api/threads/{thread_id}/runs").json()
        if not any(r["status"] in ("pending", "running") for r in runs):
            return
        time.sleep(0.05)
    raise AssertionError("runs did not settle")


def _run_count(gateway, thread_id: str) -> int:  # noqa: F811
    return len(gateway.client.get(f"/api/threads/{thread_id}/runs").json())


def test_the_gateway_keeps_its_own_sweep_out_of_the_tests_way(gateway):  # noqa: F811
    """These tests make the sweeps themselves. The gateway's own sweep pauses
    a minute between passes; with the loop's sleep sped up for the whole app
    (the fixture once did, for the task tool's poll) it swept every 50 ms and
    took the resume a test was waiting for (issue #180)."""
    from app.gateway.resume import SWEEP_INTERVAL_SECONDS

    assert asyncio.sleep is _REAL_SLEEP, "the fixture sped up every sleep in the gateway, the expiry sweep's pause among them"
    assert SWEEP_INTERVAL_SECONDS >= 30


def test_answered_then_the_rest_expire_resumes_once_and_reports_the_expired_as_not_run(gateway):  # noqa: F811
    thread_id = _thread(gateway)
    cards = _private_turn_with_fetches(gateway, thread_id, URLS)
    before = _run_count(gateway, thread_id)
    first = gateway.client.post(f"/api/confirmations/{cards[0]['id']}/confirm", json={}).json()
    assert first["outcome"] == "executed" and not first["detail"].get("resume_run_id"), "resumed while a card was open"
    _expire(cards[1]["id"])
    LEAD_SCRIPT[:] = [AIMessage(content="One place found; the other lookup expired.")]
    started = _sweep(gateway)
    assert len(started) == 1, started
    assert wr._wait_run(gateway, thread_id, started[0]) == "success"
    seen = LEAD_SAW[-1]
    tools = [m[2] for m in seen if m[0] == "tool"]
    assert any("observed data" in t for t in tools), seen
    assert any("expired, so it did not run" in t for t in tools), seen
    assert SENT == [f"fetch:{URLS[0]}"], f"an expired call ran, or a call ran twice: {SENT}"
    # A second sweep finds nothing left to resume.
    assert _sweep(gateway) == []
    _settle(gateway, thread_id)
    assert _run_count(gateway, thread_id) == before + 1


def test_a_turn_whose_cards_all_expired_still_resumes_once(gateway):  # noqa: F811
    thread_id = _thread(gateway)
    cards = _private_turn_with_fetches(gateway, thread_id, URLS)
    for card in cards:
        _expire(card["id"])
    LEAD_SCRIPT[:] = [AIMessage(content="Nothing was looked up: the confirmations expired.")]
    started = _sweep(gateway)
    assert len(started) == 1
    assert wr._wait_run(gateway, thread_id, started[0]) == "success"
    assert SENT == []
    assert len([m for m in LEAD_SAW[-1] if m[0] == "tool" and "expired, so it did not run" in m[2]]) == 2


def test_an_expiry_racing_the_last_answer_resumes_once(gateway):  # noqa: F811
    thread_id = _thread(gateway)
    cards = _private_turn_with_fetches(gateway, thread_id, [*URLS, "https://food3.example/philly"])
    gateway.client.post(f"/api/confirmations/{cards[0]['id']}/confirm", json={})
    _expire(cards[2]["id"])
    before = _run_count(gateway, thread_id)
    LEAD_SCRIPT[:] = [AIMessage(content="Done.")]

    def answer():
        return gateway.client.post(f"/api/confirmations/{cards[1]['id']}/confirm", json={}).json()["detail"].get("resume_run_id")

    with ThreadPoolExecutor(3) as pool:
        futures = [pool.submit(answer), pool.submit(_sweep, gateway), pool.submit(_sweep, gateway)]
        results = [f.result() for f in futures]
    # The loser of a race gives its locks back; a later sweep may still find
    # the turn unresumed, never resumed twice.
    for _ in range(3):
        _settle(gateway, thread_id)
        if _run_count(gateway, thread_id) > before:
            break
        _sweep(gateway)
    _settle(gateway, thread_id)
    assert _run_count(gateway, thread_id) == before + 1, f"resumes: {results}"
    assert sorted(SENT) == sorted(f"fetch:{u}" for u in URLS), SENT


def test_a_turn_part_of_which_another_caller_holds_is_not_resumed_in_part(gateway):  # noqa: F811
    """Deterministic form of the race: another caller (an answer, another
    worker's sweep) holds one card of the turn. This caller resumes nothing
    and keeps nothing; once the other lets go, one resume follows."""
    thread_id = _thread(gateway)
    cards = _private_turn_with_fetches(gateway, thread_id, URLS)
    gateway.client.post(f"/api/confirmations/{cards[0]['id']}/confirm", json={})
    _expire(cards[1]["id"])
    store = _store()
    assert store.take_continue(cards[1]["id"])  # the other caller
    before = _run_count(gateway, thread_id)
    assert _sweep(gateway) == []
    assert store.take_continue(cards[0]["id"]), "a card was kept by the caller that resumed nothing"
    store.release_continue(cards[0]["id"])
    store.release_continue(cards[1]["id"])
    LEAD_SCRIPT[:] = [AIMessage(content="Done.")]
    # A pass that finds the chat still busy looks again later; one resume follows.
    started: list[str] = []
    for _ in range(20):
        _settle(gateway, thread_id)
        started = _sweep(gateway)
        if started:
            break
        time.sleep(0.2)
    [run_id] = started
    assert wr._wait_run(gateway, thread_id, run_id) == "success"
    assert _sweep(gateway) == []
    assert _run_count(gateway, thread_id) == before + 1


# -- at most once, never against the person's wishes (review H2) ------------


def test_a_failed_resume_is_not_retried(gateway, monkeypatch):  # noqa: F811
    import app.gateway.services as services

    thread_id = _thread(gateway)
    cards = _private_turn_with_fetches(gateway, thread_id, URLS[:1])
    _expire(cards[0]["id"])
    attempts = []

    async def broken(*args, **kwargs):
        attempts.append(1)
        raise RuntimeError("the run could not start")

    monkeypatch.setattr(services, "start_run", broken)
    assert _sweep(gateway) == []
    assert _sweep(gateway) == []
    assert len(attempts) == 1, "a failed resume was tried again"


def test_two_sweeps_at_once_attempt_a_failed_resume_once(gateway, monkeypatch):  # noqa: F811
    """Every worker sweeps. Two sweeps that both find the turn unattempted
    (both past the marker check before either records its attempt) still
    make ONE attempt: a failed resume is not tried again by the other."""
    import app.gateway.resume as resume
    import app.gateway.services as services

    thread_id = _thread(gateway)
    cards = _private_turn_with_fetches(gateway, thread_id, URLS[:1])
    _expire(cards[0]["id"])
    attempts = []

    async def broken(*args, **kwargs):
        attempts.append(1)
        raise RuntimeError("the run could not start")

    monkeypatch.setattr(services, "start_run", broken)
    # Hold each sweep after its marker check until both have passed it.
    real_why_not = resume._why_not
    arrived: list[int] = []
    both = asyncio.Event()

    async def held(*args, **kwargs):
        arrived.append(1)
        if len(arrived) == 2:
            both.set()
        await asyncio.wait_for(both.wait(), timeout=10)
        return await real_why_not(*args, **kwargs)

    monkeypatch.setattr(resume, "_why_not", held)

    async def two_sweeps():
        return await asyncio.gather(resume.resume_expired(gateway.client.app), resume.resume_expired(gateway.client.app))

    assert gateway.client.portal.call(two_sweeps) == [[], []]
    assert len(arrived) == 2, "the sweeps did not both pass the marker check; this test proves nothing"
    assert len(attempts) == 1, f"a failed resume was attempted {len(attempts)} times by two sweeps"


def test_a_task_the_person_stopped_is_not_restarted(gateway, monkeypatch):  # noqa: F811
    from types import SimpleNamespace

    from omniharness.runtime.runs.manager import RunManager

    thread_id = _thread(gateway)
    cards = _private_turn_with_fetches(gateway, thread_id, URLS[:1])
    real = RunManager.list_history

    async def stopped_last(self, tid, **kwargs):
        runs = await real(self, tid, **kwargs)
        return [*runs, SimpleNamespace(status=SimpleNamespace(value="interrupted"))] if tid == thread_id else runs

    before = _run_count(gateway, thread_id)
    _expire(cards[0]["id"])
    monkeypatch.setattr(RunManager, "list_history", stopped_last)
    assert _sweep(gateway) == []
    monkeypatch.setattr(RunManager, "list_history", real)
    assert _sweep(gateway) == [], "retried after the person stopped the task"
    assert _run_count(gateway, thread_id) == before


def test_no_resume_once_the_person_has_moved_on(gateway):  # noqa: F811
    thread_id = _thread(gateway)
    cards = _private_turn_with_fetches(gateway, thread_id, URLS[:1])
    wr._say(gateway, thread_id, "never mind, what's the weather?", [AIMessage(content="Sunny.")])
    before = _run_count(gateway, thread_id)
    _expire(cards[0]["id"])
    assert _sweep(gateway) == []
    assert _run_count(gateway, thread_id) == before
    assert SENT == []


def test_a_deleted_chat_is_never_resumed(gateway):  # noqa: F811
    thread_id = _thread(gateway)
    cards = _private_turn_with_fetches(gateway, thread_id, URLS[:1])
    assert gateway.client.delete(f"/api/threads/{thread_id}").status_code == 200
    _expire(cards[0]["id"])
    assert _sweep(gateway) == []


def test_a_card_being_executed_is_not_expired(gateway):  # noqa: F811
    from app.policy.models import Outcome

    thread_id = _thread(gateway)
    cards = _private_turn_with_fetches(gateway, thread_id, URLS[:1])
    store = _store()
    assert store.claim(cards[0]["id"], "a confirm in flight") is not None
    _expire(cards[0]["id"])
    store.expire_due(datetime.now(UTC))
    assert store.get(cards[0]["id"]).outcome is None, "a claimed card was marked expired"
    assert store.get(cards[0]["id"]).outcome != Outcome.EXPIRED
