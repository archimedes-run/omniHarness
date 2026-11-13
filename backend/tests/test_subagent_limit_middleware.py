"""Tests for SubagentLimitMiddleware."""

from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage

from omniharness.agents.middlewares.subagent_limit_middleware import (
    MAX_CONCURRENT_SUBAGENTS,
    MAX_SUBAGENT_LIMIT,
    MIN_SUBAGENT_LIMIT,
    SubagentLimitMiddleware,
    _clamp_subagent_limit,
)


def _make_runtime():
    runtime = MagicMock()
    runtime.context = {"thread_id": "test-thread"}
    return runtime


def _task_call(task_id="call_1"):
    return {"name": "task", "id": task_id, "args": {"prompt": "do something"}}


def _other_call(name="bash", call_id="call_other"):
    return {"name": name, "id": call_id, "args": {}}


class TestClampSubagentLimit:
    def test_below_min_clamped_to_min(self):
        assert _clamp_subagent_limit(0) == MIN_SUBAGENT_LIMIT
        assert _clamp_subagent_limit(1) == MIN_SUBAGENT_LIMIT

    def test_above_max_clamped_to_max(self):
        assert _clamp_subagent_limit(10) == MAX_SUBAGENT_LIMIT
        assert _clamp_subagent_limit(100) == MAX_SUBAGENT_LIMIT

    def test_within_range_unchanged(self):
        assert _clamp_subagent_limit(2) == 2
        assert _clamp_subagent_limit(3) == 3
        assert _clamp_subagent_limit(4) == 4


class TestSubagentLimitMiddlewareInit:
    def test_default_max_concurrent(self):
        mw = SubagentLimitMiddleware()
        assert mw.max_concurrent == MAX_CONCURRENT_SUBAGENTS

    def test_custom_max_concurrent_clamped(self):
        mw = SubagentLimitMiddleware(max_concurrent=1)
        assert mw.max_concurrent == MIN_SUBAGENT_LIMIT

        mw = SubagentLimitMiddleware(max_concurrent=10)
        assert mw.max_concurrent == MAX_SUBAGENT_LIMIT


class TestTruncateTaskCalls:
    def test_no_messages_returns_none(self):
        mw = SubagentLimitMiddleware()
        assert mw._truncate_task_calls({"messages": []}) is None

    def test_missing_messages_returns_none(self):
        mw = SubagentLimitMiddleware()
        assert mw._truncate_task_calls({}) is None

    def test_last_message_not_ai_returns_none(self):
        mw = SubagentLimitMiddleware()
        state = {"messages": [HumanMessage(content="hello")]}
        assert mw._truncate_task_calls(state) is None

    def test_ai_no_tool_calls_returns_none(self):
        mw = SubagentLimitMiddleware()
        state = {"messages": [AIMessage(content="thinking...")]}
        assert mw._truncate_task_calls(state) is None

    def test_task_calls_within_limit_returns_none(self):
        mw = SubagentLimitMiddleware(max_concurrent=3)
        msg = AIMessage(
            content="",
            tool_calls=[_task_call("t1"), _task_call("t2"), _task_call("t3")],
        )
        assert mw._truncate_task_calls({"messages": [msg]}) is None

    def test_task_calls_exceeding_limit_truncated(self):
        mw = SubagentLimitMiddleware(max_concurrent=2)
        msg = AIMessage(
            content="",
            tool_calls=[_task_call("t1"), _task_call("t2"), _task_call("t3"), _task_call("t4")],
        )
        result = mw._truncate_task_calls({"messages": [msg]})
        assert result is not None
        updated_msg = result["messages"][0]
        task_calls = [tc for tc in updated_msg.tool_calls if tc["name"] == "task"]
        assert len(task_calls) == 2
        assert task_calls[0]["id"] == "t1"
        assert task_calls[1]["id"] == "t2"

    def test_non_task_calls_preserved(self):
        mw = SubagentLimitMiddleware(max_concurrent=2)
        msg = AIMessage(
            content="",
            tool_calls=[
                _other_call("bash", "b1"),
                _task_call("t1"),
                _task_call("t2"),
                _task_call("t3"),
                _other_call("read", "r1"),
            ],
        )
        result = mw._truncate_task_calls({"messages": [msg]})
        assert result is not None
        updated_msg = result["messages"][0]
        names = [tc["name"] for tc in updated_msg.tool_calls]
        assert "bash" in names
        assert "read" in names
        task_calls = [tc for tc in updated_msg.tool_calls if tc["name"] == "task"]
        assert len(task_calls) == 2

    def test_only_non_task_calls_returns_none(self):
        mw = SubagentLimitMiddleware()
        msg = AIMessage(
            content="",
            tool_calls=[_other_call("bash", "b1"), _other_call("read", "r1")],
        )
        assert mw._truncate_task_calls({"messages": [msg]}) is None


class TestAfterModel:
    def test_delegates_to_truncate(self):
        mw = SubagentLimitMiddleware(max_concurrent=2)
        runtime = _make_runtime()
        msg = AIMessage(
            content="",
            tool_calls=[_task_call("t1"), _task_call("t2"), _task_call("t3")],
        )
        result = mw.after_model({"messages": [msg]}, runtime)
        assert result is not None
        task_calls = [tc for tc in result["messages"][0].tool_calls if tc["name"] == "task"]
        assert len(task_calls) == 2


class TestResearchFanOut:
    """Spec 009 review M1: `research` (bound in every mode) is capped like `task`."""

    def test_excess_research_calls_are_dropped_and_task_calls_untouched(self):
        mw = SubagentLimitMiddleware(max_concurrent=3, tool_names=("research",))
        calls = [{"name": "research", "id": f"r{i}", "args": {"brief": "x"}} for i in range(5)] + [_task_call("t1")]
        state = {"messages": [HumanMessage(content="go"), AIMessage(content="", tool_calls=calls)]}
        out = mw.after_model(state, _make_runtime())
        kept = [c["id"] for c in out["messages"][0].tool_calls]
        assert kept == ["r0", "r1", "r2", "t1"]

    def test_the_lead_caps_research_in_every_mode(self):
        from omniharness.agents.lead_agent.agent import _build_middlewares

        for mode in ({"subagent_enabled": False}, {"subagent_enabled": True}):
            chain = _build_middlewares({"configurable": mode}, model_name=None)
            limits = [m for m in chain if isinstance(m, SubagentLimitMiddleware)]
            assert len(limits) == 1 and "research" in limits[0].tool_names, mode
            assert ("task" in limits[0].tool_names) == mode["subagent_enabled"]
