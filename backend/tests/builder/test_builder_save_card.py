"""The builder raises the save card itself, and no secret is ever asked for (Spec 010).

Live (gpt-5): after the owner chose what the agent is for, the lead drafted,
then wrote a long "proposed spec / what I need from you" reply asking the
owner to paste a URL and access token, and never proposed the save. Now:

- a successful draft of something NEW raises its save card from the builder
  itself (one per draft; a newer draft replaces it), with the draft in plain
  words, Save or Decline, typed yes by the usual rules;
- the reply after it is one short line (the card has the details);
- no reply, in any flow, asks the person to paste a token, key, password or
  secret: that sentence becomes "Connect it from Integrations; never paste
  keys into the chat.";
- the builder's question for a bare request ("please create me an agent") is
  recognised even when the lead asks before drafting: three equal
  suggestions, captioned, and its card answer drafts.

Each guard was removed in turn and its test seen failing (listed in the PR).
"""

from __future__ import annotations

import time

from builder_helpers import call, cards, new_thread, say, script

LIVE_REPLY = (
    "Great—purpose is locked: Session-Watcher Reporter. I'll capture the requirements now with sensible defaults.\n\n"
    "Proposed spec defaults (edit anything):\n- Schedule: every weekday at 09:00\n- Output: a short summary\n\n"
    "Data access for live runs (pick one to enable reporting):\n- Session-watcher URL + temporary access token (I'll mask and not echo)\n"
    "- API base URL + read-only API key\n\nWhat I need from you to proceed:\n1. Confirm or change any defaults above.\n"
    "2. Please paste your access token and the API key here so I can connect it."
)
DRAFT = {"kind": "agent", "name": "test-010-sessions", "fields": {"instructions": "Report on running coding sessions."}}


def _final(gw, thread_id: str) -> str:
    messages = gw.client.get(f"/api/threads/{thread_id}/state").json()["values"]["messages"]
    return str([m for m in messages if m.get("type") == "ai" and not m.get("tool_calls")][-1]["content"])


def _wait(gw, thread_id: str, run_id: str | None) -> None:
    deadline = time.time() + 30
    while run_id and time.time() < deadline and gw.client.get(f"/api/threads/{thread_id}/runs/{run_id}").json().get("status") in ("pending", "running"):
        time.sleep(0.05)


def test_a_draft_of_something_new_raises_its_save_card_and_the_reply_is_short(gw) -> None:
    thread_id = new_thread(gw)
    script(gw, [call("builder_draft", DRAFT, "c1")], LIVE_REPLY)
    say(gw, thread_id, "create me an agent that reports on my coding sessions")
    [card] = cards(gw, "builder_save")
    assert card["confirmable_by_typing"] is True and "test-010-sessions" in card["plan_text"], card
    assert "nothing beyond what every agent run gets" in card["plan_text"]
    reply = _final(gw, thread_id)
    assert reply.startswith("I drafted test-010-sessions.") and len(reply) <= 300, reply
    assert "token" not in reply.lower() and "api key" not in reply.lower()


def test_the_bare_request_question_drafts_from_the_card_and_raises_the_save_card(gw) -> None:
    from app.gateway.builder import drafts
    from omniharness.agents.middlewares.clarification_middleware import MEMORY_CAPTION

    thread_id = new_thread(gw)
    ask = {"question": "What should the new agent do?", "clarification_type": "missing_info", "options": ["O-1 Opportunity-Finder", "Session-Watcher Reporter", "Calendar Day-Briefer", "Docs Summarizer"], "recommended": 0}
    script(gw, [call("ask_clarification", ask, "q1")])  # asks before drafting, as live
    say(gw, thread_id, "please create me an agent thanks")
    listed = gw.client.get(f"/api/threads/{thread_id}/questions").json()
    [question] = listed.get("questions", listed) if isinstance(listed, dict) else listed
    assert len(question["options"]) == 3 and question["recommended"] is None and question["context"] == MEMORY_CAPTION, question
    paraphrase = {**DRAFT, "owner_request": "Summarize running Claude Code sessions"}
    script(gw, [call("builder_draft", paraphrase, "c1")], LIVE_REPLY)
    out = gw.client.post(f"/api/questions/{question['id']}/answer", json={"option": 1}).json()
    _wait(gw, thread_id, out.get("resume_run_id"))
    assert drafts.active(gw.user_id, thread_id) is not None
    [card] = cards(gw, "builder_save")
    assert card["origin"] == "user", card
    assert _final(gw, thread_id).startswith("I drafted test-010-sessions.")


def test_decline_on_the_raised_card_ends_in_one_line(gw) -> None:
    from app.gateway.builder import drafts
    from omniharness.runtime.builder.surface import DECLINED_ACK

    thread_id = new_thread(gw)
    script(gw, [call("builder_draft", DRAFT, "c1")], LIVE_REPLY)
    say(gw, thread_id, "create me an agent that reports on my coding sessions")
    [card] = cards(gw, "builder_save")
    script(gw, LIVE_REPLY)
    body = gw.client.post(f"/api/confirmations/{card['id']}/decline", json={}).json()
    _wait(gw, thread_id, body.get("resume_run_id") or (body.get("detail") or {}).get("resume_run_id"))
    assert _final(gw, thread_id) == DECLINED_ACK
    assert drafts.active(gw.user_id, thread_id) is not None


def test_one_card_per_draft_and_a_newer_draft_replaces_it(gw) -> None:
    thread_id = new_thread(gw)
    second = {**DRAFT, "fields": {"instructions": "Report on sessions every hour."}}
    script(gw, [call("builder_draft", DRAFT, "c1")], [call("builder_save", {}, "c2")], [call("builder_draft", second, "c3")], "Drafted.")
    say(gw, thread_id, "create me an agent that reports on my coding sessions")
    open_cards = cards(gw, "builder_save")
    assert [c["arguments_display"]["draft_id"] for c in open_cards] == ["d-test-2"], open_cards


def test_typed_yes_saves_the_raised_card(gw) -> None:
    from builder_helpers import agent_state

    thread_id = new_thread(gw)
    script(gw, [call("builder_draft", DRAFT, "c1")], "Drafted.")
    say(gw, thread_id, "create me an agent that reports on my coding sessions")
    script(gw, "Saved.")
    say(gw, thread_id, "yes")
    assert agent_state(gw, "test-010-sessions")[1] == 1


def test_no_reply_ever_asks_for_a_secret() -> None:
    from types import SimpleNamespace

    from langchain_core.messages import AIMessage

    from app.policy.lineage import user_turn
    from omniharness.agents.middlewares.verification_middleware import VerificationMiddleware
    from omniharness.agents.working_loop import NO_SECRETS_LINE

    def final(reply: str) -> str:
        messages = [user_turn("connect my github"), AIMessage(content=reply, id="f")]
        out = VerificationMiddleware()._apply({"messages": messages}, SimpleNamespace(context={}))
        return str((out["messages"][-1] if out else messages[-1]).content)

    asked = final("I can set that up. Please paste your GitHub personal access token here. Then I will sync your issues.")
    assert NO_SECRETS_LINE in asked and "paste your GitHub" not in asked and "Then I will sync" in asked, asked
    listed = final("To proceed:\n- Share your API key and password\n- Pick a repo")
    assert NO_SECRETS_LINE in listed and "Share your API key" not in listed and "Pick a repo" in listed, listed
    kept = "Never paste a password into a chat; use the Connect button instead."
    assert final(kept) == kept
    code = "Set it like this:\n\n```\nexport API_KEY=...\n```"
    assert final(code) == code


def test_the_model_cannot_raise_a_second_card_for_the_same_draft(gw) -> None:
    thread_id = new_thread(gw)
    script(gw, [call("builder_draft", DRAFT, "c1")], [call("builder_save", {}, "c2")], "Drafted.")
    say(gw, thread_id, "create me an agent that reports on my coding sessions")
    assert len(cards(gw, "builder_save")) == 1
