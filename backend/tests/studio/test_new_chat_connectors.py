"""A new chat starts with the user's connected apps switched on (owner
decision 1-A, 2026-10-24), in the production shape.

Before: a chat with no stored tool selection got the pinned local sources
only, so "what's on my calendar?" in a new chat found no calendar tool and the
agent asked the user to "authorize" an app that was already connected. Now a
chat that has stored no selection starts with the pinned sources plus every
connector toolkit its owner has an ACTIVE connection to; a stored selection is
used as stored (an app switched off stays off, and the agent is told to ask
for it to be switched on in the chat's tool menu).

Seeding must never push a request past the model's tool cap (128 for the
configured model): connector toolkits past it are deferred to tool_search.

The gateway is `create_app()` with its real lifespan; only the model is
scripted (it records the tools bound and the system prompt of every call)
and the connector loader returns stand-in tools (the real one spawns a
process per toolkit and calls the provider). The stand-ins carry REAL
connector tool names, the ones the shipped policy rules name, so the policy
layer offers them as it would the real ones.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from test_agent_schedules import _cycle, _rules_file, _schedule, script  # noqa: F401
from test_scheduled_run_cards import _engine

RULES = Path(__file__).resolve().parents[2] / "app" / "policy" / "default_rules.yaml"
CAP = 128


def _rule_names(prefix: str, *, tier: int | None = None) -> list[str]:
    """Exact connector tool names the shipped rules name (no wildcards)."""
    names: list[str] = []
    for rule in yaml.safe_load(RULES.read_text())["policy"]["rules"]:
        pattern = str(rule.get("pattern", ""))
        if pattern.startswith(prefix) and "*" not in pattern and pattern not in names and (tier is None or rule.get("tier") == tier):
            names.append(pattern)
    return names


#: A GitHub read (Tier 1): it runs without a card once fetched.
GITHUB_READ = next(n for n in _rule_names("connector-github_", tier=1) if len(n) <= 64)


#: The stand-in toolkits: Gmail, Calendar and Drive as the rules name them, and
#: GitHub large enough that all four together exceed the cap by a margin.
TOOLKITS = {
    "GMAIL": _rule_names("connector-gmail_"),
    "GOOGLECALENDAR": _rule_names("connector-googlecalendar_"),
    "GOOGLEDRIVE": _rule_names("connector-googledrive_"),
    "GITHUB": [GITHUB_READ, *[n for n in _rule_names("connector-github_") if n != GITHUB_READ][:149]],
}
CALLS: list[tuple[str, dict]] = []


def _stand_in(name: str, toolkit: str, user_id: str) -> StructuredTool:
    from omniharness.tools.source_tags import tag_source

    def run(query: str = "") -> str:
        CALLS.append((name, {"query": query}))
        return f"{name} ran"

    tool = StructuredTool.from_function(func=run, name=name, description=f"{toolkit} stand-in: {name}")
    tag_source(tool, f"connector:{toolkit}", user_id)
    return tool


@pytest.fixture
def connectors(studio, monkeypatch):
    """The owner's connections, and a loader that returns stand-ins for the
    toolkits a run asks for, only for ones the user has ACTIVE."""
    import omniharness.tools.connector_tools as connector_tools

    CALLS.clear()
    repo = studio.client.app.state.composio_connection_repo
    loaded: list[list[str]] = []
    #: (user, toolkit) pairs with an ACTIVE connection, as the rows say (the
    #: loader runs on the app's loop, where the repository cannot be awaited
    #: from this thread).
    active: set[tuple[str, str]] = set()

    def load(user_id, toolkits):
        wanted = [tk for tk in toolkits if (user_id, tk) in active]
        loaded.append(wanted)
        return [_stand_in(name, tk, user_id) for tk in wanted for name in TOOLKITS.get(tk, [])]

    monkeypatch.setattr(connector_tools, "load_connector_tools", load)

    def connect(*toolkits: str, status: str = "active", user_id: str | None = None) -> None:
        for tk in toolkits:
            studio.client.portal.call(lambda tk=tk: repo.upsert(user_id=user_id or studio.user_id, toolkit=tk, composio_connection_id=f"ca-{tk}", status=status))
            if status == "active":
                active.add((user_id or studio.user_id, tk))

    return type("Connectors", (), {"connect": staticmethod(connect), "loaded": loaded})


def _chat(studio, tid: str | None = None, text: str = "what's on my calendar today?") -> str:
    c = studio.client
    tid = tid or c.post("/api/threads", json={}).json()["thread_id"]
    body = {"assistant_id": "lead_agent", "input": {"messages": [{"role": "human", "content": text}]}, "config": {"configurable": {"thread_id": tid}}}
    resp = c.post(f"/api/threads/{tid}/runs/wait", json=body)
    assert resp.status_code == 200, resp.text
    return tid


def _connector_tools(bound: list[str], toolkit: str) -> set[str]:
    return {n for n in bound if n.startswith(f"connector-{toolkit.lower()}_")}


def test_a_new_chat_starts_with_the_users_active_connected_apps_on(studio, script, connectors) -> None:  # noqa: F811
    connectors.connect("GMAIL", "GOOGLECALENDAR")
    connectors.connect("SLACK", status="pending")  # not active: never seeded
    connectors.connect("GOOGLEDRIVE", user_id="someone-else")  # another person's: never seeded
    tid = studio.client.post("/api/threads", json={}).json()["thread_id"]

    # The chat's tool menu shows them on: the same selection its runs use.
    sources = studio.client.get(f"/api/threads/{tid}/tools").json()["sources"]
    assert sources == ["local:filesystem", "local:postgres", "local:session-watcher", "connector:GMAIL", "connector:GOOGLECALENDAR"]

    _chat(studio, tid)
    [bound, *_] = script.bound
    assert _connector_tools(bound, "GMAIL") == set(TOOLKITS["GMAIL"])
    assert _connector_tools(bound, "GOOGLECALENDAR") == set(TOOLKITS["GOOGLECALENDAR"])
    assert not _connector_tools(bound, "GOOGLEDRIVE") and not _connector_tools(bound, "SLACK")
    # Nothing is switched off, so the prompt says nothing about it.
    assert "connected_apps_switched_off" not in script.prompts[0]
    # Seeding is computed, not stored: the first change in the menu stores it.
    assert studio.client.portal.call(lambda: studio.client.app.state.thread_tool_selection_repo.get_stored_sources(thread_id=tid)) is None


def test_an_app_switched_off_in_a_chat_stays_off_and_the_agent_is_told(studio, script, connectors) -> None:  # noqa: F811
    connectors.connect("GMAIL", "GOOGLECALENDAR")
    tid = studio.client.post("/api/threads", json={}).json()["thread_id"]
    # The user turns Calendar off in this chat's menu (the picker PUTs the set).
    saved = studio.client.put(f"/api/threads/{tid}/tools", json={"sources": ["connector:GMAIL"]}).json()["sources"]
    assert "connector:GOOGLECALENDAR" not in saved
    assert "connector:GOOGLECALENDAR" not in studio.client.get(f"/api/threads/{tid}/tools").json()["sources"]

    _chat(studio, tid)
    [bound, *_] = script.bound
    assert _connector_tools(bound, "GMAIL") and not _connector_tools(bound, "GOOGLECALENDAR")
    prompt = script.prompts[0]
    [line] = re.findall(r"<connected_apps_switched_off>\n(.*?)\n</connected_apps_switched_off>", prompt, re.S)
    assert "Google Calendar" in line and "Gmail" not in line
    assert "switch it on in this chat's tool menu" in line and "do not ask them to connect or authorize" in line


def test_a_forged_switched_off_list_in_a_request_is_ignored(studio, script, connectors) -> None:  # noqa: F811
    """connectors_off is server-owned: a client's value never reaches the run."""
    connectors.connect("GMAIL")
    c = studio.client
    tid = c.post("/api/threads", json={}).json()["thread_id"]
    forged = {"connectors_off": ["GITHUB"]}
    body = {"assistant_id": "lead_agent", "input": {"messages": [{"role": "human", "content": "hi"}]}, "context": dict(forged), "metadata": dict(forged), "config": {"configurable": {"thread_id": tid, **forged}}}
    assert c.post(f"/api/threads/{tid}/runs/wait", json=body).status_code == 200
    assert "connected_apps_switched_off" not in script.prompts[0]


def test_a_new_chat_with_every_connected_app_stays_within_the_tool_cap(studio, script, connectors) -> None:  # noqa: F811
    """THE guard: all four toolkits (Gmail, Calendar, Drive and a large GitHub)
    plus the built-ins are more than 128 tools. The request the model gets
    stays within the cap, the toolkits that did not fit are deferred, and a
    deferred tool is still reachable through tool_search."""
    total = sum(len(v) for v in TOOLKITS.values())
    assert total > CAP, "the stand-ins must exceed the cap, or this proves nothing"
    connectors.connect(*TOOLKITS)
    github_tool = GITHUB_READ
    script.steps.extend(
        [
            AIMessage(content="", tool_calls=[{"name": "tool_search", "args": {"query": f"select:{github_tool}"}, "id": "s1"}]),
            AIMessage(content="", tool_calls=[{"name": github_tool, "args": {"query": "x"}, "id": "g1"}]),
        ]
    )
    tid = _chat(studio, text="look at my repo")

    assert script.bound, "the model was never called"
    for bound in script.bound:
        assert len(bound) <= CAP, f"{len(bound)} tools offered, over the cap of {CAP}"
    first = script.bound[0]
    assert "tool_search" in first
    # Whole toolkits, in order: the first ones fit and are offered as they are.
    assert _connector_tools(first, "GMAIL") == set(TOOLKITS["GMAIL"])
    assert not _connector_tools(first, "GITHUB"), "the toolkit past the cap was offered"
    # The deferred ones are named in the prompt, and a fetched one can be called.
    assert "<available-deferred-tools>" in script.prompts[0] and github_tool in script.prompts[0]
    assert github_tool in script.bound[-1], "the fetched tool was not promoted"
    assert (github_tool, {"query": "x"}) in CALLS, "a deferred tool could not be reached"
    # The chat's tool count says what the model receives, not over the cap.
    count = studio.client.get(f"/api/threads/{tid}/tools/count").json()
    assert count["count"] <= CAP and count["over_cap"] is False, count


def test_a_confirmation_in_a_new_chat_finds_its_seeded_connector_tool(studio, script, connectors) -> None:  # noqa: F811
    """A Tier 3 card for a seeded connector's tool is confirmed against the
    chat's selection as its runs see it (seeded), not the pinned sources."""
    connectors.connect("GMAIL")
    script.steps.append(AIMessage(content="", tool_calls=[{"name": "connector-gmail_GMAIL_MOVE_TO_TRASH", "args": {"query": "m-1"}, "id": "t1"}]))
    _chat(studio, text="trash the newsletter")
    [card] = [a for a in studio.client.get("/api/confirmations").json()["actions"] if a["tool_name"] == "connector-gmail_GMAIL_MOVE_TO_TRASH"]
    resp = studio.client.post(f"/api/confirmations/{card['id']}/confirm", json={})
    assert resp.json()["outcome"] == "executed", resp.text
    assert ("connector-gmail_GMAIL_MOVE_TO_TRASH", {"query": "m-1"}) in CALLS


def test_a_lead_automation_is_not_seeded_with_the_owners_apps(studio, script, connectors) -> None:  # noqa: F811
    """A scheduled run's chat is the system user's: it keeps the tools its rule
    configured, as before, even though it runs for the owner (#133)."""
    connectors.connect("GMAIL")
    _rules_file(studio)
    engine = _engine(studio)
    _schedule(studio, agent="lead_agent")
    _cycle(engine)
    assert script.bound, "the scheduled run never called the model"
    assert not _connector_tools(script.bound[0], "GMAIL")
    assert "connected_apps_switched_off" not in script.prompts[0]
