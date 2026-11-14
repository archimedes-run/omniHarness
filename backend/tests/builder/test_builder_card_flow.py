"""The builder's question card, end to end, as it went wrong live (Spec 010).

Live (gpt-5 lead): "create me an agent" asked a good question; the owner
clicked a suggestion; the model PARAPHRASED it as its quote, the draft was
refused, two internal "Not asked" blocks showed in the chat, and the reply
asked the owner for an internal parameter by name. Now:

- the server reads the owner's words itself (their message, or their card
  answer), so a paraphrase drafts;
- after the answer, the run drafts and raises the save card: any further
  question is not asked;
- the builder's question has at most 3 suggestions of at most 60 characters,
  none pre-picked, captioned as suggestions from memory (none when memory is
  off in that chat);
- refused questions are marked as not asked (the chat hides them), and
  builder tool or parameter names never reach the reply.

Each guard was removed in turn and its test seen failing (listed in the PR).
"""

from __future__ import annotations

import time

from builder_helpers import call, cards, new_thread, say, script

ASK4 = {
    "question": "What should the new agent do for you?",
    "clarification_type": "missing_info",
    "options": [
        "O-1 Opportunity-Finder (read-only)",
        "Session-Watcher Reporter (read-only)",
        "Calendar Day-Briefer 07:30 ET (read-only), with a much longer description than fits",
        "Spinusync Docs Summarizer (read-only)",
    ],
    "recommended": 1,
}
VAGUE = {"kind": "agent", "name": "test-010-x", "fields": {"instructions": "x"}}
PARAPHRASE = {"kind": "agent", "name": "test-010-sessions", "owner_request": "Summarize running Claude Code sessions (read-only)", "fields": {"instructions": "Report on running coding sessions."}}


def _questions(gw, thread_id: str) -> list[dict]:
    listed = gw.client.get(f"/api/threads/{thread_id}/questions").json()
    return listed.get("questions", listed) if isinstance(listed, dict) else listed


def _wait(gw, thread_id: str, run_id: str | None) -> None:
    deadline = time.time() + 30
    while run_id and time.time() < deadline and gw.client.get(f"/api/threads/{thread_id}/runs/{run_id}").json().get("status") in ("pending", "running"):
        time.sleep(0.05)


def _ask(gw) -> tuple[str, dict]:
    thread_id = new_thread(gw)
    script(gw, [call("builder_draft", VAGUE, "c1")], [call("ask_clarification", ASK4, "q1")])
    say(gw, thread_id, "create me an agent")
    [question] = _questions(gw, thread_id)
    return thread_id, question


def test_the_builders_question_has_three_equal_suggestions_with_a_caption(gw) -> None:
    from omniharness.agents.middlewares.clarification_middleware import MEMORY_CAPTION

    _, question = _ask(gw)
    labels = [o["label"] for o in question["options"]]
    assert len(labels) == 3 and all(len(label) <= 60 for label in labels), labels
    assert question["recommended"] is None, "a suggestion from memory was pre-picked"
    assert question["context"] == MEMORY_CAPTION


def test_no_suggestions_when_memory_is_off(gw, monkeypatch) -> None:
    from omniharness.agents.middlewares import clarification_middleware
    from omniharness.agents.middlewares.clarification_middleware import shape_builder_question

    monkeypatch.setattr(clarification_middleware, "_memory_on", gw.memory_on)  # the real check

    shaped = shape_builder_question(dict(ASK4), {"memory_off": True})
    assert shaped["options"] == [] and shaped["context"] == "" and shaped["recommended"] is None
    # Memory off for the whole install (this test gateway): an open question.
    _, question = _ask(gw)
    assert question["options"] == [] and question["context"] == "", question


def test_a_paraphrased_answer_drafts_and_further_questions_are_not_asked(gw) -> None:
    from app.gateway.builder import drafts

    thread_id, question = _ask(gw)
    more = {"question": "Which sessions?", "clarification_type": "missing_info"}
    script(gw, [call("ask_clarification", more, "q2")], [call("ask_clarification", {**more, "question": "How often?"}, "q3")], [call("builder_draft", PARAPHRASE, "c2")], [call("builder_save", {}, "c3")], "It is on its card.")
    out = gw.client.post(f"/api/questions/{question['id']}/answer", json={"option": 1}).json()
    _wait(gw, thread_id, out.get("resume_run_id"))
    assert len(_questions(gw, thread_id)) == 1, "a further question card was raised after the answer"
    assert drafts.active(gw.user_id, thread_id) is not None and len(cards(gw, "builder_save")) == 1
    messages = gw.client.get(f"/api/threads/{thread_id}/state").json()["values"]["messages"]
    refused = [m for m in messages if m.get("type") == "tool" and m.get("name") == "ask_clarification" and str(m.get("content")).startswith("Not asked")]
    assert len(refused) == 2 and all(m.get("additional_kwargs", {}).get("omniharness_not_asked") for m in refused), refused


def test_the_whole_chain_ends_in_one_line_after_a_decline(gw) -> None:
    from app.gateway.builder import drafts
    from omniharness.runtime.builder.surface import DECLINED_ACK

    thread_id, question = _ask(gw)
    script(gw, [call("builder_draft", PARAPHRASE, "c2")], [call("builder_save", {}, "c3")], "It is on its card.")
    out = gw.client.post(f"/api/questions/{question['id']}/answer", json={"option": 1}).json()
    _wait(gw, thread_id, out.get("resume_run_id"))
    [card] = cards(gw, "builder_save")
    script(gw, 'Here it is again:\n\n```json\n{"name": "test-010-sessions"}\n```\n\n' + "It reports on sessions. " * 20)
    body = gw.client.post(f"/api/confirmations/{card['id']}/decline", json={}).json()
    _wait(gw, thread_id, body.get("resume_run_id") or (body.get("detail") or {}).get("resume_run_id"))
    messages = gw.client.get(f"/api/threads/{thread_id}/state").json()["values"]["messages"]
    reply = str([m for m in messages if m.get("type") == "ai" and not m.get("tool_calls")][-1]["content"])
    assert reply == DECLINED_ACK and "```" not in reply, reply
    assert drafts.active(gw.user_id, thread_id) is not None


def test_refused_questions_are_marked_not_asked() -> None:
    from langchain_core.messages import AIMessage, ToolMessage

    from app.policy.lineage import user_turn
    from omniharness.agents.middlewares.clarification_middleware import NOT_ASKED_MARKER, ClarificationMiddleware, answered_refusal, problem_message

    assert problem_message("each option must be 1 to 60 characters", "q1").additional_kwargs.get(NOT_ASKED_MARKER)
    assert answered_refusal("q1").additional_kwargs.get(NOT_ASKED_MARKER)
    turn = [user_turn("look into it"), AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "w1"}]), ToolMessage(content="results", tool_call_id="w1", name="web_search")]
    deferred = ClarificationMiddleware()._deferral(turn, "q1", {"clarification_type": "missing_info"})
    assert deferred is not None and deferred.additional_kwargs.get(NOT_ASKED_MARKER)


def test_builder_names_never_reach_the_reply() -> None:
    from types import SimpleNamespace

    from langchain_core.messages import AIMessage, ToolMessage

    from app.policy.lineage import user_turn
    from omniharness.agents.middlewares.verification_middleware import VerificationMiddleware

    reply = "Got it. To draft the agent, I need the purpose in your own words as the owner_request. What should it do?"
    messages = [
        user_turn("create me an agent"),
        AIMessage(content="", tool_calls=[{"name": "builder_draft", "args": {}, "id": "c1"}]),
        ToolMessage(content="Nothing was drafted.", tool_call_id="c1", name="builder_draft"),
        AIMessage(content=reply, id="final"),
    ]
    out = VerificationMiddleware()._apply({"messages": messages}, SimpleNamespace(context={}))
    final = str(out["messages"][-1].content)
    assert "owner_request" not in final and "What should it do?" in final, final
