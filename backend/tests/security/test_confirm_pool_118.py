# ruff: noqa: F401, F811
"""#118: the confirmation pool is only for a turn that answers a plan, and a
typed "yes" takes a per-user slot like the card. Real HTTP, auth ON.

Reuses `gateway` (create_app()+lifespan, real runs, the real task tool and
SubagentExecutor, fake models) from tests/policy/test_delegated_confirmation.py,
and the real _CONFIRM_POOL and _SLOTS.

1. Every person's own turn used to go through _CONFIRM_POOL (8 workers), plan
   or not, so with 8 confirmed delegations running an ordinary new chat turn
   waited for a worker (about 6 s in the review, until one finished).
2. A typed "yes" took no slot from _SLOTS, so one user could run more than
   CONFIRMS_PER_USER confirmed calls, and a card holding a slot could queue
   behind typed jobs.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "policy"))
import test_delegated_confirmation as dc  # noqa: E402
from test_delegated_confirmation import (  # noqa: E402
    DELEGATE,
    SUB_SCRIPT,
    _pending,
    _say,
    _stored,
    _thread,
    gateway,
)


def _delegations(gateway, n: int) -> list[tuple[str, dict]]:
    """n chats, each with one pending delegation the user asked for."""
    made = []
    for i in range(n):
        thread_id = _thread(gateway)
        _say(gateway, thread_id, "ask a helper to wipe the nightly backup", [AIMessage(content="", tool_calls=[dict(DELEGATE, id=f"d{i}")]), AIMessage(content="Delegation waiting.")])
        [action] = [a for a in _pending(gateway, "task") if a["thread_id"] == thread_id]
        made.append((thread_id, action))
    return made


def _hold_subagents(monkeypatch) -> tuple[threading.Event, list[int]]:
    """Every subagent model call waits for `release`; `entered` counts them."""
    release, entered = threading.Event(), []
    real = dc.SeeingFake._generate

    def held(self, messages, stop=None, run_manager=None, **kw):
        entered.append(1)
        release.wait(30)
        return real(self, messages, stop=stop, run_manager=run_manager, **kw)

    monkeypatch.setattr(dc.SeeingFake, "_generate", held)
    return release, entered


def _card_confirm_in_background(gateway, actions: list[dict]) -> tuple[list[threading.Thread], dict]:
    results: dict[str, str] = {}

    def card(action_id: str) -> None:
        results[action_id] = gateway.client.post(f"/api/confirmations/{action_id}/confirm", json={}).json().get("outcome")

    threads = [threading.Thread(target=card, args=(a["id"],)) for a in actions]
    for t in threads:
        t.start()
    return threads, results


def _slots_taken() -> int:
    from app.gateway.routers import confirmations as cf

    with cf._SLOTS._lock:
        return sum(cf._SLOTS._by_user.values())


def _wait_for(predicate, seconds: float = 30) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def _drain(release: threading.Event, threads: list[threading.Thread]) -> None:
    release.set()
    for t in threads:
        t.join(60)
    assert _wait_for(lambda: _slots_taken() == 0), "confirmation slots were not given back"


def test_full_pool_does_not_delay_an_ordinary_chat_turn(gateway, monkeypatch):
    from app.gateway.routers import confirmations as cf

    # One person may fill the whole pool by card here, so 8 card confirmations
    # in one test hold every slot and every pool worker.
    monkeypatch.setattr(cf, "CONFIRMS_PER_USER", cf.CONFIRM_WORKERS)
    made = _delegations(gateway, cf.CONFIRM_WORKERS)
    other = _thread(gateway)

    release, entered = _hold_subagents(monkeypatch)
    SUB_SCRIPT[:] = [AIMessage(content="sub done")]
    cards, results = _card_confirm_in_background(gateway, [a for _, a in made])
    box: dict = {}
    try:
        assert _wait_for(lambda: _slots_taken() == cf.CONFIRM_WORKERS), f"the card confirmations did not fill the slots: {_slots_taken()}"
        # The subagents are inside their confirmed delegations (the executor
        # runs at most 3 at once; the rest wait inside their pool threads).
        assert _wait_for(lambda: len(entered) >= 3), "the confirmed delegations never started"
        assert cf._CONFIRM_POOL._work_queue.qsize() == 0

        dc.LEAD_SCRIPT[:] = [AIMessage(content="hi there")]

        def chat() -> None:
            t0 = time.time()
            r = gateway.client.post(f"/api/threads/{other}/runs/wait", json={"assistant_id": "lead_agent", "input": {"messages": [{"role": "user", "content": "hello, what time is it?"}]}})
            box["status"], box["secs"], box["body"] = r.status_code, time.time() - t0, r.json()

        t = threading.Thread(target=chat)
        t.start()
        t.join(5)
        blocked = t.is_alive()
        assert _slots_taken() == cf.CONFIRM_WORKERS, "the pool was freed during the measurement"
    finally:
        _drain(release, cards)
    t.join(30)
    assert not blocked, "an ordinary chat turn waited for the confirmation pool"
    assert box["status"] == 200, box
    assert box["secs"] < 1.5, f"an ordinary chat turn took {box['secs']:.2f}s while the confirmation pool was full"
    assert "hi there" in str(box["body"].get("messages", [])[-1].get("content")), box
    assert set(results.values()) == {"executed"}, results


def test_typed_yes_with_no_free_slot_is_busy_and_runs_nothing(gateway, monkeypatch):
    from app.gateway.routers import confirmations as cf

    held_by_card = _delegations(gateway, cf.CONFIRMS_PER_USER)
    [(typed_thread, typed)] = _delegations(gateway, 1)
    assert typed["confirmable_by_typing"] is True

    release, entered = _hold_subagents(monkeypatch)
    SUB_SCRIPT[:] = [AIMessage(content="sub done")]
    cards, results = _card_confirm_in_background(gateway, [a for _, a in held_by_card])
    box: dict = {}
    try:
        assert _wait_for(lambda: _slots_taken() == cf.CONFIRMS_PER_USER), f"the card confirmations did not take this user's slots: {_slots_taken()}"
        dc.LEAD_SCRIPT[:] = [AIMessage(content="the lead must not answer")]

        def typed_yes() -> None:
            r = gateway.client.post(
                f"/api/threads/{typed_thread}/runs/wait",
                json={"assistant_id": "lead_agent", "input": {"messages": [{"role": "user", "content": "yes"}]}, "context": {"subagent_enabled": True}},
            )
            box["status"], box["body"] = r.status_code, r.json()

        t = threading.Thread(target=typed_yes)
        t.start()
        t.join(10)
        answered_while_full = not t.is_alive()
        stored_while_full = _stored(typed["id"])
    finally:
        _drain(release, cards)
    t.join(30)
    assert box["status"] == 200, box
    reply = str(box["body"].get("messages", [])[-1].get("content"))
    # The card's busy answer, word for word (CONFIRM_BUSY_MESSAGE).
    assert reply == f"{cf.CONFIRMS_PER_USER} confirmed actions are already running, so this one has not started. Nothing has run. Confirm again when one finishes.", f"a typed yes with no free slot was not refused as busy: {reply!r}"
    assert answered_while_full, "a typed yes with no free slot did not answer at once"
    # Nothing ran, nothing was claimed: the plan is still open, for the card or
    # another "yes" once a slot is free.
    assert stored_while_full.outcome is None and not stored_while_full.confirmation, stored_while_full
    assert _stored(typed["id"]).outcome is None
    assert typed["id"] in [a["id"] for a in _pending(gateway, "task")]
    assert set(results.values()) == {"executed"}, results
