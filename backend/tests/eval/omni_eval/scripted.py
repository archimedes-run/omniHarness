"""The eval's scripted chat model (spec 009 FR-073).

In mock mode every model the gateway builds (the lead, a subagent, the
summariser) is this class, named in the trial's config (`use:
omni_eval.scripted:ScriptedChatModel`). It replays the task's `mock` turns
in order and FAILS the run when the conversation diverges from the script: a
step may say what the last tool result must contain (`expect`). So a mocked
task tests the harness (middleware, policy, resume, summarisation, trace,
checks), not a model's judgement.

Which queue a call reads:
  * the lead's calls (its tools include `write_todos`): `lead`;
  * a subagent's calls (any other tool list): `sub`;
  * the summariser (no tools bound): a fixed summary, never a script step.
"""

from __future__ import annotations

import json
import threading
import uuid
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict


class EvalDivergence(RuntimeError):
    """The conversation left the script: the mocked task fails on it."""


class Script:
    """The current trial's script, shared by every model instance."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.queues: dict[str, list[dict]] = {"lead": [], "sub": []}
        self.used: dict[str, int] = {"lead": 0, "sub": 0}
        self.divergence: str | None = None
        self.calls: list[str] = []

    def load(self, mock: dict | list | None) -> None:
        with self.lock:
            if isinstance(mock, list):
                mock = {"lead": mock}
            mock = mock or {}
            self.queues = {"lead": list(mock.get("lead") or []), "sub": list(mock.get("sub") or [])}
            self.used = {"lead": 0, "sub": 0}
            self.divergence = None
            self.calls = []

    def next(self, who: str, messages: list[BaseMessage]) -> dict:
        with self.lock:
            queue = self.queues.get(who) or []
            index = self.used[who]
            self.calls.append(who)
            if index >= len(queue):
                self.divergence = self.divergence or f"{who} model called a {index + 1}th time; the script has {len(queue)} step(s)"
                raise EvalDivergence(self.divergence)
            step = queue[index]
            self.used[who] = index + 1
        expect = step.get("expect")
        if expect:
            problem = _check_expect(expect, messages)
            if problem:
                with self.lock:
                    tail = " | ".join(f"{type(m).__name__}:{_text(m)[:80]!r}" for m in messages[-4:])
                    self.divergence = self.divergence or f"{who} step {index + 1}: {problem} (last messages: {tail})"
                raise EvalDivergence(self.divergence)
        return step

    def remaining(self) -> dict[str, int]:
        with self.lock:
            return {k: len(v) - self.used[k] for k, v in self.queues.items()}


SCRIPT = Script()


def _text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content or [])


def _check_expect(expect: dict, messages: list[BaseMessage]) -> str | None:
    """`expect`: {tool: name, contains: text, not_contains: text, any_contains: text}.
    `tool`/`contains` read the LAST tool result; `any_contains` any message."""
    tools = [m for m in messages if isinstance(m, ToolMessage)]
    last = tools[-1] if tools else None
    if "tool" in expect and (last is None or (last.name or "") != expect["tool"]):
        return f"expected the last tool result from {expect['tool']!r}, got {getattr(last, 'name', None)!r}"
    if "contains" in expect and (last is None or str(expect["contains"]).lower() not in _text(last).lower()):
        return f"expected the last tool result to contain {expect['contains']!r}; it was {(_text(last) if last else '')[:160]!r}"
    if "not_contains" in expect and last is not None and str(expect["not_contains"]).lower() in _text(last).lower():
        return f"the last tool result contains {expect['not_contains']!r}"
    if "any_contains" in expect and not any(str(expect["any_contains"]).lower() in _text(m).lower() for m in messages):
        return f"no message contains {expect['any_contains']!r}"
    return None


def to_message(step: dict) -> AIMessage:
    calls = []
    for index, call in enumerate(step.get("tool_calls") or []):
        calls.append({"name": call["name"], "args": call.get("args") or {}, "id": call.get("id") or f"call_{uuid.uuid4().hex[:10]}_{index}", "type": "tool_call"})
    usage = step.get("usage") or {"input_tokens": 1000, "output_tokens": 100, "total_tokens": 1100}
    return AIMessage(content=step.get("content", ""), tool_calls=calls, usage_metadata=usage, response_metadata={"model_name": "scripted"})


class ScriptedChatModel(BaseChatModel):
    """Replays SCRIPT. Accepts (and ignores) the provider settings a config passes."""

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)
    bound_tools: list[str] = []

    @property
    def _llm_type(self) -> str:
        return "eval-scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedChatModel:
        names = []
        for tool in tools or []:
            name = getattr(tool, "name", None) or (tool.get("name") if isinstance(tool, dict) else None) or ((tool.get("function") or {}).get("name") if isinstance(tool, dict) else None)
            if name:
                names.append(str(name))
        return self.model_copy(update={"bound_tools": names})

    def _who(self) -> str | None:
        if not self.bound_tools:
            return None
        return "lead" if "write_todos" in self.bound_tools else "sub"

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: CallbackManagerForLLMRun | None = None, **kwargs: Any) -> ChatResult:
        who = self._who()
        if who is None:
            # The summariser (or any tool-less helper call).
            summary = "Summary of the work so far: the task is in progress (scripted summary)."
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=summary, response_metadata={"model_name": "scripted"}))])
        step = SCRIPT.next(who, messages)
        return ChatResult(generations=[ChatGeneration(message=to_message(step))])


def dump_script() -> str:
    return json.dumps({"queues": SCRIPT.queues, "used": SCRIPT.used})
