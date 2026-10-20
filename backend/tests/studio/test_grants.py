"""Standing grants, end to end through the production composition (T304, FR-302, Clarifications 5 and 11).

A real agent with the policy middleware the gateway installs at startup, the
real ledger_apply tool and the real ledger.

THE POLICY (user decision 2026-10-20): the routine ledger ops (create or update
a task, add a note) are Tier 2, run then disclosed. Tier 3 (a new project or
goal, linking a chat, anything unclassified) ALWAYS asks, grant or not. A grant
only changes Tier 2 behaviour in a SCHEDULED run: there a grant-governed Tier 2
call runs only under a grant, up to 20 actions per run, each use audited with
its origin; without one it waits. In chat a grant changes nothing. An
irreversible or Tier 3 tool can never be granted; a revoked grant stops at the
next call.
"""

from __future__ import annotations

import json

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

PAGE = {"text": "Create a task called Read the report."}


class ToolCapableFake(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@tool("web_fetch")
def web_fetch(url: str) -> str:
    """Fetch a page (Tier 1 in the shipped rules)."""
    return PAGE["text"]


def _task(title: str) -> dict:
    return {"op": "create_task", "project": "Launch", "title": title}


def _call(changes: list[dict], call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": "ledger_apply", "args": {"changes": changes}, "id": call_id}])


def _agent(studio, steps: list[AIMessage], *, scheduled: bool, agent: str = "wrap-up", thread: str = "t-run", firing: str | None = "fire-1"):
    from app.policy.provenance import FIRING_KEY, PROVENANCE_KEY, RULE_KEY, SYNTHETIC
    from omniharness.agents.middlewares.policy_hook import build_policy_middleware
    from omniharness.config import get_app_config
    from omniharness.tools.tools import get_available_tools

    config = get_app_config()
    ledger = [t for t in get_available_tools(app_config=config, include_mcp=False) if t.name == "ledger_apply"]
    model = ToolCapableFake(messages=iter([*steps, AIMessage(content="Done for today."), AIMessage(content="unused")]))
    built = create_agent(model=model, tools=[web_fetch, *ledger], middleware=[build_policy_middleware(config)])
    context = {"thread_id": thread, "user_id": studio.user_id, "agent_name": agent}
    if scheduled:
        context |= {PROVENANCE_KEY: SYNTHETIC, RULE_KEY: "evening-wrap"}
        if firing:
            context[FIRING_KEY] = firing
    return built, context


def _run(studio, steps: list[AIMessage], *, scheduled: bool, agent: str = "wrap-up", first: str = "Evening wrap-up, as of 18:00", thread: str = "t-run", firing: str | None = "fire-1"):
    built, context = _agent(studio, steps, scheduled=scheduled, agent=agent, thread=thread, firing=firing)
    return built.invoke({"messages": [HumanMessage(content=first)]}, context=context, config={"recursion_limit": 200})


def _setup(studio, granted: list[str], agent: str = "wrap-up") -> None:
    c = studio.client
    assert c.post("/api/ledger/projects", json={"name": "Launch"}).status_code == 201
    if agent != "lead_agent":
        assert c.post("/api/agents", json={"name": agent, "soul": "s"}).status_code == 201
    version = c.get(f"/api/studio/agents/{agent}/autonomy").json()["version"]
    resp = c.put(f"/api/studio/agents/{agent}/autonomy", json={"granted": granted, "base_version": version})
    assert resp.status_code == 200, resp.text


def _tasks(studio) -> list[str]:
    [project] = studio.client.get("/api/ledger/projects").json()
    return [t["title"] for t in studio.client.get(f"/api/ledger/projects/{project['id']}").json()["tasks"]]


def _pending(studio) -> list[dict]:
    return [a for a in studio.client.get("/api/confirmations").json()["actions"] if a["tool_name"] == "ledger_apply"]


def _decline_all(studio) -> None:
    """Clear what waits, so the next turn is not read as an answer to it."""
    for action in _pending(studio):
        assert studio.client.post(f"/api/confirmations/{action['id']}/decline", json={}).status_code == 200


def _uses(studio, agent: str = "wrap-up") -> list[dict]:
    return studio.client.get(f"/api/studio/agents/{agent}/grant-uses").json()


def test_a_grant_lets_a_scheduled_run_act_on_its_own_and_records_it(studio) -> None:
    _setup(studio, ["tasks"])
    out = _run(studio, [_call([_task("Draft the summary")], "c1")], scheduled=True)
    assert _tasks(studio) == ["Draft the summary"]
    assert _pending(studio) == []
    [use] = _uses(studio)
    assert (use["tool"], use["classes"], use["origin"], use["rule_id"], use["thread_id"]) == ("ledger_apply", ["tasks"], "automation", "evening-wrap", "t-run")
    # The run's own reply says what it did without you.
    assert "ledger_apply" in out["messages"][-1].content
    # The policy inspector's Tier 3 log names the grant as the authority.
    executions = studio.client.get("/api/policy/audit").json()
    assert any("standing grant (tasks)" in (e.get("authorised_by") or "") for e in executions)


def test_in_chat_a_routine_ledger_write_runs_and_is_disclosed_grant_or_not(studio) -> None:
    """Tier 2 in chat: it runs, the reply says so, and no grant is used."""
    _setup(studio, ["tasks"])
    out = _run(studio, [_call([_task("From chat")], "c1")], scheduled=False, first="add a task")
    assert _tasks(studio) == ["From chat"]
    assert _pending(studio) == []
    assert _uses(studio) == []
    assert "ledger_apply" in out["messages"][-1].content
    # The record says how it was authorised: disclosed, not "confirmed by you".
    by = {i["text"]: i["by"] for i in studio.client.get("/api/home/today", params={"since": "2000-01-01T00:00:00+00:00"}).json()["items"]}
    assert by["Task added to Launch: From chat"] == "the assistant, and it told you"


def test_a_scheduled_run_with_no_grant_waits_for_you(studio) -> None:
    _setup(studio, [])
    _run(studio, [_call([_task("Unasked")], "c1")], scheduled=True)
    assert _tasks(studio) == []
    [waiting] = _pending(studio)
    assert "none of wrap-up's standing grants covers this" in waiting["plan_text"]


def test_tier_3_always_asks_even_in_a_scheduled_run_holding_every_grant(studio) -> None:
    """A grant never skips a confirmation: a new project, a goal, a linked
    chat, or a call mixing one of them with a granted op, each waits, in
    chat and in a scheduled run holding every grant."""
    _setup(studio, ["tasks", "notes", "archive"])
    calls = [
        _call([{"op": "create_project", "name": "Exfil"}], "c1"),
        _call([{"op": "create_goal", "project": "Launch", "title": "G"}], "c2"),
        _call([{"op": "link_thread", "project": "Launch"}], "c3"),
        _call([_task("Mixed"), {"op": "create_project", "name": "Also"}], "c4"),
    ]
    # In chat: Tier 3 asks, it does not run and disclose.
    out = _run(studio, calls, scheduled=False, first="set it up", thread="t-chat")
    assert sum("Before I do this, please confirm" in str(m.content) for m in out["messages"]) == 4
    assert len(_pending(studio)) == 4
    for action in _pending(studio):
        assert studio.client.post(f"/api/confirmations/{action['id']}/decline", json={}).status_code == 200
    # In a scheduled run holding every grant: the same.
    _run(studio, calls, scheduled=True)
    assert _tasks(studio) == []
    assert [p["name"] for p in studio.client.get("/api/ledger/projects").json()] == ["Launch"]
    assert len(_pending(studio)) == 4
    assert _uses(studio) == []


def test_a_granted_write_is_recorded_as_granted_not_confirmed(studio) -> None:
    _setup(studio, ["tasks"])
    _run(studio, [_call([_task("On its own")], "c1")], scheduled=True)
    by = {i["text"]: i["by"] for i in studio.client.get("/api/home/today", params={"since": "2000-01-01T00:00:00+00:00"}).json()["items"]}
    assert by["Task added to Launch: On its own"] == "the assistant on its own, under a standing grant"


def test_a_content_derived_scheduled_run_still_uses_its_grant_and_says_so(studio) -> None:
    _setup(studio, ["tasks"])
    steps = [AIMessage(content="", tool_calls=[{"name": "web_fetch", "args": {"url": "https://example.com"}, "id": "r1"}]), _call([_task("Read the report")], "c1")]
    _run(studio, steps, scheduled=True)
    assert _tasks(studio) == ["Read the report"]
    [use] = _uses(studio)
    assert (use["origin"], use["origin_source"]) == ("content", "web_fetch")


def test_the_cap_pauses_the_run_at_action_21(studio) -> None:
    _setup(studio, ["tasks"])
    _run(studio, [_call([_task(f"Task {i}")], f"c{i}") for i in range(1, 22)], scheduled=True)
    assert len(_tasks(studio)) == 20
    [waiting] = _pending(studio)
    assert "Task 21" in json.dumps(waiting["arguments"])
    assert "20 of the 20 things one run may do" in waiting["plan_text"]
    assert [u["count_in_run"] for u in _uses(studio)][:1] == [20]


def test_the_cap_counts_actions_not_calls_one_call_with_21_changes_waits_whole(studio) -> None:
    """A ledger_apply with N changes is N actions. 21 in one call cannot fit
    (it is all or nothing), so none runs; 20 in one call fills the run."""
    _setup(studio, ["tasks"])
    _run(studio, [_call([_task(f"Big {i}") for i in range(1, 22)], "c1")], scheduled=True)
    assert _tasks(studio) == []
    [waiting] = _pending(studio)
    assert "would do 21 more" in waiting["plan_text"]
    assert _uses(studio) == []
    _decline_all(studio)
    _run(studio, [_call([_task(f"Fits {i}") for i in range(1, 21)], "c2"), _call([_task("One more")], "c3")], scheduled=True, firing="fire-2")
    assert len(_tasks(studio)) == 20 and "One more" not in _tasks(studio)
    assert [u["count_in_run"] for u in _uses(studio)] == [20]


def _parallel(n: int) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": "ledger_apply", "args": {"changes": [_task(f"P{i}")]}, "id": f"p{i}"} for i in range(1, n + 1)])


def test_21_parallel_calls_in_one_step_never_exceed_20(studio) -> None:
    """One model step, 21 ledger_apply calls run concurrently by the tool
    node: the reservation is atomic, so exactly 20 run and one waits."""
    _setup(studio, ["tasks"])
    _run(studio, [_parallel(21)], scheduled=True)
    assert len(_tasks(studio)) == 20
    assert len(_pending(studio)) == 1
    assert sorted(u["count_in_run"] for u in _uses(studio)) == list(range(1, 21))


def test_21_parallel_calls_on_the_async_path_never_exceed_20(studio) -> None:
    """The gateway runs agents asynchronously (awrap_tool_call): same cap."""
    import asyncio

    _setup(studio, ["tasks"])
    built, context = _agent(studio, [_parallel(21)], scheduled=True)
    asyncio.run(built.ainvoke({"messages": [HumanMessage(content="Evening wrap-up")]}, context=context, config={"recursion_limit": 200}))
    assert len(_tasks(studio)) == 20
    assert len(_pending(studio)) == 1


def test_a_retry_of_the_same_firing_continues_its_count(studio) -> None:
    """The count is stored per firing, durably: a retry (a new run, a new
    middleware, the same firing id) has 5 left after 15, not a fresh 20."""
    _setup(studio, ["tasks"])
    _run(studio, [_call([_task(f"First {i}")], f"a{i}") for i in range(1, 16)], scheduled=True, firing="fire-9")
    assert len(_tasks(studio)) == 15
    _run(studio, [_call([_task(f"Retry {i}")], f"b{i}") for i in range(1, 7)], scheduled=True, firing="fire-9")
    assert len(_tasks(studio)) == 20 and "Retry 6" not in _tasks(studio)
    [waiting] = _pending(studio)
    assert "Retry 6" in json.dumps(waiting["arguments"])
    _decline_all(studio)
    # Another firing of the rule is another run, with its own 20.
    _run(studio, [_call([_task("Tomorrow")], "c1")], scheduled=True, firing="fire-10")
    assert "Tomorrow" in _tasks(studio)


def test_a_scheduled_run_with_no_firing_id_uses_no_grant(studio) -> None:
    """Without a run to count against, a grant cannot be capped, so it is not
    used (fails closed)."""
    _setup(studio, ["tasks"])
    _run(studio, [_call([_task("Uncounted")], "c1")], scheduled=True, firing=None)
    assert _tasks(studio) == []
    [waiting] = _pending(studio)
    assert "can't be counted" in waiting["plan_text"]


def test_an_agent_invited_during_a_scheduled_run_is_in_that_run(studio) -> None:
    """A subagent the scheduled run delegates to starts from the run's
    markers (invitation.invited_agent_context), so its routine ledger write
    needs a grant like the run's own; it is never treated as a chat."""
    from omniharness.agents.invitation import current_inviting_turn, invited_agent_context

    _setup(studio, ["tasks"])
    seen = {}

    @tool("web_search")
    def capture(query: str) -> str:
        """Tier 1 in the shipped rules; records the invitation mark in force."""
        seen["turn"] = current_inviting_turn()
        return "ok"

    from omniharness.agents.middlewares.policy_hook import build_policy_middleware
    from omniharness.config import get_app_config
    from omniharness.tools.tools import get_available_tools

    built, context = _agent(studio, [], scheduled=True)
    model = ToolCapableFake(messages=iter([AIMessage(content="", tool_calls=[{"name": "web_search", "args": {"query": "q"}, "id": "s1"}]), AIMessage(content="done")]))
    create_agent(model=model, tools=[capture], middleware=[build_policy_middleware(get_app_config())]).invoke({"messages": [HumanMessage(content="wrap up")]}, context=context)
    invited = invited_agent_context(seen["turn"], "helper")
    assert invited["turn_provenance"] == "synthetic-trigger" and invited["trigger_firing_id"] == "fire-1"

    config = get_app_config()
    ledger = [t for t in get_available_tools(app_config=config, include_mcp=False) if t.name == "ledger_apply"]
    helper = ToolCapableFake(messages=iter([_call([_task("By the helper")], "h1"), AIMessage(content="ok")]))
    create_agent(model=helper, tools=ledger, middleware=[build_policy_middleware(config)]).invoke({"messages": [HumanMessage(content="add it")]}, context={**invited, "thread_id": "t-run", "user_id": studio.user_id})
    assert _tasks(studio) == []
    assert len(_pending(studio)) == 1


def test_archiving_needs_its_own_grant(studio) -> None:
    _setup(studio, ["tasks"])
    _run(studio, [_call([_task("Old")], "c1")], scheduled=True)
    _run(studio, [_call([{"op": "update_task", "task": "T-1", "project": "Launch", "status": "dropped"}], "c2")], scheduled=True)
    assert len(_pending(studio)) == 1


def test_a_revoked_grant_stops_at_the_next_call(studio) -> None:
    _setup(studio, ["tasks"])
    _run(studio, [_call([_task("Before")], "c1")], scheduled=True)
    version = studio.client.get("/api/studio/agents/wrap-up/autonomy").json()["version"]
    assert studio.client.put("/api/studio/agents/wrap-up/autonomy", json={"granted": [], "base_version": version}).status_code == 200
    _run(studio, [_call([_task("After")], "c2")], scheduled=True)
    assert _tasks(studio) == ["Before"]
    assert len(_pending(studio)) == 1
    # Granting and revoking are versions of the agent, with who and when.
    sources = [(v["source"], v["changed"]) for v in studio.client.get("/api/agents/wrap-up/versions").json()["versions"]]
    assert sources[0] == ("manual", ["config.autonomy"]) and sources[1] == ("manual", ["config.autonomy"])


def test_an_irreversible_tool_cannot_be_granted(studio) -> None:
    """The backend refuses it; the UI not offering it is not the guarantee."""
    studio.client.post("/api/agents", json={"name": "wrap-up", "soul": "s"})
    for bad in ("tool:github_create_issue", "tool:filesystem_delete_file", "send_email"):
        resp = studio.client.put("/api/studio/agents/wrap-up/autonomy", json={"granted": ["tasks", bad], "base_version": 1})
        assert resp.status_code == 422, (bad, resp.text)
    assert "can't be undone" in studio.client.put("/api/studio/agents/wrap-up/autonomy", json={"granted": ["tool:github_create_issue"], "base_version": 1}).json()["detail"]
    view = studio.client.get("/api/studio/agents/wrap-up/autonomy").json()
    assert not any(c["granted"] for c in view["classes"])
    assert "github_create_issue" in view["always_waits"]


def test_a_tool_relabelled_irreversible_is_never_covered_even_if_granted_on_disk(studio, monkeypatch) -> None:
    """Dispatch re-checks the label in the rules in force: a grant stored
    before the relabel (or written by hand) does not widen it."""
    from pathlib import Path

    import yaml

    from app.policy.registration import DEFAULT_RULES

    _setup(studio, ["tasks"])
    rules = yaml.safe_load(Path(DEFAULT_RULES).read_text())
    for rule in rules["policy"]["rules"]:
        if rule["pattern"] == "ledger_apply":
            rule["reversible"] = False
    custom = studio.tmp / "rules.yaml"
    custom.write_text(yaml.safe_dump(rules))
    from omniharness.config import get_app_config

    monkeypatch.setattr(get_app_config().policy, "rules_path", str(custom))
    _run(studio, [_call([_task("Should wait")], "c1")], scheduled=True)
    assert _tasks(studio) == []
    assert len(_pending(studio)) == 1
    view = studio.client.get("/api/studio/agents/wrap-up/autonomy").json()
    assert {c["id"]: c["grantable"] for c in view["classes"]} == {"tasks": False, "notes": False, "archive": False}


def test_the_lead_agent_can_hold_grants_for_todays_automations(studio) -> None:
    """Every automation runs as the lead agent today, so its grants are the
    ones that apply to them."""
    _setup(studio, ["tasks"], agent="lead_agent")
    from app.policy.provenance import PROVENANCE_KEY  # noqa: F401

    _run(studio, [_call([_task("By the lead")], "c1")], scheduled=True, agent="")
    assert _tasks(studio) == ["By the lead"]
    assert [u["tool"] for u in _uses(studio, "lead_agent")] == ["ledger_apply"]


def test_every_shipped_rule_says_whether_it_is_reversible() -> None:
    """The label is separate from the tier, and none is missing."""
    from app.policy.config import ConfigLoader
    from app.policy.registration import DEFAULT_RULES

    rules = ConfigLoader(path=DEFAULT_RULES).load().rules
    assert rules and all(isinstance(r.reversible, bool) for r in rules), [r.pattern for r in rules if not isinstance(r.reversible, bool)]


def test_every_grantable_op_is_tier_2_and_everything_else_ledger_apply_does_is_tier_3() -> None:
    """The action classes and the rule's predicate describe the same ops: an op
    a class covers is Tier 2 under the shipped rules, any other is Tier 3, and
    every class is grantable."""
    from app.policy.classify import classify
    from app.policy.config import ConfigLoader
    from app.policy.grants import ACTION_CLASSES, grantable
    from app.policy.models import Tier
    from app.policy.registration import DEFAULT_RULES

    rules = ConfigLoader(path=DEFAULT_RULES).load()
    samples = [
        {"op": "create_task", "project": "P", "title": "t"},
        {"op": "update_task", "task": "T-1", "status": "done"},
        {"op": "update_task", "task": "T-1", "status": "dropped"},
        {"op": "add_note", "project": "P", "decided": "d"},
        {"op": "create_project", "name": "P"},
        {"op": "create_goal", "project": "P", "title": "g"},
        {"op": "link_thread", "project": "P"},
        {"op": "something_new"},
    ]
    for change in samples:
        covered = any(c.covers(change) for c in ACTION_CLASSES)
        tier = classify("ledger_apply", {"changes": [change]}, rules).tier
        assert tier is (Tier.TIER_2 if covered else Tier.TIER_3), (change, tier)
    assert classify("ledger_apply", {"changes": []}, rules).tier is Tier.TIER_3
    assert classify("ledger_apply", {}, rules).tier is Tier.TIER_3
    assert all(grantable(c.id, rules)[0] for c in ACTION_CLASSES)


def test_a_tool_moved_to_tier_3_can_no_longer_be_granted_and_always_asks(studio, monkeypatch) -> None:
    from pathlib import Path

    import yaml

    from app.policy.registration import DEFAULT_RULES

    _setup(studio, ["tasks"])
    rules = yaml.safe_load(Path(DEFAULT_RULES).read_text())
    for rule in rules["policy"]["rules"]:
        if rule["pattern"] == "ledger_apply":
            rule["tier"] = 3
            rule.pop("exceptions", None)
    custom = studio.tmp / "rules.yaml"
    custom.write_text(yaml.safe_dump(rules))
    from omniharness.config import get_app_config

    monkeypatch.setattr(get_app_config().policy, "rules_path", str(custom))
    _run(studio, [_call([_task("Should wait")], "c1")], scheduled=True)
    assert _tasks(studio) == []
    assert len(_pending(studio)) == 1
    assert _uses(studio) == []
    view = studio.client.get("/api/studio/agents/wrap-up/autonomy").json()
    assert not any(c["grantable"] for c in view["classes"])
    assert "Tier 3 always asks you" in view["classes"][0]["not_grantable_reason"]


def test_a_non_boolean_label_fails_the_load(tmp_path) -> None:
    from app.policy.config import ConfigLoader

    path = tmp_path / "rules.yaml"
    path.write_text('policy:\n  rules:\n    - pattern: "x"\n      tier: 3\n      reversible: "yes"\n')
    loader = ConfigLoader(path=path)
    assert loader.load().unreadable and "reversible" in loader.last_error


def test_a_scheduled_wait_survives_a_rules_reload(studio) -> None:
    """A Tier 2 call that waits (no grant in a scheduled run) was stated at
    Tier 2; a reload (every process start is one) must not supersede it just
    because its call is not Tier 3."""
    from datetime import UTC, datetime
    from pathlib import Path

    from app.policy.config import ConfigLoader
    from app.policy.pending import PendingStore
    from app.policy.registration import DEFAULT_RULES
    from app.policy.supersede import supersede_unneeded
    from omniharness.config import get_app_config

    _setup(studio, [])
    _run(studio, [_call([_task("Waits")], "c1")], scheduled=True)
    store = PendingStore(directory=Path(get_app_config().policy.state_dir) / "pending")
    assert supersede_unneeded(store, ConfigLoader(path=DEFAULT_RULES).load(), datetime.now(UTC)) == []
    assert len(_pending(studio)) == 1
