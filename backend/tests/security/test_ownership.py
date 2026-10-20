"""Item 0c: a second account cannot see or act on the owner's records.

The door is OPENED first (`sec.admit_second()`), so each of these passes only
because the ownership check holds, not because the second account was turned
away at sign-in (test_owner_only covers that). Real HTTP, auth ON.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


@pytest.fixture
def two(sec):
    sec.admit_second()
    other = sec.login_second()
    tid = sec.owner.post("/api/threads", json={"metadata": {"title": "owner's"}}).json()["thread_id"]
    return sec, other, tid


def _pending_store():
    from app.policy.registration import build
    from omniharness.config import get_app_config

    return build(get_app_config()).pending


def _state_plan(owner_id: str | None, thread_id: str | None = None):
    from app.policy.models import PendingAction, Tier

    action = PendingAction(
        plan_text="Delete four calendar events",
        tool_name="gmail_delete_email",
        arguments={"ids": ["a", "b"]},
        targets=["a", "b"],
        tier_at_statement=Tier.TIER_3,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        thread_id=thread_id,
        owner_id=owner_id,
    )
    _pending_store().save(action)
    return action


# ── threads ──────────────────────────────────────────────────────────────


def test_second_account_cannot_see_the_owners_thread(two) -> None:
    sec, other, tid = two
    assert other.get(f"/api/threads/{tid}").status_code == 404
    assert other.get(f"/api/threads/{tid}/state").status_code == 404
    listed = other.post("/api/threads/search", json={}).json()
    assert tid not in [t["thread_id"] for t in listed]
    # Positive control: the owner sees it.
    assert sec.owner.get(f"/api/threads/{tid}").status_code == 200
    assert tid in [t["thread_id"] for t in sec.owner.post("/api/threads/search", json={}).json()]


def test_second_account_cannot_change_or_delete_the_owners_thread(two) -> None:
    sec, other, tid = two
    assert other.patch(f"/api/threads/{tid}", json={"metadata": {"title": "mine now"}}).status_code == 404
    assert other.delete(f"/api/threads/{tid}").status_code == 404
    assert sec.owner.get(f"/api/threads/{tid}").status_code == 200


def test_second_account_cannot_read_or_set_the_owners_thread_tools(two) -> None:
    sec, other, tid = two
    assert other.get(f"/api/threads/{tid}/tools").status_code == 404
    assert other.put(f"/api/threads/{tid}/tools", json={"sources": []}).status_code == 404
    assert other.get(f"/api/threads/{tid}/skills").status_code == 404
    assert sec.owner.get(f"/api/threads/{tid}/tools").status_code == 200


def test_second_account_cannot_run_on_the_owners_thread_through_the_stateless_api(two) -> None:
    """/api/runs/* names the thread in the BODY, so the path decorator never
    saw it; start_run now checks it for every route."""
    _, other, tid = two
    body = {"assistant_id": "lead_agent", "input": {"messages": [{"role": "human", "content": "hi"}]}, "config": {"configurable": {"thread_id": tid}}}
    assert other.post("/api/runs/wait", json=body).status_code == 404
    assert other.post(f"/api/threads/{tid}/runs/wait", json=body).status_code == 404


def test_second_account_cannot_read_the_owners_run_history(two) -> None:
    _, other, tid = two
    assert other.get(f"/api/threads/{tid}/runs").status_code == 404


# ── pending actions (approvals) ──────────────────────────────────────────


def test_second_account_cannot_list_the_owners_approvals(two) -> None:
    sec, other, tid = two
    action = _state_plan(sec.owner_id, tid)
    assert action.id not in [a["id"] for a in other.get("/api/confirmations").json()["actions"]]
    assert action.id in [a["id"] for a in sec.owner.get("/api/confirmations").json()["actions"]]


@pytest.mark.parametrize("verb", ["confirm", "decline"])
def test_second_account_cannot_answer_the_owners_approval(two, verb) -> None:
    sec, other, tid = two
    action = _state_plan(sec.owner_id, tid)
    resp = other.post(f"/api/confirmations/{action.id}/{verb}", json={})
    assert resp.status_code == 404, resp.text
    # Still open, untouched.
    stored = _pending_store().get(action.id)
    assert stored.outcome is None and stored.claimed_by is None


def test_second_account_cannot_edit_the_owners_approval(two) -> None:
    sec, other, tid = two
    action = _state_plan(sec.owner_id, tid)
    resp = other.post(f"/api/confirmations/{action.id}/edit", json={"arguments": {"ids": ["a"]}})
    assert resp.status_code == 404, resp.text
    assert _pending_store().get(action.id).outcome is None


def test_the_owner_answers_the_systems_approvals_and_legacy_ones(two) -> None:
    """A scheduled run's plan is owned by the system user; a plan from before
    owners were stored has none. Both are the owner's to answer, nobody else's."""
    sec, other, _ = two
    system = _state_plan("default")
    legacy = _state_plan(None)
    other_ids = [a["id"] for a in other.get("/api/confirmations").json()["actions"]]
    owner_ids = [a["id"] for a in sec.owner.get("/api/confirmations").json()["actions"]]
    assert system.id not in other_ids and legacy.id not in other_ids
    assert system.id in owner_ids and legacy.id in owner_ids
    assert other.post(f"/api/confirmations/{system.id}/decline", json={}).status_code == 404
    assert sec.owner.post(f"/api/confirmations/{system.id}/decline", json={}).json()["outcome"] == "declined"


def test_a_plan_is_stamped_with_the_owner_of_the_run_that_stated_it(two) -> None:
    """The middleware records runtime.context['user_id'] (server-set) as owner."""
    from types import SimpleNamespace

    from app.policy.registration import build
    from omniharness.config import get_app_config

    sec, _, tid = two
    middleware = build(get_app_config())
    runtime = SimpleNamespace(context={"thread_id": tid, "user_id": sec.owner_id})
    request = SimpleNamespace(tool_call={"name": "googlecalendar_decline_everything", "args": {"meetings": ["m1"]}, "id": "tc1"}, runtime=runtime, state={"messages": []})
    middleware.wrap_tool_call(request, lambda r: pytest.fail("a Tier 3 call executed at statement"))
    [action] = [a for a in middleware.pending.open_actions(middleware.now()) if a.thread_id == tid]
    assert action.owner_id == sec.owner_id


# ── agent configs ────────────────────────────────────────────────────────


def test_second_account_cannot_see_edit_or_delete_the_owners_agent(two) -> None:
    sec, other, _ = two
    created = sec.owner.post("/api/agents", json={"name": "owners-agent", "description": "mine", "soul": "be useful"})
    assert created.status_code == 201, created.text
    assert other.get("/api/agents/owners-agent").status_code == 404
    assert "owners-agent" not in [a["name"] for a in other.get("/api/agents").json()["agents"]]
    assert other.put("/api/agents/owners-agent", json={"description": "taken"}).status_code == 404
    assert other.delete("/api/agents/owners-agent").status_code == 404
    got = sec.owner.get("/api/agents/owners-agent")
    assert got.status_code == 200 and got.json()["description"] == "mine"
