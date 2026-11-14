"""A save card the builder raises itself is a card of the turn like any
proposed one (Spec 010, review of the server-raised save card).

- same turn key, requester, tool surface, expiry and origin as a card the
  model proposed in that turn, so a turn with both resumes once, after both
  are answered;
- two drafts in one model step show one card (the per-chat lock is held
  across the checks and the raise);
- the draft call's trace step says it ended in a card, with the card's id.
"""

from __future__ import annotations

import time
from pathlib import Path

from builder_helpers import call, cards, new_thread, say, script

DRAFT = {"kind": "agent", "name": "test-010-sessions", "fields": {"instructions": "Report on running coding sessions."}}
TASK = {"description": "sessions", "prompt": "List my coding sessions.", "subagent_type": "general-purpose"}


def _store(gw):
    from app.policy.pending import PendingStore

    return PendingStore(directory=Path(gw.client.app.state.config.policy.state_dir) / "pending")


def _wait(gw, thread_id: str, run_id: str | None) -> None:
    deadline = time.time() + 30
    while run_id and time.time() < deadline and gw.client.get(f"/api/threads/{thread_id}/runs/{run_id}").json().get("status") in ("pending", "running"):
        time.sleep(0.05)


def _turn_with_both(gw) -> tuple[str, object, object]:
    thread_id = new_thread(gw)
    script(gw, [call("builder_draft", DRAFT, "c1")], [call("task", TASK, "t1")], "Waiting.")
    say(gw, thread_id, "make me an agent that reports on my coding sessions, and ask a helper to list them now")
    [save] = cards(gw, "builder_save")
    [task] = cards(gw, "task")
    return thread_id, _store(gw).get(save["id"]), _store(gw).get(task["id"])


def test_a_raised_card_and_a_proposed_card_of_one_turn_match(gw) -> None:
    _, save, task = _turn_with_both(gw)
    assert save.group_key and save.group_key == task.group_key, (save.group_key, task.group_key)
    assert not save.group_key.startswith("run:"), "the turn key is the owner's message id, as for a proposed card"
    assert save.requester == task.requester and save.thread_id == task.thread_id and save.owner_id == task.owner_id
    assert save.surface == task.surface, (save.surface, task.surface)
    assert abs((save.expires_at - task.expires_at).total_seconds()) < 10, "both expire by the same rule"
    assert save.origin == task.origin == "user", (save.origin, task.origin)


def test_a_mixed_turn_resumes_once_after_both_cards_are_answered(gw) -> None:
    thread_id, save, task = _turn_with_both(gw)
    script(gw, "Noted.")
    first = gw.client.post(f"/api/confirmations/{task.id}/decline", json={}).json()
    assert not (first.get("resume_run_id") or (first.get("detail") or {}).get("resume_run_id")), "resumed before the save card was answered"
    script(gw, "Saved.")
    second = gw.client.post(f"/api/confirmations/{save.id}/confirm", json={}).json()
    run_id = second.get("resume_run_id") or (second.get("detail") or {}).get("resume_run_id")
    assert run_id, second
    _wait(gw, thread_id, run_id)
    runs = gw.client.get(f"/api/threads/{thread_id}/runs").json()
    runs = runs.get("runs", runs) if isinstance(runs, dict) else runs
    assert len(runs) == 2, f"one turn and ONE resume: {runs}"


def test_two_drafts_in_one_model_step_show_one_card(gw) -> None:
    thread_id = new_thread(gw)
    other = {**DRAFT, "fields": {"instructions": "Report on sessions every hour."}}
    script(gw, [call("builder_draft", DRAFT, "c1"), call("builder_draft", other, "c2")], "Drafted.")
    out = say(gw, thread_id, "make me an agent that reports on my coding sessions")
    raised = [a for a in _store(gw).in_thread(thread_id) if a.tool_name == "builder_save"]
    assert len(raised) == 1, [(a.id, a.outcome) for a in raised]
    texts = [str(m.get("content")) for m in out["messages"] if m.get("type") == "tool"]
    assert any("this step already showed the save card" in t for t in texts), texts


def test_the_draft_call_is_stamped_with_its_card(gw) -> None:
    from omniharness.agents.turns import POLICY_STEP_MARKER

    thread_id = new_thread(gw)
    script(gw, [call("builder_draft", DRAFT, "c1")], "Drafted.")
    out = say(gw, thread_id, "make me an agent that reports on my coding sessions")
    [card] = cards(gw, "builder_save")
    [result] = [m for m in out["messages"] if m.get("type") == "tool" and m.get("name") == "builder_draft"]
    stamp = (result.get("additional_kwargs") or {}).get(POLICY_STEP_MARKER)
    assert stamp and stamp.get("outcome") == "needs_confirmation" and stamp.get("card_id") == card["id"], stamp


def test_the_builder_holds_the_same_reentrant_lock_a_proposed_card_is_stated_under() -> None:
    from app.policy.middleware import _proposing
    from app.policy.server_cards import card_lock

    context = {"user_id": "u-1", "thread_id": "t-1"}
    lock = card_lock(context)
    assert lock is _proposing("u-1", "t-1"), "the builder must take the middleware's per-chat lock"
    with lock, lock:  # re-entrant: raise_card takes it again inside the builder's hold
        pass
