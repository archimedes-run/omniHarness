"""Per-chat skill removal (Feature 006, the chat bar's skill chips).

Through the gateway as production builds it: the exclusion is stored per
thread, loaded at run launch into the runtime context as ``excluded_skills``,
and never taken from the client's run body.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

from app.gateway import services
from app.gateway.services import ConflictError


def _capture_launch():
    """Patch the detached launch: record the run config, then refuse the run
    so no agent actually starts (the router turns the conflict into a 409)."""
    seen: dict = {}

    async def fake_launch(**kwargs):
        seen["config"] = kwargs["run_config"]
        raise ConflictError("captured for the test")

    return seen, patch.object(services, "launch_agent_run_detached", fake_launch)


def _new_thread(client) -> str:
    resp = client.post("/api/threads", json={})
    assert resp.status_code == 200, resp.text
    return resp.json()["thread_id"]


def _launch(client, thread_id: str, **body) -> dict:
    seen, patcher = _capture_launch()
    with patcher:
        resp = client.post(f"/api/threads/{thread_id}/runs", json={"input": {"messages": []}, **body})
    assert resp.status_code == 409, resp.text
    return seen["config"]


def test_a_thread_with_nothing_removed_reads_empty(gateway):
    tid = str(uuid.uuid4())
    resp = gateway.client.get(f"/api/threads/{tid}/skills")
    assert resp.status_code == 200
    assert resp.json() == {"thread_id": tid, "excluded": []}


def test_an_exclusion_can_be_stored_before_the_thread_has_a_run(gateway):
    tid = str(uuid.uuid4())  # the new-chat page's client-generated id
    resp = gateway.client.put(f"/api/threads/{tid}/skills", json={"excluded": ["deep-research", "deep-research", "spec-kit"]})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"thread_id": tid, "excluded": ["deep-research", "spec-kit"]}
    assert gateway.client.get(f"/api/threads/{tid}/skills").json()["excluded"] == ["deep-research", "spec-kit"]


def test_a_launched_run_carries_the_stored_exclusion(gateway):
    tid = _new_thread(gateway.client)
    gateway.client.put(f"/api/threads/{tid}/skills", json={"excluded": ["deep-research"]})
    config = _launch(gateway.client, tid)
    assert config["context"]["excluded_skills"] == ["deep-research"]


def test_a_run_with_nothing_removed_has_no_exclusion(gateway):
    tid = _new_thread(gateway.client)
    config = _launch(gateway.client, tid)
    assert "excluded_skills" not in config.get("context", {})


def test_the_client_cannot_set_the_exclusion_through_the_run_body(gateway):
    tid = _new_thread(gateway.client)
    gateway.client.put(f"/api/threads/{tid}/skills", json={"excluded": ["deep-research"]})
    config = _launch(
        gateway.client,
        tid,
        context={"excluded_skills": ["spec-kit"]},
        config={"configurable": {"excluded_skills": ["bootstrap"]}},
    )
    assert config["context"]["excluded_skills"] == ["deep-research"]
    assert "excluded_skills" not in config.get("configurable", {})


def test_the_client_cannot_add_an_exclusion_where_none_is_stored(gateway):
    tid = _new_thread(gateway.client)
    config = _launch(gateway.client, tid, context={"excluded_skills": ["spec-kit"]}, config={"context": {"excluded_skills": ["spec-kit"]}})
    assert "excluded_skills" not in config.get("context", {})
    assert "excluded_skills" not in config.get("configurable", {})
