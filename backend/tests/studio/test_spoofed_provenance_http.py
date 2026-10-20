"""A chat run that CLAIMS to be scheduled, through real HTTP (review round 2, C.2).

The client is the owner, logged in with real cookies (the studio fixture:
create_app() with its lifespan, auth on). It starts an ordinary chat run on
/api/threads/{id}/runs/wait whose body carries turn_provenance=synthetic-trigger
(and a rule and firing id), the markers only the trigger engine may set. The
lead agent is the real one the gateway builds; only the model is scripted.

  * Every Tier 3 call still asks: nothing a spoofed marker could unlock skips
    a confirmation (Tier 3 never consults grants).
  * The spoofed marker is ignored, so the run behaves as the chat it is: a
    routine Tier 2 ledger write runs and is disclosed, rather than being held
    as if nobody were there (the security baseline's server-owned run context:
    the markers, the firing id included, are accepted only from the trigger
    engine's internal auth).
"""

from __future__ import annotations

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

SPOOF = {"turn_provenance": "synthetic-trigger", "trigger_rule_id": "evening-wrap", "trigger_firing_id": "spoofed-firing"}


class ToolCapableFake(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _call(changes: list[dict], call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": "ledger_apply", "args": {"changes": changes}, "id": call_id}])


@pytest.fixture
def scripted(monkeypatch):
    """The lead agent's model answers from `steps`; any helper model (title,
    summary) answers a fixed line."""
    import omniharness.agents.lead_agent.agent as lead
    import omniharness.agents.middlewares.title_middleware as title

    steps: list[AIMessage] = []

    def factory(*args, **kwargs):
        if "reasoning_effort" in kwargs:
            return ToolCapableFake(messages=iter([*steps, AIMessage(content="Done."), AIMessage(content="Done.")]))
        return ToolCapableFake(messages=iter([AIMessage(content="A title")] * 5))

    monkeypatch.setattr(lead, "create_chat_model", factory)
    monkeypatch.setattr(title, "create_chat_model", factory)
    return steps


def _spoofed_chat_run(studio, form: str) -> dict:
    c = studio.client
    thread = c.post("/api/threads", json={})
    assert thread.status_code == 200, thread.text
    tid = thread.json()["thread_id"]
    body = {"assistant_id": "lead_agent", "input": {"messages": [{"role": "human", "content": "Set up the launch, please"}]}}
    if form == "configurable":
        body["config"] = {"configurable": {"thread_id": tid, **SPOOF}}
        body["metadata"] = dict(SPOOF)
    else:
        body["context"] = dict(SPOOF)
    resp = c.post(f"/api/threads/{tid}/runs/wait", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _ledger_pending(studio) -> list[dict]:
    return [a for a in studio.client.get("/api/confirmations").json()["actions"] if a["tool_name"] == "ledger_apply"]


def _grant_everything_to_the_lead(studio) -> None:
    c = studio.client
    version = c.get("/api/studio/agents/lead_agent/autonomy").json()["version"]
    assert c.put("/api/studio/agents/lead_agent/autonomy", json={"granted": ["tasks", "notes", "archive"], "base_version": version}).status_code == 200


@pytest.mark.parametrize("form", ["configurable", "context"])
def test_a_chat_run_carrying_synthetic_trigger_still_asks_for_every_tier_3_call(studio, scripted, form) -> None:
    _grant_everything_to_the_lead(studio)
    assert studio.client.post("/api/ledger/projects", json={"name": "Launch"}).status_code == 201
    scripted += [
        _call([{"op": "create_project", "name": "Spoofed"}], "c1"),
        _call([{"op": "create_goal", "project": "Launch", "title": "G"}], "c2"),
        _call([{"op": "link_thread", "project": "Launch"}], "c3"),
        _call([{"op": "create_task", "project": "Launch", "title": "Mixed"}, {"op": "create_project", "name": "Also"}], "c4"),
    ]
    _spoofed_chat_run(studio, form)
    assert [p["name"] for p in studio.client.get("/api/ledger/projects").json()] == ["Launch"]
    assert len(_ledger_pending(studio)) == 4
    assert studio.client.get("/api/studio/agents/lead_agent/grant-uses").json() == []


@pytest.mark.parametrize("form", ["configurable", "context"])
def test_a_chat_run_carrying_synthetic_trigger_is_treated_as_the_chat_it_is(studio, scripted, form) -> None:
    """No grants: if the marker were honoured, the routine write would be held
    as a scheduled one; as a chat it runs and is disclosed."""
    assert studio.client.post("/api/ledger/projects", json={"name": "Launch"}).status_code == 201
    scripted.append(_call([{"op": "create_task", "project": "Launch", "title": "From chat"}], "c1"))
    _spoofed_chat_run(studio, form)
    assert _ledger_pending(studio) == []
    [project] = studio.client.get("/api/ledger/projects").json()
    assert [t["title"] for t in studio.client.get(f"/api/ledger/projects/{project['id']}").json()["tasks"]] == ["From chat"]
