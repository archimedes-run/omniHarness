"""What counts as the owner saying what a NEW agent, skill or automation is for (Spec 010).

- A request names a subject when it has one word beyond the generic ones
  ("create me an agent" does not; "make me a twitter bot" does), in any script.
- The quote must be the owner's own words of THIS request: their tagged
  message of the current turn, or their answer on the Question card the
  builder's own "ask first" refusal raised (checked in the question store).
  Whole words only; older messages, memory and read content never count.
- Answering that question on the card (a suggestion clicked, or free text),
  or typing the answer in chat, leads to a draft and its save card.

Each guard was removed in turn and its test seen failing (listed in the PR).
"""

from __future__ import annotations

import time

import pytest
from builder_helpers import call, cards, new_thread, say, script

ACCEPTED = [
    "make me a twitter bot",
    "an agent for my inbox",
    "a twitter bot",
    "create an agent that reads my mail",
    "Triage my inbox",
    "create me an agent that triages my inbox every morning",
    "make a skill for meeting notes",
    "set up an automation that briefs me at 9",
    "build me a research assistant for biology papers",
    "an agent to track my expenses",
    "make a bot that posts to slack",
    "create a skill that writes release notes",
    "I need an agent for job applications",
    "make me something that summarizes podcasts",
    "a daily standup agent",
    "set up a weekly report automation",
    "create an agent called Scout",
    "an assistant for my calendar",
    "build a helper that renames files",
    "make an agent that watches github issues",
    "create a reminder automation for bills",
    "a skill for SQL reviews",
    "an agent that drafts replies",
    "make me a recipe bot",
    "create an agent for customer support tickets",
    "automation: every friday email me the backlog",
    "a newsletter agent",
]
REFUSED = [
    "create me an agent",
    "make a skill",
    "set up an automation for me",
    "build me something",
    "make me an agent please",
    "create an agent",
    "can you make me a new bot",
    "I want a skill",
    "make one",
    "create a new automation",
    "build an assistant for me",
    "set up a workflow",
    "help me make an agent",
]
SCRIPTS = [
    "मेरे इनबॉक्स को छाँटने वाला एजेंट बनाओ",
    "受信箱を整理するエージェントを作って",
    "أنشئ وكيلا يرتب بريدي الوارد",
    "создай агента, который разбирает мою почту",
    "crée un agent qui trie ma boîte de réception",
]


def _problem(owner_text: str, quote: str, *, earlier: list | None = None) -> str | None:
    from langchain_core.messages import AIMessage

    from app.gateway.builder.service import MESSAGES_KEY, GatewayBuilderController
    from app.policy.lineage import user_turn

    messages = [*(earlier or []), user_turn(owner_text), AIMessage(content="", tool_calls=[{"name": "builder_draft", "args": {}, "id": "c1"}])]
    return GatewayBuilderController._request_problem({MESSAGES_KEY: messages, "thread_id": "t", "user_id": "u"}, quote)


@pytest.mark.parametrize("phrase", ACCEPTED)
def test_a_request_that_names_a_subject_is_accepted(phrase) -> None:
    assert _problem(phrase, phrase) is None, phrase


@pytest.mark.parametrize("phrase", REFUSED)
def test_a_bare_request_is_refused(phrase) -> None:
    assert _problem(phrase, phrase), phrase


@pytest.mark.parametrize("phrase", SCRIPTS)
def test_a_request_in_any_script_is_accepted(phrase) -> None:
    assert _problem(phrase, phrase) is None, phrase


def test_whole_words_only_and_only_the_current_request() -> None:
    from langchain_core.messages import AIMessage

    from app.policy.lineage import user_turn

    assert _problem("create an agent that reads my email", "mail"), "a quote inside a longer word matched"
    earlier = [user_turn("an agent that files my receipts"), AIMessage(content="Noted.")]
    assert _problem("create me an agent", "files my receipts", earlier=earlier), "an older message counted"


# -- through the app: the model's own quote (the helper does not fill it in) --------


def test_a_wrong_or_bare_quote_from_the_model_is_refused(gw) -> None:
    from app.gateway.builder import drafts

    for quote in ("an agent that finds O-1 visa opportunities", "create me an agent", "inbox every"):
        thread_id = new_thread(gw)
        draft = {"kind": "agent", "name": "test-010-x", "owner_request": quote, "fields": {"instructions": "x"}}
        script(gw, [call("builder_draft", draft, "c1")], "Asked.")
        say(gw, thread_id, "create me an agent that sorts my inbox")
        assert drafts.active(gw.user_id, thread_id) is None, quote


# -- through the app: answering the builder's question --------------------------------


ASK = {"question": "What should the agent do?", "clarification_type": "missing_info", "options": ["Triage my inbox", "Brief me each morning"]}
VAGUE = {"kind": "agent", "name": "test-010-x", "fields": {"instructions": "x"}}


def _asked(gw) -> tuple[str, str]:
    thread_id = new_thread(gw)
    script(gw, [call("builder_draft", VAGUE, "c1")], [call("ask_clarification", ASK, "q1")])
    say(gw, thread_id, "create me an agent")
    listed = gw.client.get(f"/api/threads/{thread_id}/questions").json()
    listed = listed.get("questions", listed) if isinstance(listed, dict) else listed
    return thread_id, listed[0]["id"]


def _answer(gw, thread_id: str, qid: str, body: dict, quote: str) -> None:
    draft = {"kind": "agent", "name": "test-010-inbox", "owner_request": quote, "fields": {"instructions": "Triage the inbox."}}
    script(gw, [call("builder_draft", draft, "c2")], [call("builder_save", {}, "c3")], "On its card.")
    out = gw.client.post(f"/api/questions/{qid}/answer", json=body).json()
    run_id = out.get("resume_run_id")
    assert run_id, out
    deadline = time.time() + 30
    while time.time() < deadline and gw.client.get(f"/api/threads/{thread_id}/runs/{run_id}").json().get("status") in ("pending", "running"):
        time.sleep(0.05)


def test_a_suggestion_clicked_on_the_card_becomes_the_draft(gw) -> None:
    from app.gateway.builder import drafts

    thread_id, qid = _asked(gw)
    _answer(gw, thread_id, qid, {"option": 0}, "Triage my inbox")
    assert drafts.active(gw.user_id, thread_id) is not None
    assert len(cards(gw, "builder_save")) == 1


def test_free_text_on_the_card_becomes_the_draft(gw) -> None:
    from app.gateway.builder import drafts

    thread_id, qid = _asked(gw)
    _answer(gw, thread_id, qid, {"text": "an agent that files my receipts"}, "files my receipts")
    assert drafts.active(gw.user_id, thread_id) is not None
    assert len(cards(gw, "builder_save")) == 1


def test_a_quote_not_from_the_card_answer_is_refused_in_the_resume(gw) -> None:
    from app.gateway.builder import drafts

    thread_id, qid = _asked(gw)
    _answer(gw, thread_id, qid, {"option": 0}, "files my receipts")
    assert drafts.active(gw.user_id, thread_id) is None and cards(gw, "builder_save") == []


def test_a_typed_answer_in_chat_becomes_the_draft(gw) -> None:
    from app.gateway.builder import drafts

    thread_id, _ = _asked(gw)
    draft = {"kind": "agent", "name": "test-010-inbox", "fields": {"instructions": "File receipts."}}
    script(gw, [call("builder_draft", draft, "c2")], [call("builder_save", {}, "c3")], "On its card.")
    say(gw, thread_id, "an agent that files my receipts")
    assert drafts.active(gw.user_id, thread_id) is not None
    assert len(cards(gw, "builder_save")) == 1


# -- a mixed group: the work that ran is reported -------------------------------------


@pytest.mark.parametrize("builder_first", [True, False])
def test_a_mixed_group_reports_the_work_and_is_not_cut(builder_first) -> None:
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from langchain_core.messages import AIMessage

    from app.gateway.resume import resume_messages
    from app.policy.lineage import user_turn
    from app.policy.models import Outcome, PendingAction, Tier
    from omniharness.agents.middlewares.verification_middleware import VerificationMiddleware

    def action(tool: str, outcome: Outcome) -> PendingAction:
        a = PendingAction(plan_text="", tool_name=tool, arguments={}, targets=[], tier_at_statement=Tier.TIER_3, expires_at=datetime.now(UTC) + timedelta(hours=1))
        a.outcome, a.result_excerpt = outcome, "sent"
        return a

    save, mail = action("builder_save", Outcome.DECLINED), action("send_email", Outcome.EXECUTED)
    resumed = resume_messages([save, mail] if builder_first else [mail, save])
    texts = [str(m.content) for m in resumed[1:]]
    assert "Carry on" in texts[-1], texts
    assert any("Mention it in one sentence" in t for t in texts) and not any("The build stops here" in t for t in texts), texts
    report = "I sent the email to the team with the summary you asked for. " * 8
    messages = [user_turn("email the team and make an agent for it"), *resumed, AIMessage(content=report, id="final")]
    out = VerificationMiddleware()._apply({"messages": messages}, SimpleNamespace(context={}))
    assert str((out["messages"][-1] if out else messages[-1]).content).startswith("I sent the email"), "the report of work that ran was cut"
