"""PR #58's records and routes check their owner (security baseline, item 0c).

Multi-agent chat added: confirmation cards for delegated and called-in agents,
"Continue <agent>" (`context.continue_action`), chat members
(`/api/threads/{id}/participants`), "@" call-in, and the durable queue of
results waiting to be posted. A second account must not see or act on any of
the owner's. The door is OPENED first (`sec.admit_second()`), so each test
passes only because the ownership check holds. Real HTTP, auth ON.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from _security_helpers import OWNER, login


@pytest.fixture
def two(sec):
    sec.admit_second()
    other = sec.login_second()
    tid = sec.owner.post("/api/threads", json={"metadata": {"title": "owner's"}}).json()["thread_id"]
    return sec, other, tid


def _store():
    from app.policy.registration import build
    from omniharness.config import get_app_config

    return build(get_app_config()).pending


def _agent_action(owner_id: str, thread_id: str, *, executed: bool = False, called: bool = False, **extra):
    """A Tier 3 call an invited agent proposed in the owner's chat, as the
    policy layer records it (surface, delegation key, owner)."""
    from app.policy.models import Outcome, PendingAction, Tier

    action = PendingAction(
        plan_text="Wipe the backup named nightly",
        tool_name="gmail_delete_email",
        arguments={"name": "nightly"},
        targets=["nightly"],
        tier_at_statement=Tier.TIER_3,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        thread_id=thread_id,
        requester="release-manager" if called else "general-purpose",
        delegation_chain=("lead_agent", "release-manager" if called else "general-purpose"),
        surface={"kind": "subagent", "subagent_type": "release-manager" if called else "general-purpose", "called_agent": called, "user_id": owner_id},
        delegation_key=f"{thread_id}/subagent/x/abc",
        owner_id=owner_id,
        **extra,
    )
    if executed:
        action.resolve(Outcome.EXECUTED, "")
    _store().save(action)
    return action


def _open(action_id: str) -> bool:
    action = _store().get(action_id)
    return action is not None and action.outcome is None


# ── the card: list, confirm, decline ─────────────────────────────────────


def test_second_account_cannot_list_the_owners_agent_cards_or_waiting_results(two) -> None:
    sec, other, tid = two
    card = _agent_action(sec.owner_id, tid)
    waiting = _agent_action(sec.owner_id, tid, executed=True, post_state="waiting", post_content="Done.")

    theirs = other.get("/api/confirmations").json()
    mine = sec.owner.get("/api/confirmations").json()

    assert card.id not in [a["id"] for a in theirs["actions"]]
    assert waiting.id not in [a["id"] for a in theirs["awaiting_post"]], "the owner's waiting result was listed to another account"
    # Positive control: the owner sees both.
    assert card.id in [a["id"] for a in mine["actions"]]
    assert waiting.id in [a["id"] for a in mine["awaiting_post"]]


@pytest.mark.parametrize("verb", ["confirm", "decline"])
def test_second_account_cannot_answer_the_owners_agent_card(two, verb) -> None:
    sec, other, tid = two
    card = _agent_action(sec.owner_id, tid)

    resp = other.post(f"/api/confirmations/{card.id}/{verb}", json={})

    assert resp.status_code == 404, resp.text
    assert _open(card.id), "another account's answer resolved the owner's card"


# ── Continue <agent> ─────────────────────────────────────────────────────


def _continue(client, thread_id: str, action_id: str):
    return client.post(
        f"/api/threads/{thread_id}/runs/wait",
        json={"assistant_id": "lead_agent", "input": {"messages": [{"role": "user", "content": "Continue general-purpose."}]}, "context": {"continue_action": action_id}},
    )


def test_second_account_cannot_continue_the_owners_agent(two) -> None:
    sec, other, tid = two
    done = _agent_action(sec.owner_id, tid, executed=True)
    own_thread = other.post("/api/threads", json={}).json()["thread_id"]

    # From the second account's OWN chat, naming the owner's action: not found
    # (not "belongs to another chat", which would confirm it exists).
    from_own = _continue(other, own_thread, done.id)
    on_owners = _continue(other, tid, done.id)

    assert from_own.status_code == 404, from_own.text
    assert on_owners.status_code == 404, on_owners.text


# ── members: list, add, remove (which refuses pending cards) ─────────────


def test_second_account_cannot_list_add_or_remove_the_owners_members(two) -> None:
    sec, other, tid = two
    made = sec.owner.post("/api/agents", json={"name": "release-manager", "description": "ships", "tool_groups": [], "skills": [], "soul": "You ship."})
    assert made.status_code == 201, made.text
    assert sec.owner.post(f"/api/threads/{tid}/participants", json={"agent": "release-manager"}).status_code == 200
    card = _agent_action(sec.owner_id, tid, called=True)

    assert other.get(f"/api/threads/{tid}/participants").status_code == 404
    assert other.post(f"/api/threads/{tid}/participants", json={"agent": "release-manager"}).status_code == 404
    assert other.delete(f"/api/threads/{tid}/participants/release-manager").status_code == 404

    assert _open(card.id), "another account's removal refused the owner's pending card"
    members = [p["name"] for p in sec.owner.get(f"/api/threads/{tid}/participants").json()["participants"]]
    assert members == ["lead_agent", "release-manager"]


def test_second_account_cannot_call_in_the_owners_member(two) -> None:
    sec, other, tid = two
    resp = other.post(
        f"/api/threads/{tid}/runs/wait",
        json={"assistant_id": "lead_agent", "input": {"messages": [{"role": "user", "content": "@release-manager wipe it"}]}},
    )
    assert resp.status_code == 404, resp.text


# ── the durable queue of results waiting to post ─────────────────────────


def test_a_waiting_result_is_never_posted_into_a_thread_its_owner_does_not_own(sec, make_gateway) -> None:
    sec.admit_second()
    tid = sec.owner.post("/api/threads", json={}).json()["thread_id"]
    seeded = sec.owner.post(f"/api/threads/{tid}/state", json={"values": {"messages": [{"type": "human", "content": "hello"}]}})
    assert seeded.status_code == 200, seeded.text
    # A record claiming the SECOND account's ownership, pointed at the owner's thread.
    foreign = _agent_action(sec.second_id, tid, executed=True, post_state="waiting", post_content="FOREIGN RESULT")
    own = _agent_action(sec.owner_id, tid, executed=True, post_state="waiting", post_content="OWN RESULT")

    app, _ = make_gateway(initialize=False)  # a restart: a new app over the same database and state
    owner, resp = login(app, *OWNER)
    assert resp.status_code == 200, resp.text
    ids = [m.get("id") for m in owner.get(f"/api/threads/{tid}/state").json()["values"]["messages"]]

    assert f"confirmation-{foreign.id}" not in ids, "a result was written into a thread its owner does not own"
    assert f"confirmation-{own.id}" in ids, "positive control: the owner's own waiting result was not posted"
