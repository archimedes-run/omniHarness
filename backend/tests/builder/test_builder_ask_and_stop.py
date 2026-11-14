"""The builder asks before inventing, and a decline ends the build (Spec 010, live fix).

Live (gpt-5 lead): "create me an agent" with nothing else got a draft invented
from memory (the owner's name, employer and goals in its instructions) and a
save card; declined, the resumed lead posted the whole spec and a JSON block
and offered to propose it again. Both are now enforced by the system:

- a NEW agent, skill or automation is drafted only with the owner's own words
  from this chat saying what it is for (`owner_request`, checked against the
  owner's tagged messages); otherwise the builder refuses and the lead asks
  one question (the Question card), which the clarification rules let through;
- after a declined or expired builder card, the resumed lead holds no builder
  tool, is told the build stops, and a reply that restates the draft is cut
  to one acknowledgement.

Each guard was removed in turn and its test seen failing (listed in the PR).
"""

from __future__ import annotations

from builder_helpers import agent_state, call, cards, new_thread, offered, say, script

GENERIC = {"kind": "agent", "name": "o1-finder", "fields": {"instructions": "Find O-1 opportunities for Jordan at Acme."}}


def _decline(gw, card: dict) -> dict:
    import time

    body = gw.client.post(f"/api/confirmations/{card['id']}/decline", json={}).json()
    run_id = body.get("resume_run_id") or (body.get("detail") or {}).get("resume_run_id")
    deadline = time.time() + 30
    while run_id and time.time() < deadline:
        if gw.client.get(f"/api/threads/{card['thread_id']}/runs/{run_id}").json().get("status") not in ("pending", "running"):
            break
        time.sleep(0.05)
    return body


def _last_reply(gw, thread_id: str) -> str:
    messages = gw.client.get(f"/api/threads/{thread_id}/state").json()["values"]["messages"]
    return str([m for m in messages if m.get("type") == "ai" and not m.get("tool_calls")][-1]["content"])


# -- 1. no subject: ask, don't draft --------------------------------------------------


def test_create_me_an_agent_drafts_nothing_and_asks_one_question(gw) -> None:
    from app.gateway.builder import drafts
    from omniharness.runtime.builder.surface import ASK_FIRST_PREFIX

    thread_id = new_thread(gw)
    ask = {"question": "What should the agent do?", "clarification_type": "missing_info", "options": ["Triage my inbox", "Brief me each morning"]}
    script(gw, [call("builder_draft", GENERIC, "c1")], [call("ask_clarification", ask, "q1")])
    out = say(gw, thread_id, "create me an agent")
    results = [m for m in out["messages"] if m.get("type") == "tool"]
    assert str(results[0]["content"]).startswith(ASK_FIRST_PREFIX), results[0]
    assert drafts.active(gw.user_id, thread_id) is None and cards(gw) == []
    questions = gw.client.get(f"/api/threads/{thread_id}/questions").json()
    listed = questions.get("questions", questions) if isinstance(questions, dict) else questions
    assert any("What should the agent do?" in str(q) for q in listed), questions


def test_a_request_with_a_purpose_drafts(gw) -> None:
    thread_id = new_thread(gw)
    draft = {"kind": "agent", "name": "test-010-inbox", "fields": {"instructions": "Triage the inbox each morning."}}
    script(gw, [call("builder_draft", draft, "c1")], [call("builder_save", {}, "c2")], "On its card.")
    say(gw, thread_id, "create me an agent that triages my inbox every morning")
    assert len(cards(gw, "builder_save")) == 1


def test_a_quote_that_is_not_the_owners_words_is_refused(gw) -> None:
    from app.gateway.builder import drafts

    thread_id = new_thread(gw)
    draft = {**GENERIC, "owner_request": "an agent that finds O-1 visa opportunities for me"}
    script(gw, [call("builder_draft", draft, "c1")], "Asked.")
    say(gw, thread_id, "create me an agent")
    assert drafts.active(gw.user_id, thread_id) is None and cards(gw) == []


def test_memory_and_read_content_never_count_as_the_owners_request(gw) -> None:
    from langchain_core.messages import HumanMessage, ToolMessage

    from app.gateway.builder.service import MESSAGES_KEY, GatewayBuilderController
    from app.policy.lineage import user_turn
    from omniharness.agents.lead_agent.prompt import BUILDER_SECTION

    profile = "Jordan works at Acme and wants an O-1 visa through published research"
    messages = [
        HumanMessage(content=f"<memory>{profile}</memory>"),  # injected context, not the owner's turn
        user_turn("create me an agent"),
        ToolMessage(content=profile, tool_call_id="m1", name="memory_read"),
    ]
    controller = GatewayBuilderController(lambda: gw.client.app.state.config)
    context = {"user_id": gw.user_id, "thread_id": new_thread(gw), MESSAGES_KEY: messages}
    out = controller.draft(context, kind="agent", name="o1-finder", fields={"instructions": profile}, guessed=[], replace_current=False, owner_request="wants an O-1 visa through published research")
    assert out.startswith("Nothing was drafted") and "not the user's own words" in out, out
    assert "only when the user's request mentions them" in BUILDER_SECTION


def test_a_question_after_the_refusal_is_not_sent_back(gw) -> None:
    from langchain_core.messages import AIMessage, ToolMessage

    from app.policy.lineage import user_turn
    from omniharness.agents.middlewares.clarification_middleware import ClarificationMiddleware
    from omniharness.runtime.builder.surface import ASK_FIRST_PREFIX

    turn = [
        user_turn("create me an agent"),
        AIMessage(content="", tool_calls=[{"name": "builder_draft", "args": {}, "id": "c1"}]),
        ToolMessage(content=f"{ASK_FIRST_PREFIX} the agent is for.", tool_call_id="c1", name="builder_draft"),
    ]
    assert ClarificationMiddleware()._deferral(turn, "q1", {"clarification_type": "missing_info"}) is None


# -- 2. a decline ends it ---------------------------------------------------------------


LONG = 'Here is the full agent again:\n\n```json\n{"name": "o1-finder", "instructions": "..."}\n```\n\n' + "It would do many things. " * 20


def _card(gw, thread_id: str) -> dict:
    draft = {"kind": "agent", "name": "test-010-inbox", "fields": {"instructions": "Triage the inbox each morning."}}
    script(gw, [call("builder_draft", draft, "c1")], [call("builder_save", {}, "c2")], "On its card.")
    say(gw, thread_id, "create me an agent that triages my inbox every morning")
    [card] = cards(gw, "builder_save")
    return card


def test_a_declined_save_gets_one_short_acknowledgement_and_no_builder_call(gw) -> None:
    from app.gateway.builder import drafts
    from omniharness.runtime.builder.surface import DECLINED_ACK

    thread_id = new_thread(gw)
    card = _card(gw, thread_id)
    script(gw, LONG)
    body = _decline(gw, card)
    assert body["outcome"] == "declined", body
    reply = _last_reply(gw, thread_id)
    assert len(reply) <= 300 and "```" not in reply and reply == DECLINED_ACK, reply
    assert not {t for t in offered(gw.lead) if t.startswith("builder_")}, "the resumed lead held builder tools"
    assert drafts.active(gw.user_id, thread_id) is not None, "the draft should be kept"
    assert agent_state(gw, "test-010-inbox") == (None, 0) and cards(gw) == []


def test_a_typed_no_is_short_too(gw) -> None:
    from app.gateway.builder import drafts

    thread_id = new_thread(gw)
    _card(gw, thread_id)
    script(gw, LONG)
    out = say(gw, thread_id, "no")
    reply = str(out["messages"][-1]["content"])
    assert len(reply) <= 300 and "```" not in reply, reply
    assert drafts.active(gw.user_id, thread_id) is not None and agent_state(gw, "test-010-inbox") == (None, 0)


def test_an_expired_builder_card_resumes_with_the_stop_and_a_short_reply() -> None:
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from langchain_core.messages import AIMessage

    from app.gateway.resume import resume_messages
    from app.policy.lineage import user_turn
    from app.policy.models import Outcome, PendingAction, Tier
    from omniharness.agents.middlewares.verification_middleware import VerificationMiddleware
    from omniharness.runtime.builder.surface import DECLINED_ACK

    action = PendingAction(plan_text="", tool_name="builder_save", arguments={"draft_id": "d-1"}, targets=[], tier_at_statement=Tier.TIER_3, expires_at=datetime.now(UTC) - timedelta(minutes=1))
    action.outcome = Outcome.EXPIRED
    resumed = resume_messages([action])
    assert "The build stops here" in str(resumed[-1].content) and "Carry on" not in str(resumed[-1].content)
    messages = [user_turn("create me an agent that triages my inbox"), *resumed, AIMessage(content=LONG, id="final")]
    out = VerificationMiddleware()._apply({"messages": messages}, SimpleNamespace(context={}))
    assert str(out["messages"][-1].content) == DECLINED_ACK
    short = [user_turn("x"), *resumed, AIMessage(content="Okay, not saved.", id="f2")]
    out = VerificationMiddleware()._apply({"messages": short}, SimpleNamespace(context={}))
    assert str((out["messages"][-1] if out else short[-1]).content) == "Okay, not saved."
