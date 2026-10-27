"""Spec 009 Slice 0: the lead's prompt, tool texts and working-loop helpers.

The behaviours are measured end to end by the eval suite (tests/eval); these
pin the texts and the pure functions the middlewares and the eval share.
"""

from __future__ import annotations

import re

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from omniharness.agents.turns import USER_TURN_MARKER
from omniharness.agents.working_loop import (
    build_verification_record,
    has_menu,
    narrates_tools,
    plan_record,
    plan_record_text,
    strip_trailing_menu,
)

#: D11: no commercial agent, assistant or vendor product in the prompt or the
#: tool texts (open-source projects may be named).
PRODUCT_NAMES = re.compile(r"\b(Codex|Claude|ChatGPT|Copilot|Cursor|Gemini|Perplexity|Tencent|AWS|Azure|GCP|Alibaba|Oracle Cloud|techcrunch|openai\.com)\b", re.I)


def _prompt(**kwargs) -> str:
    from omniharness.agents.lead_agent.prompt import apply_prompt_template

    return apply_prompt_template(**kwargs)


def test_the_prompt_has_the_working_loop_and_no_clarify_first_rule() -> None:
    for subagents in (False, True):
        prompt = _prompt(subagent_enabled=subagents)
        assert "<working_loop>" in prompt
        assert "<clarification_system>" not in prompt
        assert "CLARIFY → PLAN → ACT" not in prompt
        assert "you MUST ask for clarification FIRST" not in prompt
        assert "Clarification First" not in prompt
        assert 'The first item is "Done when: ..."' in prompt
        assert "Reading never needs permission" in prompt
        assert "never applies to reading" in prompt  # memory "confirm first" notes do not cover reads
        assert "never repeat an identical" in prompt
        assert "Not verified" in prompt
        assert "Do not narrate your tool calls" in prompt
        assert "present_files" in prompt
        assert "Would you like me to" in prompt  # named as the thing not to do
    # The tracked texts (installed skills are the user's, not ours).
    from omniharness.agents.lead_agent.prompt import SYSTEM_PROMPT_TEMPLATE, _build_subagent_section

    for text in (SYSTEM_PROMPT_TEMPLATE, _build_subagent_section(3)):
        assert not PRODUCT_NAMES.search(text), PRODUCT_NAMES.search(text)


def test_the_subagent_section_asks_for_a_five_part_brief() -> None:
    prompt = _prompt(subagent_enabled=True)
    for part in ("Goal:", "Inputs:", "Constraints:", "Done when:", "Return:"):
        assert part in prompt
    assert "Only use `task` when you can launch 2+ subagents" not in prompt


def test_ask_clarification_offers_no_approach_risk_or_suggestion_types() -> None:
    from omniharness.tools.builtins.clarification_tool import ask_clarification_tool

    schema = ask_clarification_tool.args_schema.model_json_schema()
    kinds = set(schema["properties"]["clarification_type"]["enum"])
    assert kinds == {"missing_info", "ambiguous_requirement"}
    text = ask_clarification_tool.description
    assert "confirmation card" in text and "permission to read" in text
    assert not PRODUCT_NAMES.search(text)


def test_tool_texts_say_what_to_change() -> None:
    from omniharness.agents.middlewares import loop_detection_middleware as loop
    from omniharness.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
    from omniharness.tools.builtins.present_file_tool import present_file_tool
    from omniharness.tools.builtins.research_tool import research_tool
    from omniharness.tools.builtins.task_tool import task_tool

    assert "Continue with available context" not in __import__("inspect").getsource(ToolErrorHandlingMiddleware)
    assert "produce your final answer now" not in loop._WARNING_MSG
    assert "Change your approach" in loop._WARNING_MSG
    assert "not verified" in loop._HARD_STOP_MSG
    assert "checked exist" in present_file_tool.description
    assert "Done when" in task_tool.tool_call_schema.model_json_schema()["properties"]["prompt"]["description"]
    assert "config.yaml" not in task_tool.description
    assert "read-only web researcher" in research_tool.description


def test_write_todos_is_bound_in_every_mode() -> None:
    from omniharness.agents.lead_agent.agent import _create_todo_list_middleware

    for plan_mode in (False, True):
        middleware = _create_todo_list_middleware(plan_mode)
        assert [t.name for t in middleware.tools] == ["write_todos"]
        assert "Done when" in middleware.tools[0].description


# ---------------------------------------------------------------- helpers


def test_menu_detection_reads_the_last_paragraph_only() -> None:
    body = "Morning: the market.\n\nOption A: a museum. Option B: a park.\n\nEvening: dinner at Zahav."
    assert not has_menu(body)
    assert has_menu(body + "\n\nWould you like me to book a table?")
    assert has_menu("Here it is.\n\nWhich would you like?\n\n- A\n- B") or has_menu("Here it is.\n\nShould I add more?")


def test_a_trailing_menu_is_stripped_only_when_enough_stays() -> None:
    long_body = "The Philadelphia Museum of Art is a great Saturday choice, with big collections and a river view. " * 2
    text, changed = strip_trailing_menu(long_body + "\n\nWould you like me to find lunch nearby?")
    assert changed and "Would you like" not in text
    only_question = "Would you like me to search for something?"
    assert strip_trailing_menu(only_question) == (only_question, False)


def test_narration_is_detected() -> None:
    assert narrates_tools("I used write_file with the path below.")
    assert narrates_tools("I called web_search for restaurants.")
    assert not narrates_tools("Here are five restaurants.")


def _turn(*messages):
    return [HumanMessage(content="go", additional_kwargs={USER_TURN_MARKER: True}), *messages]


def test_the_record_is_verified_only_on_evidence() -> None:
    call = AIMessage(content="", tool_calls=[{"name": "web_search", "args": {"query": "x"}, "id": "c1"}])
    result = ToolMessage(content='[{"url": "https://a.example/one"}]', tool_call_id="c1", name="web_search")
    todos = [{"content": "Done when: one link", "status": "completed"}, {"content": "Search", "status": "completed"}]
    good = build_verification_record(_turn(call, result), todos, run_id="r1", reply="See https://a.example/one\n\nChecked: from the search.")
    assert good["status"] == "verified" and good["links"]["verified"] == ["https://a.example/one"]
    invented = build_verification_record(_turn(call, result), todos, run_id="r1", reply="See https://b.example/two")
    assert invented["status"] == "unverified" and invented["links"]["unverified"] == ["https://b.example/two"]
    open_item = build_verification_record(_turn(call, result), [*todos, {"content": "Fetch", "status": "pending"}], run_id="r1", reply="See https://a.example/one")
    assert open_item["status"] == "unverified"
    nothing = build_verification_record(_turn(), [], run_id="r1", reply="15% of 80 is 12.")
    assert nothing["status"] == "none"


def test_the_plan_record_keeps_findings_and_blockers() -> None:
    call = AIMessage(content="", tool_calls=[{"name": "web_search", "args": {"query": "fishtown"}, "id": "c1"}, {"name": "web_fetch", "args": {"url": "https://bad.example"}, "id": "c2"}])
    ok = ToolMessage(content='[{"url": "https://www.surayaphilly.com/"}]', tool_call_id="c1", name="web_search")
    bad = ToolMessage(content="Error: Tool 'web_fetch' failed with RuntimeError: 404", tool_call_id="c2", name="web_fetch", status="error")
    record = plan_record(_turn(call, ok, bad), [{"content": "Done when: 12 links", "status": "completed"}, {"content": "Search", "status": "in_progress"}])
    assert record["done_criteria"] == "12 links"
    assert record["findings"][0]["urls"] == ["https://www.surayaphilly.com/"]
    assert record["blockers"][0]["tool"] == "web_fetch"
    text = plan_record_text(record)
    assert "Already done and verified" in text and "surayaphilly" in text and "[in_progress] Search" in text
