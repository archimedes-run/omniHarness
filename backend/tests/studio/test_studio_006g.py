"""Agent & Skill Studio redesign (006-G): the server pieces beside tool access.

Through the production gateway (`studio`: create_app() + lifespan, auth on):
  * a one-sentence draft suggests integrations, only ones this install has;
  * "Draft emails (never sends)" is a grantable, reversible class: on a
    schedule an agent set up with an allowlist drafts only under its grant; an
    agent saved before 006-G behaves exactly as on main; chat is unchanged;
    a granted draft is listed in the run summary but never "undone" there;
  * a skill's icon and colour are validated; its test results are saved with
    it, from what the test route observed;
  * the agent runs view says the engine's quiet hours.
"""

from __future__ import annotations

import json

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from app.policy.lineage import user_turn

DRAFT = "connector-gmail_GMAIL_CREATE_EMAIL_DRAFT"
DRAFTED: list[dict] = []


@tool(DRAFT)
def gmail_draft(to: str, body: str) -> str:
    """Save an email draft (Tier 2, reversible, in the shipped rules)."""
    DRAFTED.append({"to": to, "body": body})
    return f"draft saved for {to}"


class ToolCapableFake(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _draft_call(call_id: str = "d1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": DRAFT, "args": {"to": "sam@example.com", "body": "Friday works."}, "id": call_id}])


def _run(studio, agent: str, *, scheduled: bool, firing: str = "fire-d"):
    from app.policy.provenance import FIRING_KEY, PROVENANCE_KEY, RULE_KEY, SYNTHETIC
    from omniharness.agents.middlewares.policy_hook import build_policy_middleware
    from omniharness.config import get_app_config

    config = get_app_config()
    model = ToolCapableFake(messages=iter([_draft_call(), AIMessage(content="Done."), AIMessage(content="unused")]))
    built = create_agent(model=model, tools=[gmail_draft], middleware=[build_policy_middleware(config)])
    context = {"thread_id": f"t-{agent}", "user_id": studio.user_id, "agent_name": agent}
    if scheduled:
        context |= {PROVENANCE_KEY: SYNTHETIC, RULE_KEY: f"{agent}-sched", FIRING_KEY: firing}
    return built.invoke({"messages": [user_turn("Morning run")]}, context=context, config={"recursion_limit": 50})


def _agent(studio, name: str, *, allowlist: bool) -> None:
    body = {"name": name, "soul": "s"}
    if allowlist:
        body["tools"] = {"integrations": ["connector:GMAIL"], "tools": [DRAFT]}
    assert studio.client.post("/api/agents", json=body).status_code == 201


def _grant(studio, agent: str, granted: list[str]) -> None:
    version = studio.client.get(f"/api/studio/agents/{agent}/autonomy").json()["version"]
    resp = studio.client.put(f"/api/studio/agents/{agent}/autonomy", json={"granted": granted, "base_version": version})
    assert resp.status_code == 200, resp.text


def _waiting(studio) -> list[dict]:
    return [a for a in studio.client.get("/api/confirmations").json()["actions"] if a["tool_name"] == DRAFT]


# -- the drafts grant ---------------------------------------------------------------


def test_drafts_is_a_grantable_reversible_class(studio) -> None:
    _agent(studio, "inbox", allowlist=True)
    view = studio.client.get("/api/studio/agents/inbox/autonomy").json()
    [drafts] = [c for c in view["classes"] if c["id"] == "drafts"]
    assert drafts["grantable"] is True and "never sends" in drafts["label"]


def test_on_a_schedule_an_allowlist_agent_drafts_only_under_its_grant(studio) -> None:
    DRAFTED.clear()
    _agent(studio, "inbox", allowlist=True)
    _run(studio, "inbox", scheduled=True)
    assert DRAFTED == [], "an ungranted scheduled draft ran on its own"
    assert len(_waiting(studio)) == 1


def test_with_the_drafts_grant_the_scheduled_draft_runs_and_is_recorded(studio) -> None:
    DRAFTED.clear()
    _agent(studio, "inbox", allowlist=True)
    _grant(studio, "inbox", ["drafts"])
    _run(studio, "inbox", scheduled=True, firing="fire-granted")
    assert DRAFTED == [{"to": "sam@example.com", "body": "Friday works."}]
    [use] = studio.client.get("/api/studio/agents/inbox/grant-uses").json()
    assert (use["tool"], use["classes"]) == (DRAFT, ["drafts"])
    summary = studio.client.get(f"/api/studio/runs/{use['firing_id']}").json()
    [write] = summary["writes"]
    assert write["undoable"] is False and summary["all_undone"] is True
    # Nothing a ledger undo could revert, so Undo all has nothing to do.
    assert studio.client.post(f"/api/studio/runs/{use['firing_id']}/undo", json={}).status_code == 409


def test_an_agent_saved_before_006g_drafts_on_a_schedule_as_on_main(studio) -> None:
    DRAFTED.clear()
    _agent(studio, "legacy", allowlist=False)
    _run(studio, "legacy", scheduled=True)
    assert len(DRAFTED) == 1, "the drafts class changed an agent that has no allowlist"
    assert _waiting(studio) == []


def test_in_chat_drafting_is_unchanged(studio) -> None:
    DRAFTED.clear()
    _agent(studio, "inbox", allowlist=True)
    _run(studio, "inbox", scheduled=False)
    assert len(DRAFTED) == 1 and _waiting(studio) == []


# -- a draft suggests integrations ---------------------------------------------------------


def test_a_draft_suggests_only_integrations_this_install_has(studio, fake_model) -> None:
    reply = {
        "display_name": "Researcher",
        "description": "Digs into a question",
        "instructions": "You research.",
        "tool_groups": [],
        "skills": [],
        "integrations": ["builtin:web", "connector:GMAIL", "local:nowhere"],
    }
    fake_model.replies.append(json.dumps(reply))
    body = studio.client.post("/api/drafts/agent", json={"sentence": "research things on the web"}).json()
    # No Gmail connection and no such server here: only the web is suggested.
    assert body["agent"]["integrations"] == ["builtin:web"]
    assert {"connector:GMAIL", "local:nowhere"} <= set(body["dropped"])


# -- a skill's icon, colour and saved tests -------------------------------------------------


SKILL_MD = "---\nname: status-format\ndescription: Use when reporting the status of a project.\n---\n\n# Status\n"


def _skill(studio, allow_scans) -> None:
    assert studio.client.post("/api/skills/custom", json={"name": "status-format", "content": SKILL_MD}).status_code == 201


def test_a_skills_icon_and_colour_are_validated(studio, allow_scans) -> None:
    _skill(studio, allow_scans)
    ok = studio.client.put("/api/skills/custom/status-format/studio", json={"icon": "list", "color": 6})
    assert ok.status_code == 200 and (ok.json()["icon"], ok.json()["color"]) == ("list", 6)
    assert studio.client.put("/api/skills/custom/status-format/studio", json={"icon": "../evil", "color": 6}).status_code == 422
    assert studio.client.put("/api/skills/custom/status-format/studio", json={"icon": "list", "color": 9}).status_code == 422
    assert studio.client.get("/api/skills/custom/status-format/studio").json()["icon"] == "list"
    assert studio.client.put("/api/skills/custom/nope/studio", json={"icon": "list"}).status_code == 404


def test_test_results_are_saved_with_the_skill_from_what_was_observed(studio, allow_scans, monkeypatch) -> None:
    import omniharness.models as models

    _skill(studio, allow_scans)
    read = AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"path": "/mnt/skills/custom/status-format/SKILL.md"}, "id": "r"}])
    replies = iter([read, AIMessage(content="no"), read])

    class Fake(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    monkeypatch.setattr(models, "create_chat_model", lambda **_: Fake(messages=replies))
    unsaved = studio.client.post("/api/skills/status-format/test", json={"message": "just looking", "tries": 1, "save": False})
    assert unsaved.status_code == 200
    resp = studio.client.post("/api/skills/status-format/test", json={"message": "Where are we on judging?", "save": True, "tries": 2})
    assert resp.status_code == 200, resp.text
    [saved] = studio.client.get("/api/skills/custom/status-format/studio").json()["tests"]
    assert (saved["message"], saved["loaded"], saved["total"]) == ("Where are we on judging?", 1, 2)
    assert [t["loaded"] for t in saved["tries"]] == [False, True]
    gone = studio.client.delete("/api/skills/custom/status-format/tests", params={"message": "Where are we on judging?"})
    assert gone.status_code == 200 and gone.json()["tests"] == []


# -- quiet hours -----------------------------------------------------------------


def test_the_runs_view_says_the_engines_quiet_hours(studio) -> None:
    (studio.tmp / "rules.json").write_text(json.dumps({"quiet_hours": {"enabled": True, "start": "22:00", "end": "07:00", "timezone": "America/New_York"}, "rules": []}))
    (studio.tmp / "triggers").mkdir(exist_ok=True)
    assert studio.client.post("/api/agents", json={"name": "wrap-up"}).status_code == 201
    quiet = studio.client.get("/api/studio/agents/wrap-up/runs").json()["quiet_hours"]
    assert quiet == {"enabled": True, "start": "22:00", "end": "07:00", "timezone": "America/New_York"}
