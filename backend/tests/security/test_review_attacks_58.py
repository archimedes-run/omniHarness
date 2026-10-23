# ruff: noqa: F401, F811, F841  (the reviewer's attack file, kept verbatim: it imports the `gateway` fixture by name)
"""Adversarial review of PR #58 (independent reviewer). Real HTTP, auth ON.

Reuses the production-composition fixture of
tests/policy/test_delegated_confirmation.py (`gateway`: create_app()+lifespan,
real runs, real task tool and SubagentExecutor, fake models) and the security
fixture `sec` (owner + second account).
"""

from __future__ import annotations

import dataclasses
import sys
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "policy"))
import test_delegated_confirmation as dc  # noqa: E402
from test_delegated_confirmation import (  # noqa: E402,F401
    DELEGATE,
    HOLD,
    RAN,
    SUB_SCRIPT,
    SUBAGENT_RUNS,
    _continue,
    _pending,
    _say,
    _thread,
    _thread_messages,
    _user_delegates_and_subagent_proposes,
    gateway,
)


def _store():
    from app.policy.pending import PendingStore
    from omniharness.config import get_app_config

    return PendingStore(directory=Path(get_app_config().policy.state_dir) / "pending")


def _clone(action_id: str, n: int) -> list[str]:
    """n more open copies of a real, server-written pending action (new ids)."""
    store = _store()
    base = store.get(action_id)
    ids = []
    for _ in range(n):
        copy = dataclasses.replace(base, id=uuid.uuid4().hex[:12])
        copy.claimed_by = None
        store.save(copy)
        ids.append(copy.id)
    return ids


def _post_async(client, url: str, box: dict, key: str) -> threading.Thread:
    t = threading.Thread(target=lambda: box.update({key: client.post(url, json={})}), daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# 1. Continue after a restart: the delegation's own history must come back
# ---------------------------------------------------------------------------


def test_continue_after_a_process_restart_still_has_the_delegations_history(gateway) -> None:
    """The subagent's checkpoints go to omniharness.runtime.checkpointer.get_checkpointer(),
    which is an InMemorySaver unless a legacy `checkpointer:` section exists
    (the shipped config uses `database:` only). The in-process fixture restart
    keeps that singleton alive; a real process restart does not, so reset it."""
    from omniharness.runtime.checkpointer import reset_checkpointer

    thread_id, wipe = _user_delegates_and_subagent_proposes(gateway)
    assert gateway.client.post(f"/api/confirmations/{wipe['id']}/confirm", json={}).json()["outcome"] == "executed"

    gateway.restart()
    reset_checkpointer()  # what a real process restart does to a module singleton

    SUBAGENT_RUNS.clear()
    SUB_SCRIPT[:] = [AIMessage(content="continued")]
    resp = _continue(gateway, thread_id, wipe["id"])
    assert resp.status_code == 200, resp.text
    [seen] = SUBAGENT_RUNS
    text = "\n".join(seen)
    assert "Wipe the backup named nightly." in text, "after a restart Continue re-entered an EMPTY delegation: its own task and history are gone"


# ---------------------------------------------------------------------------
# 2. Confirm pool exhaustion: 4 long confirmations block every decline
# ---------------------------------------------------------------------------


def test_four_long_confirmations_do_not_block_a_decline(gateway) -> None:
    _thread_id, wipe = _user_delegates_and_subagent_proposes(gateway)
    others = _clone(wipe["id"], 4)
    entered, release = threading.Event(), threading.Event()
    HOLD["wipe"] = (entered, release)
    box: dict = {}
    workers = [_post_async(gateway.client, f"/api/confirmations/{aid}/confirm", box, aid) for aid in [wipe["id"], *others[:3]]]
    assert entered.wait(30)
    time.sleep(1.0)  # let all four reach the held tool

    started = time.monotonic()
    decliner = _post_async(gateway.client, f"/api/confirmations/{others[3]}/decline", box, "decline")
    decliner.join(5)
    waited = time.monotonic() - started
    release.set()
    for w in workers:
        w.join(30)
    decliner.join(30)
    HOLD.clear()
    assert waited < 5, f"a DECLINE of an unrelated card hung {waited:.1f}s behind four running confirmations (_CONFIRM_POOL max_workers=4)"


# ---------------------------------------------------------------------------
# 3. Exactly once: concurrent confirm + decline, concurrent double confirm
# ---------------------------------------------------------------------------


def test_concurrent_confirm_and_decline_runs_at_most_once(gateway) -> None:
    _thread_id, wipe = _user_delegates_and_subagent_proposes(gateway)
    entered, release = threading.Event(), threading.Event()
    HOLD["wipe"] = (entered, release)
    box: dict = {}
    c1 = _post_async(gateway.client, f"/api/confirmations/{wipe['id']}/confirm", box, "c1")
    assert entered.wait(30)
    d = gateway.client.post(f"/api/confirmations/{wipe['id']}/decline", json={}).json()
    c2 = gateway.client.post(f"/api/confirmations/{wipe['id']}/confirm", json={}).json()
    release.set()
    c1.join(30)
    HOLD.clear()
    final = _store().get(wipe["id"])
    assert box["c1"].json()["outcome"] == "executed"
    assert RAN == [("wipe_backup", {"name": "nightly"})]
    # The decline arrived while the confirmed call was RUNNING (claimed). The
    # decline path never takes the claim, so it answers "I have not done it"
    # and records DECLINED; the execution then overwrites it with EXECUTED.
    assert d["outcome"] != "declined", f"decline told the user 'not done' while it ran; final record outcome={final.outcome}"


# ---------------------------------------------------------------------------
# 4. A chat deleted after the card was raised
# ---------------------------------------------------------------------------


def test_a_card_whose_chat_was_deleted_is_not_run_or_left_waiting_forever(gateway) -> None:
    thread_id, wipe = _user_delegates_and_subagent_proposes(gateway)
    assert gateway.client.delete(f"/api/threads/{thread_id}").status_code == 200

    body = gateway.client.post(f"/api/confirmations/{wipe['id']}/confirm", json={}).json()
    awaiting = gateway.client.get("/api/confirmations").json()["awaiting_post"]

    assert wipe["id"] not in [a["id"] for a in awaiting], "the result sits 'waiting to post' into a deleted chat forever"


# ---------------------------------------------------------------------------
# 5. Continue: replay, and a pending card elsewhere in the chat
# ---------------------------------------------------------------------------


def test_a_card_whose_chat_was_deleted_is_not_run(gateway) -> None:
    thread_id, wipe = _user_delegates_and_subagent_proposes(gateway)
    assert gateway.client.delete(f"/api/threads/{thread_id}").status_code == 200
    body = gateway.client.post(f"/api/confirmations/{wipe['id']}/confirm", json={}).json()
    assert RAN == [], f"the deleted chat's card still ran its call: {body['outcome']}, posted={body['detail'].get('posted_to_thread')}"


def test_continue_cannot_be_replayed(gateway) -> None:
    thread_id, wipe = _user_delegates_and_subagent_proposes(gateway)
    assert gateway.client.post(f"/api/confirmations/{wipe['id']}/confirm", json={}).json()["outcome"] == "executed"
    SUB_SCRIPT[:] = [AIMessage(content="continued")]
    assert _continue(gateway, thread_id, wipe["id"]).status_code == 200
    SUBAGENT_RUNS.clear()
    again = _continue(gateway, thread_id, wipe["id"])
    assert again.status_code == 409 or SUBAGENT_RUNS == [], "the same confirmed action re-entered the delegation a second time (replayed 'the user confirmed, continue')"


def test_continue_works_while_another_card_is_pending(gateway) -> None:
    thread_id, wipe = _user_delegates_and_subagent_proposes(gateway)
    assert gateway.client.post(f"/api/confirmations/{wipe['id']}/confirm", json={}).json()["outcome"] == "executed"
    # Another Tier 3 card is pending in the same chat.
    _say(gateway, thread_id, "also delegate another thing please", [AIMessage(content="", tool_calls=[{**DELEGATE, "id": "d9"}]), AIMessage(content="waiting")])
    assert len(_pending(gateway, "task")) == 1
    SUBAGENT_RUNS.clear()
    SUB_SCRIPT[:] = [AIMessage(content="continued")]
    resp = _continue(gateway, thread_id, wipe["id"])
    assert resp.status_code == 200, resp.text
    assert SUBAGENT_RUNS, f"Continue did nothing while another card was pending: {resp.json().get('messages', [])[-1:]}"
    assert len(_pending(gateway, "task")) == 1, "the Continue turn resolved a DIFFERENT pending card"


# ---------------------------------------------------------------------------
# 6. HTTP-only seeds (sec fixture): deleted agent, untracked thread, edit
# ---------------------------------------------------------------------------


def _called_action(owner_id: str, thread_id: str, agent: str):
    from app.policy.models import PendingAction, Tier

    action = PendingAction(
        plan_text="Wipe the backup named nightly",
        tool_name="wipe_backup",
        arguments={"name": "nightly"},
        targets=["nightly"],
        tier_at_statement=Tier.TIER_3,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        thread_id=thread_id,
        requester=agent,
        delegation_chain=("lead_agent", agent),
        surface={"kind": "subagent", "subagent_type": agent, "called_agent": True, "user_id": owner_id, "model_name": None, "tool_groups": [], "skills": [], "selected_sources": None},
        delegation_key=f"{thread_id}/subagent/x/abc",
        owner_id=owner_id,
    )
    from app.policy.registration import build
    from omniharness.config import get_app_config

    build(get_app_config()).pending.save(action)
    return action


def test_a_deleted_called_agents_card_is_refused_with_a_reason(sec) -> None:
    tid = sec.owner.post("/api/threads", json={}).json()["thread_id"]
    made = sec.owner.post("/api/agents", json={"name": "release-manager", "description": "ships", "tool_groups": [], "skills": [], "soul": "You ship."})
    assert made.status_code == 201, made.text
    action = _called_action(sec.owner_id, tid, "release-manager")
    assert sec.owner.delete("/api/agents/release-manager").status_code in (200, 204)

    resp = sec.owner.post(f"/api/confirmations/{action.id}/confirm", json={})

    assert resp.status_code == 200, resp.text
    assert resp.json()["outcome"] == "tool_unavailable", resp.json()
    assert "no longer exists" in resp.json()["message"]


def test_second_account_cannot_take_over_an_untracked_thread_via_participants(sec) -> None:
    """add_participant checks thread access WITHOUT require_existing (a write),
    then creates the threads_meta row as the caller's."""
    sec.admit_second()
    other = sec.login_second()
    tid = str(uuid.uuid4())

    async def seed():
        cp = sec.app.state.checkpointer
        from langgraph.checkpoint.base import empty_checkpoint

        ck = empty_checkpoint()
        ck["channel_values"] = {"messages": []}
        await cp.aput({"configurable": {"thread_id": tid, "checkpoint_ns": ""}}, ck, {"source": "input", "step": -1}, {})

    sec.owner.portal.call(seed)  # an untracked (legacy/no-meta-row) chat of the owner's
    assert sec.owner.post("/api/agents", json={"name": "spy-agent", "description": "x", "tool_groups": [], "skills": [], "soul": "x"}).status_code == 201

    resp = other.post(f"/api/threads/{tid}/participants", json={"agent": "spy-agent"})
    owner_view = sec.owner.get(f"/api/threads/{tid}/participants")

    assert resp.status_code == 404, f"second account wrote to (and now owns) an untracked thread: {resp.status_code} {resp.text[:200]}; owner now gets {owner_view.status_code}"


@pytest.mark.parametrize("verb", ["edit"])
def test_second_account_cannot_edit_the_owners_card(sec, verb) -> None:
    sec.admit_second()
    other = sec.login_second()
    tid = sec.owner.post("/api/threads", json={}).json()["thread_id"]
    action = _called_action(sec.owner_id, tid, "release-manager")
    resp = other.post(f"/api/confirmations/{action.id}/edit", json={"arguments": {"name": "x"}})
    assert resp.status_code == 404, resp.text
