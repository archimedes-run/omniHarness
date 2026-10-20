"""The run history is the owner's (security baseline adoption), through real
HTTP with real cookies. A scheduled run is owned by the system user (the engine
acts as the internal principal), which the ownership rule gives to the owner
account only. With the door OPEN (admit_second), a second account still can't
list, read, change or delete any of it."""

from __future__ import annotations

import pytest


@pytest.fixture
def runs(sec):
    from app.run_history.recorder import automation_recorder

    history = sec.app.state.run_history
    automation_recorder(history)({"rule_id": "inbox", "status": "completed", "body": {"reply": "OWNER-ONLY-CONTENT"}})
    (scheduled,) = history.list(source_id="inbox")
    own = history.record(kind="automation", source_id="mine", body={"reply": "x"}, status="completed", owner_id=sec.owner_id)
    return scheduled.id, own


def test_a_scheduled_run_is_owned_by_the_system_user(sec, runs) -> None:
    from omniharness.runtime.user_context import DEFAULT_USER_ID

    scheduled, _ = runs
    assert sec.app.state.run_history.get(scheduled)["owner_id"] == DEFAULT_USER_ID


def test_the_owner_sees_the_scheduled_and_own_runs(sec, runs) -> None:
    scheduled, own = runs
    listed = {r["id"] for r in sec.owner.get("/api/run-history/runs").json()}
    assert listed == {scheduled, own}
    assert "OWNER-ONLY-CONTENT" in sec.owner.get(f"/api/run-history/runs/{scheduled}").text


def test_a_second_account_cannot_list_read_change_or_delete_it(sec, runs) -> None:
    sec.admit_second()
    other = sec.login_second()
    scheduled, own = runs

    assert other.get("/api/run-history/runs").json() == [], "the second account lists the owner's runs"
    for rid in (scheduled, own):
        r = other.get(f"/api/run-history/runs/{rid}")
        assert r.status_code == 404 and "OWNER-ONLY-CONTENT" not in r.text
    assert other.get("/api/run-history/settings").status_code == 404
    assert other.put("/api/run-history/settings", json={"retention_days": 1}).status_code == 404
    assert other.delete("/api/run-history/runs", params={"confirm": "delete-all"}).status_code in (403, 404)

    history = sec.app.state.run_history
    assert history.count() == 2 and history.retention_days() == 30, "the second account changed the owner's history"
