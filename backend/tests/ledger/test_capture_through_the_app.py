"""Capture from chat, end to end through the production composition (US1, T022).

A real agent proposes ledger_apply; the policy layer built by the builder the
gateway registers at startup states it as a pending action; the user confirms
(or edits and confirms) through the real HTTP route; the project is read back
from /api/ledger. Nothing is stored before the confirmation (FR-009).
"""

from __future__ import annotations

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage

CHANGES = [
    {"op": "create_project", "ref": "p", "name": "Beta launch", "why": "Ship the public beta by Dec 1"},
    {"op": "create_goal", "project": "p", "title": "Public beta live", "definition_of_done": "Anyone can sign up", "target_date": "2026-12-01"},
    {"op": "create_task", "project": "p", "title": "Landing page", "due_date": "2026-11-01"},
    {"op": "create_task", "project": "p", "title": "Waitlist"},
]


class ToolCapableFake(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def propose(gateway, changes=CHANGES, said: str = "I'm launching the beta by Dec 1"):
    """One chat turn whose model proposes ledger_apply, as the lead agent would."""
    from omniharness.agents.middlewares.policy_hook import build_policy_middleware
    from omniharness.config import get_app_config
    from omniharness.tools.tools import get_available_tools

    config = get_app_config()
    tools = [t for t in get_available_tools(app_config=config, include_mcp=False) if t.name in ("ledger_apply", "ledger_read")]
    assert {t.name for t in tools} == {"ledger_apply", "ledger_read"}, "startup did not register the ledger controller"
    middleware = build_policy_middleware(config)
    assert middleware is not None, "startup did not install the policy layer"
    model = ToolCapableFake(messages=iter([AIMessage(content="", tool_calls=[{"name": "ledger_apply", "args": {"changes": changes}, "id": "c1"}]), AIMessage(content="I've proposed it.")]))
    agent = create_agent(model=model, tools=tools, middleware=[middleware])
    agent.invoke({"messages": [HumanMessage(content=said)]}, config={"configurable": {"thread_id": "thread-1"}}, context={"thread_id": "thread-1", "user_id": gateway.user_id})


def pending(gateway) -> list[dict]:
    resp = gateway.client.get("/api/confirmations")
    assert resp.status_code == 200, resp.text
    return [a for a in resp.json()["actions"] if a["tool_name"] == "ledger_apply"]


def test_a_proposed_project_is_stored_only_after_confirmation(gateway) -> None:
    propose(gateway)
    assert gateway.client.get("/api/ledger/projects").json() == [], "something was stored before the user confirmed"

    [action] = pending(gateway)
    # FR-010: the card lists exactly the changes, rendered from the arguments.
    assert action["targets"] == [
        "Create project “Beta launch” — Ship the public beta by Dec 1",
        "Add goal “Public beta live” to p, target 2026-12-01: done when Anyone can sign up",
        "Add task “Landing page” to p, due 2026-11-01",
        "Add task “Waitlist” to p",
    ]
    assert action["arguments"] == {"changes": CHANGES}

    resp = gateway.client.post(f"/api/confirmations/{action['id']}/confirm", json={})
    assert resp.json()["outcome"] == "executed", resp.text

    [project] = gateway.client.get("/api/ledger/projects").json()
    assert (project["name"], project["open_tasks"]) == ("Beta launch", 2)
    view = gateway.client.get(f"/api/ledger/projects/{project['id']}").json()
    assert [t["short_id"] for t in view["tasks"]] == ["T-1", "T-2"]
    assert view["goals"][0]["target_date"] == "2026-12-01"


def test_an_edited_plan_is_what_is_stored_and_the_original_never_runs(gateway) -> None:
    propose(gateway)
    [action] = pending(gateway)
    edited = [dict(c) for c in CHANGES]
    edited[0]["name"] = "Public beta"
    edited = edited[:1] + edited[2:3]  # keep the project and one task

    resp = gateway.client.post(f"/api/confirmations/{action['id']}/edit", json={"arguments": {"changes": edited}})
    assert resp.json()["outcome"] == "executed", resp.text
    assert resp.json()["detail"]["replaced"] == action["id"]

    [project] = gateway.client.get("/api/ledger/projects").json()
    assert (project["name"], project["open_tasks"]) == ("Public beta", 1)
    assert pending(gateway) == [], "the original plan is still open"


def test_a_declined_plan_writes_nothing(gateway) -> None:
    propose(gateway)
    [action] = pending(gateway)
    assert gateway.client.post(f"/api/confirmations/{action['id']}/decline", json={}).json()["outcome"] == "declined"
    assert gateway.client.get("/api/ledger/projects").json() == []


def test_an_invalid_plan_writes_nothing_at_all(gateway) -> None:
    """All or nothing: the third change names a project that does not exist."""
    propose(gateway, changes=[CHANGES[0], CHANGES[2], {"op": "create_task", "project": "Nope", "title": "x"}])
    [action] = pending(gateway)
    resp = gateway.client.post(f"/api/confirmations/{action['id']}/confirm", json={})
    assert gateway.client.get("/api/ledger/projects").json() == [], resp.text
