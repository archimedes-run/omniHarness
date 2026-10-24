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
    {"op": "create_goal", "ref": "g", "project": "p", "title": "Public beta live", "definition_of_done": "Anyone can sign up", "target_date": "2026-12-01"},
    {"op": "create_task", "project": "p", "goal": "g", "title": "Landing page", "due_date": "2026-11-01"},
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
    # The chat exists, as every chat a real run proposes in does: a card whose
    # chat does not exist (deleted) is refused at confirmation.
    created = gateway.client.post("/api/threads", json={"thread_id": "thread-1"})
    assert created.status_code in (200, 409), created.text
    return agent.invoke({"messages": [HumanMessage(content=said)]}, config={"configurable": {"thread_id": "thread-1"}}, context={"thread_id": "thread-1", "user_id": gateway.user_id})


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
        "Add goal “Public beta live” to “Beta launch”, target 2026-12-01: done when Anyone can sign up",
        "Add task “Landing page” to “Beta launch”, under goal “Public beta live”, due 2026-11-01",
        "Add task “Waitlist” to “Beta launch”",
    ]
    assert action["arguments"] == {"changes": CHANGES}

    resp = gateway.client.post(f"/api/confirmations/{action['id']}/confirm", json={})
    assert resp.json()["outcome"] == "executed", resp.text

    [project] = gateway.client.get("/api/ledger/projects").json()
    assert (project["name"], project["open_tasks"]) == ("Beta launch", 2)
    view = gateway.client.get(f"/api/ledger/projects/{project['id']}").json()
    assert [t["short_id"] for t in view["tasks"]] == ["T-1", "T-2"]
    assert view["goals"][0]["target_date"] == "2026-12-01"
    # The task named under the goal counts toward it.
    assert view["goals"][0]["progress"] == {"done": 0, "total": 1}
    # The project links to the chat it was captured in (US1).
    assert [(link["to_kind"], link["to_ref"]) for link in view["links"]] == [("thread", "thread-1")]
    # Times carry their zone, so a browser does not read UTC as local.
    assert project["updated_at"].endswith("+00:00")


def test_an_edited_plan_is_what_is_stored_and_the_original_never_runs(gateway) -> None:
    propose(gateway)
    [action] = pending(gateway)
    edited = [dict(c) for c in CHANGES]
    edited[0]["name"] = "Public beta"
    # Keep the project and one task, without the goal it named (also removed).
    edited = edited[:1] + [{k: v for k, v in edited[2].items() if k != "goal"}]

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


def test_an_invalid_plan_is_refused_before_its_card_and_writes_nothing(gateway) -> None:
    """A plan that could not be applied is never put on a card (the user would
    approve it and then see it fail): the third change names a project that
    does not exist, so the model is told why, and nothing is proposed or
    written."""
    out = propose(gateway, changes=[CHANGES[0], CHANGES[3], {"op": "create_task", "project": "Nope", "title": "x"}])
    assert pending(gateway) == [], "an invalid plan became a card"
    assert gateway.client.get("/api/ledger/projects").json() == []
    [result] = [m for m in out["messages"] if getattr(m, "type", "") == "tool"]
    assert "Nothing was proposed or changed" in str(result.content) and "there is no project 'Nope'" in str(result.content)
    # The refusal is the harness's own words about the call (as a plan is), so
    # it does not taint the turn: the model's corrected plan is not a
    # "suggestion".
    from app.policy.lineage import TRUSTED_ACK_MARKER

    assert result.additional_kwargs.get(TRUSTED_ACK_MARKER) is True


def test_a_plan_sent_as_text_is_refused_before_its_card(gateway) -> None:
    """`changes` as a JSON string, not a list: the predicate cannot see its ops
    (so it is Tier 3, fail-safe) and the tool's schema would reject it after
    the user approved. It is refused to the model instead, with no card."""
    import json

    out = propose(gateway, changes=json.dumps(CHANGES))
    assert pending(gateway) == []
    assert gateway.client.get("/api/ledger/projects").json() == []
    [result] = [m for m in out["messages"] if getattr(m, "type", "") == "tool"]
    assert "must be a list" in str(result.content)


def test_an_invalid_edited_plan_is_refused_and_the_original_stays_open(gateway) -> None:
    """A plan edited on its card into one that cannot be applied (the third
    change names a project that does not exist) is checked before the
    original is superseded: nothing is written, and the original plan is
    still there to confirm or edit again."""
    propose(gateway)
    [action] = pending(gateway)
    edited = [CHANGES[0], {k: v for k, v in CHANGES[2].items() if k != "goal"}, {"op": "create_task", "project": "Nope", "title": "x"}]
    resp = gateway.client.post(f"/api/confirmations/{action['id']}/edit", json={"arguments": {"changes": edited}})
    assert resp.json()["outcome"] == "invalid_plan" and "there is no project 'Nope'" in resp.json()["message"], resp.text
    assert gateway.client.get("/api/ledger/projects").json() == [], resp.text
    assert [a["id"] for a in pending(gateway)] == [action["id"]]


def test_a_confirmed_plan_that_fails_logs_the_ledgers_reason(gateway, caplog) -> None:
    """A plan valid when proposed can still fail at apply (the ledger changed
    in between). The log says why, in the ledger's own words, not only the
    exception's type."""
    import logging

    made = gateway.client.post("/api/ledger/projects", json={"name": "Launch"}).json()
    task = gateway.client.post(f"/api/ledger/projects/{made['id']}/tasks", json={"title": "Ship"}).json()
    propose(gateway, changes=[{"op": "update_task", "project": "Launch", "task": "Ship", "status": "done"}], said="I shipped it")
    [action] = pending(gateway)
    # The task it was pinned to is removed before the user confirms.
    repo = gateway.client.app.state.ledger_service.repo
    with repo.transaction() as s:
        assert repo.remove(s, "task", task["id"], owner_id=None, actor="user", version=None)
    with caplog.at_level(logging.ERROR, logger="app.policy.confirm_flow"):
        resp = gateway.client.post(f"/api/confirmations/{action['id']}/confirm", json={})
    assert resp.json()["outcome"] == "failed", resp.text
    [line] = [r.getMessage() for r in caplog.records if "did not complete" in r.getMessage()]
    assert "RuntimeError" in line and "(ledger: the task this was proposed for (T-1) no longer exists)" in line


# -- re-review: changes naming rows the plan itself creates are never pinned ----


def _confirm_only_card(gateway) -> dict:
    [action] = pending(gateway)
    resp = gateway.client.post(f"/api/confirmations/{action['id']}/confirm", json={})
    assert resp.json()["outcome"] == "executed", resp.text
    return action


def _project_named(gateway, name: str) -> dict:
    [project] = [p for p in gateway.client.get("/api/ledger/projects").json() if p["name"] == name]
    return gateway.client.get(f"/api/ledger/projects/{project['id']}").json()


def test_a_task_in_a_project_the_plan_creates_by_name_applies_after_confirm(gateway) -> None:
    propose(gateway, changes=[{"op": "create_project", "name": "Alpha"}, {"op": "create_task", "project": "Alpha", "title": "First"}])
    action = _confirm_only_card(gateway)
    assert "_pin" not in action["arguments"]["changes"][1], "a pin to a row that only existed in the check"
    assert [t["title"] for t in _project_named(gateway, "Alpha")["tasks"]] == ["First"]


def test_an_update_of_a_task_the_plan_creates_applies_after_confirm(gateway) -> None:
    assert gateway.client.post("/api/ledger/projects", json={"name": "TEST P"}).status_code == 201
    propose(gateway, changes=[{"op": "create_task", "project": "TEST P", "title": "Newtask"}, {"op": "update_task", "project": "TEST P", "task": "Newtask", "status": "done"}])
    action = _confirm_only_card(gateway)
    assert "task_id" not in (action["arguments"]["changes"][1].get("_pin") or {})
    assert [(t["title"], t["status"]) for t in _project_named(gateway, "TEST P")["tasks"]] == [("Newtask", "done")]


def test_linking_a_project_the_plan_creates_applies_after_confirm(gateway) -> None:
    propose(gateway, changes=[{"op": "create_project", "name": "Beta"}, {"op": "link_thread", "project": "Beta"}])
    _confirm_only_card(gateway)
    links = _project_named(gateway, "Beta")["links"]
    assert ("thread", "thread-1") in [(link["to_kind"], link["to_ref"]) for link in links]
