"""The chat builder end to end, through `create_app()` (Spec 010 Slice 2).

Assert on state, not status: every save test reads the store back.
"""

from __future__ import annotations

from builder_helpers import agent_history, agent_state, call, cards, history_records, make_agent, new_thread, offered, say, script

DRAFT_AGENT = {"kind": "agent", "name": "test-010-inbox", "fields": {"display_name": "Inbox triage", "description": "Triages my inbox", "instructions": "You triage the inbox every morning."}, "guessed": ["description"]}

OLD_TOOLS = {"setup_agent", "update_agent", "skill_manage"}
BUILDER = {"builder_draft", "builder_read", "builder_diff", "builder_save", "builder_grant", "builder_undo"}


def _build(gw, thread_id: str, draft: dict = DRAFT_AGENT, draft_id: str = "d-test-1") -> dict:
    script(gw, [call("builder_draft", draft, "c1")], [call("builder_save", {"draft_id": draft_id}, "c2")], "Here is the draft.")
    return say(gw, thread_id, "make me an agent that triages my inbox every morning")


def test_the_assistant_holds_the_builder_and_no_old_tool(gw) -> None:
    say(gw, new_thread(gw), "hello")
    tools = offered(gw.lead)
    assert BUILDER <= tools, tools
    assert not OLD_TOOLS & tools, f"FR-024: an old writer is on the model's tool list: {sorted(OLD_TOOLS & tools)}"


def test_draft_then_typed_yes_saves_version_1_from_chat(gw) -> None:
    thread_id = new_thread(gw)
    _build(gw, thread_id)
    # The draft is shown and nothing is written (FR-005, FR-010).
    assert agent_state(gw, "test-010-inbox") == (None, 0)
    [card] = cards(gw, "builder_save")
    assert card["thread_id"] == thread_id and card["confirmable_by_typing"] is True, card
    assert "New agent: Inbox triage" in card["plan_text"] and "description (guessed)" in card["plan_text"], card["plan_text"]
    state = gw.client.get(f"/api/threads/{thread_id}/builder").json()
    assert state["building"]["title"] == "Inbox triage" and state["building"]["saved_version"] is None, state

    script(gw, "Saved.")
    say(gw, thread_id, "yes")
    snapshot, version = agent_state(gw, "test-010-inbox")
    assert version == 1 and snapshot["soul"] == "You triage the inbox every morning.", (snapshot, version)
    [record] = history_records(gw, "test-010-inbox")
    assert record["source"] == "chat" and record["who"] == f"user:{gw.user_id}", record
    assert record["thread_id"] == thread_id and record["card_id"] == card["id"] and record["via"] == "chat", record
    assert gw.client.get("/api/agents/test-010-inbox").status_code == 200
    assert gw.client.get(f"/api/threads/{thread_id}/builder").json()["building"]["saved_version"] == 1


def test_every_word_of_the_closed_list_saves_and_nothing_else_does(gw) -> None:
    from app.policy.builder_rules import BUILDER_CONFIRM_FORMS

    assert BUILDER_CONFIRM_FORMS == {"yes", "y", "save", "apply", "do it", "go ahead"}
    thread_id = new_thread(gw)
    _build(gw, thread_id)
    # In the general list, and not in the builder's: a revision, not a yes.
    for text in ("sure", "ok", "yes but shorter", "yes 1"):
        script(gw, "Revising.")
        say(gw, thread_id, text)
        assert agent_state(gw, "test-010-inbox") == (None, 0), f"{text!r} saved a builder draft"
        assert len(cards(gw, "builder_save")) == 1, f"{text!r} answered the card"
    script(gw, "Saved.")
    say(gw, thread_id, "Go ahead!")
    assert agent_state(gw, "test-010-inbox")[1] == 1


def test_a_revision_replaces_the_card_and_only_the_new_draft_saves(gw) -> None:
    thread_id = new_thread(gw)
    _build(gw, thread_id)
    revised = {**DRAFT_AGENT, "fields": {**DRAFT_AGENT["fields"], "instructions": "Only on weekdays, not before 8."}}
    script(gw, [call("builder_draft", revised, "c3")], [call("builder_save", {"draft_id": "d-test-2"}, "c4")], "Revised.")
    say(gw, thread_id, "only weekdays, and not before 8")
    open_cards = cards(gw, "builder_save")
    assert [c["arguments_display"]["draft_id"] for c in open_cards] == ["d-test-2"], open_cards
    script(gw, "Saved.")
    say(gw, thread_id, "save")
    assert agent_state(gw, "test-010-inbox")[0]["soul"] == "Only on weekdays, not before 8."


def test_edit_shows_the_live_before_and_applies_as_the_next_version(gw) -> None:
    make_agent(gw, "test-010-standup", description="Daily standup")
    thread_id = new_thread(gw)
    edit = {"kind": "agent", "name": "test-010-standup", "fields": {"instructions": "Keep it to three lines."}}
    script(gw, [call("builder_read", {"kind": "agent", "name": "test-010-standup"}, "r1")], [call("builder_draft", edit, "c1")], [call("builder_save", {"draft_id": "d-test-1"}, "c2")], "Here is the diff.")
    say(gw, thread_id, "make my standup agent shorter")
    [card] = cards(gw, "builder_save")
    assert "− You are test-010-standup." in card["plan_text"] and "+ Keep it to three lines." in card["plan_text"], card["plan_text"]
    before = agent_state(gw, "test-010-standup")[1]
    script(gw, "Applied.")
    say(gw, thread_id, "apply")
    snapshot, version = agent_state(gw, "test-010-standup")
    assert version == before + 1 and snapshot["soul"] == "Keep it to three lines."
    assert snapshot["config"]["description"] == "Daily standup", "a field the edit did not name changed"
    assert agent_history(gw, "test-010-standup")[-1].source == "chat"


def test_a_stale_base_version_is_refused_and_nothing_is_overwritten(gw) -> None:
    make_agent(gw, "test-010-standup")
    thread_id = new_thread(gw)
    script(gw, [call("builder_draft", {"kind": "agent", "name": "test-010-standup", "fields": {"instructions": "From chat."}}, "c1")], [call("builder_save", {"draft_id": "d-test-1"}, "c2")], "Diff.")
    say(gw, thread_id, "change it")
    # Edited in Studio between the card and the yes.
    current = gw.client.get("/api/agents/test-010-standup").json()
    resp = gw.client.put("/api/agents/test-010-standup", json={"soul": "From Studio.", "base_version": current["version"]})
    assert resp.status_code == 200, resp.text
    studio_version = agent_state(gw, "test-010-standup")[1]
    script(gw, "Ok.")
    out = say(gw, thread_id, "yes")
    snapshot, version = agent_state(gw, "test-010-standup")
    assert (snapshot["soul"], version) == ("From Studio.", studio_version), "a stale chat save overwrote the Studio edit"
    assert "changed since this draft was made" in str(out["messages"]), out["messages"][-1]
    # Proposing it again is refused before any card.
    script(gw, [call("builder_save", {"draft_id": "d-test-1"}, "c3")], "Ok.")
    say(gw, thread_id, "save it again")
    assert cards(gw, "builder_save") == []


def test_tier_one_tools_write_nothing(gw) -> None:
    make_agent(gw, "test-010-standup")
    before = (agent_state(gw, "test-010-standup"), history_records(gw, "test-010-standup"))
    thread_id = new_thread(gw)
    script(
        gw,
        [call("builder_read", {"kind": "agent"}, "r0")],
        [call("builder_read", {"kind": "agent", "name": "test-010-standup"}, "r1")],
        [call("builder_draft", {"kind": "agent", "name": "test-010-standup", "fields": {"instructions": "x"}}, "c1")],
        [call("builder_diff", {"draft_id": "d-test-1"}, "c2")],
        "Done.",
    )
    say(gw, thread_id, "look at my standup agent")
    assert (agent_state(gw, "test-010-standup"), history_records(gw, "test-010-standup")) == before
    assert cards(gw) == []


def test_mcp_server_request_hands_off_and_drafts_nothing(gw) -> None:
    thread_id = new_thread(gw)
    script(gw, [call("builder_draft", {"kind": "mcp_server", "name": "bank", "fields": {"request": "a server for my bank's API"}}, "c1")], "Use MCP Studio.")
    out = say(gw, thread_id, "build me a server for my bank's API")
    assert "MCP Studio" in str(out["messages"]) and "/workspace/mcp" in str(out["messages"])
    assert gw.client.get(f"/api/threads/{thread_id}/builder").json()["building"] is None


def test_drop_writes_nothing_and_refuses_the_open_card(gw) -> None:
    thread_id = new_thread(gw)
    _build(gw, thread_id)
    [card] = cards(gw, "builder_save")
    resp = gw.client.delete(f"/api/threads/{thread_id}/builder")
    assert resp.status_code == 200 and resp.json() == {"thread_id": thread_id, "dropped": True, "refused_cards": 1}, resp.text
    assert gw.client.get(f"/api/threads/{thread_id}/builder").json()["building"] is None
    assert cards(gw, "builder_save") == []
    resp = gw.client.post(f"/api/confirmations/{card['id']}/confirm", json={})
    assert resp.json()["outcome"] == "already_resolved", resp.text
    assert agent_state(gw, "test-010-inbox") == (None, 0)


def test_a_skill_from_chat_is_a_versioned_custom_skill(gw, monkeypatch) -> None:
    from app.gateway.builder import service

    class Allow:
        decision, reason = "allow", "ok"

    async def scan(*_a, **_k):
        return Allow()

    monkeypatch.setattr("omniharness.skills.security_scanner.scan_skill_content", scan)
    assert service  # imported for the patch target's module
    thread_id = new_thread(gw)
    draft = {"kind": "skill", "name": "test-010-notes", "fields": {"description": "Use when taking meeting notes.", "body": "# Notes\n\n1. List decisions."}}
    script(gw, [call("builder_draft", draft, "c1")], [call("builder_save", {"draft_id": "d-test-1"}, "c2")], "Draft.")
    say(gw, thread_id, "make a skill for meeting notes")
    script(gw, "Saved.")
    say(gw, thread_id, "y")
    from omniharness.config import config_versions
    from omniharness.skills.storage import get_or_new_skill_storage

    storage = get_or_new_skill_storage()
    assert "1. List decisions." in storage.read_custom_skill("test-010-notes")
    [version] = config_versions.skill_history("test-010-notes", storage)
    assert (version.version, version.source) == (1, "chat")


def test_an_automation_from_chat_goes_through_the_rules_store(gw) -> None:
    import json

    thread_id = new_thread(gw)
    rule = {"type": "cron", "match": {"schedule": "0 9 * * 1-5"}, "prompt": "Brief me on the beta."}
    script(gw, [call("builder_draft", {"kind": "automation", "name": "test-010-brief", "fields": rule}, "c1")], [call("builder_save", {"draft_id": "d-test-1"}, "c2")], "Draft.")
    say(gw, thread_id, "every weekday at 9, brief me on the beta")
    assert json.loads((gw.tmp / "rules.json").read_text())["rules"] == []
    script(gw, "Saved.")
    say(gw, thread_id, "do it")
    [saved] = json.loads((gw.tmp / "rules.json").read_text())["rules"]
    assert saved["id"] == "test-010-brief" and saved["match"]["schedule"] == "0 9 * * 1-5"
    versions = gw.client.get("/api/automations/rules/test-010-brief/versions").json()
    assert versions["current"] == 1 and versions["versions"][-1]["source"] == "chat" and versions["versions"][-1]["via"] == "chat", versions


def test_undo_from_chat_restores_as_a_new_version(gw) -> None:
    thread_id = new_thread(gw)
    _build(gw, thread_id)
    script(gw, "Saved.")
    say(gw, thread_id, "yes")
    script(gw, [call("builder_undo", {"kind": "agent", "name": "test-010-inbox", "version": 1}, "u1")], "Undo?")
    say(gw, thread_id, "undo that")
    script(gw, "Undone.")
    say(gw, thread_id, "yes")
    snapshot, version = agent_state(gw, "test-010-inbox")
    assert (snapshot, version) == (None, 2), (snapshot, version)
    assert [v.source for v in agent_history(gw, "test-010-inbox")] == ["chat", "undo"]


def test_a_save_without_a_draft_id_pins_the_chats_current_draft(gw) -> None:
    thread_id = new_thread(gw)
    script(gw, [call("builder_draft", DRAFT_AGENT, "c1")], [call("builder_save", {}, "c2")], "Draft.")
    say(gw, thread_id, "make me an agent")
    [card] = cards(gw, "builder_save")
    assert card["arguments_display"]["draft_id"] == "d-test-1", card["arguments_display"]
    script(gw, "Saved.")
    say(gw, thread_id, "yes")
    assert agent_state(gw, "test-010-inbox")[1] == 1
