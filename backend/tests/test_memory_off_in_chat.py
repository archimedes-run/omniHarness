"""Memory off in a chat (live chat 2026-11-14: "do not reference my past chats
and history with you" was answered from memory).

Asserts on what the model is given (the assembled system prompt) and on
whether a memory write is queued, never on model text. The end-to-end path
through the gateway is the M-MEMORY-OFF / M-MEMORY-ON eval tasks.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from omniharness.agents.memory_switch import MEMORY_OFF_SECTION, MEMORY_RULE, asks_memory_off

MARKER = "ZEBRA-7731 Opportunity scouting (judging, press, speaking)"


@pytest.fixture
def memory_with_marker(monkeypatch):
    from omniharness.agents import memory as memory_pkg

    data = {"user": {"workContext": {"summary": MARKER}}, "facts": [{"id": "f1", "content": MARKER, "category": "goal", "confidence": 0.95}]}
    monkeypatch.setattr(memory_pkg, "get_memory_data", lambda *a, **k: data)
    return data


def _config():
    return SimpleNamespace(memory=SimpleNamespace(enabled=True, injection_enabled=True, max_injection_tokens=2000))


def test_the_marker_is_in_the_prompt_only_when_memory_is_on(memory_with_marker) -> None:
    from omniharness.agents.lead_agent.prompt import _get_memory_context

    on = _get_memory_context(app_config=_config(), user_id="u1")
    assert "ZEBRA-7731" in on and MEMORY_RULE in on, "memory (with its background rule) should be injected when on"


def test_memory_off_removes_the_memory_block_from_the_assembled_prompt(memory_with_marker, monkeypatch) -> None:
    from omniharness.agents.lead_agent import prompt

    seen: list[bool] = []
    real = prompt._get_memory_context

    def spy(*a, **k):
        seen.append(True)
        return real(*a, app_config=_config(), user_id="u1")

    monkeypatch.setattr(prompt, "_get_memory_context", spy)
    monkeypatch.setattr(prompt, "get_skills_prompt_section", lambda *a, **k: "")
    monkeypatch.setattr(prompt, "get_deferred_tools_prompt_section", lambda *a, **k: "")
    monkeypatch.setattr(prompt, "_build_custom_mounts_section", lambda *a, **k: "")
    monkeypatch.setattr(prompt, "get_agent_soul", lambda *a, **k: "")
    monkeypatch.setattr(prompt, "coding_jobs_section", lambda: "")
    off = prompt.apply_prompt_template(memory_off=True)
    assert "ZEBRA-7731" not in off and "Opportunity scouting" not in off
    assert MEMORY_OFF_SECTION.strip() in off
    assert not seen, "memory was read for a chat with memory off"
    on = prompt.apply_prompt_template(memory_off=False)
    assert "ZEBRA-7731" in on


def test_the_closed_set_of_phrasings() -> None:
    for text in (
        "What can you do for me, do not reference my past chats and history with you",
        "Don't use my memory for this",
        "please do not use memory",
        "without using my past conversations, plan my week",
        "forget what you know about me",
        "dont bring up our previous chats",
        "turn off your memory",
    ):
        assert asks_memory_off(text), text
    for text in ("what is in my memory?", "remember that I like tea", "summarise our previous chat", "who is Justin Bojarski", "do not use bullet points", "history of Rome without dates"):
        assert not asks_memory_off(text), text


def test_no_memory_write_from_a_chat_with_memory_off(monkeypatch) -> None:
    from omniharness.agents.middlewares import memory_middleware as mm

    queued: list[dict] = []
    monkeypatch.setattr(mm, "get_memory_queue", lambda: SimpleNamespace(add=lambda **k: queued.append(k)))
    middleware = mm.MemoryMiddleware(memory_config=SimpleNamespace(enabled=True))
    state = {"messages": [HumanMessage(content="what can you do"), AIMessage(content="I can research.")]}
    middleware.after_agent(state, SimpleNamespace(context={"thread_id": "t1", "memory_off": True}))
    assert queued == []
    middleware.after_agent(state, SimpleNamespace(context={"thread_id": "t1"}))
    assert len(queued) == 1, "the control: a chat with memory on queues the update"


def test_no_memory_write_before_a_summary_when_memory_is_off(monkeypatch) -> None:
    from omniharness.agents.memory import summarization_hook as hook

    queued: list[dict] = []
    monkeypatch.setattr(hook, "get_memory_queue", lambda: SimpleNamespace(add_nowait=lambda **k: queued.append(k)))
    monkeypatch.setattr(hook, "get_memory_config", lambda: SimpleNamespace(enabled=True))
    msgs = (HumanMessage(content="hi"), AIMessage(content="hello"))
    event = SimpleNamespace(messages_to_summarize=msgs, preserved_messages=(), thread_id="t1", agent_name=None, runtime=SimpleNamespace(context={"memory_off": True}))
    hook.memory_flush_hook(event)
    assert queued == []
    event.runtime = SimpleNamespace(context={})
    hook.memory_flush_hook(event)
    assert len(queued) == 1


class _Threads:
    """A thread store with the two calls the switch uses."""

    def __init__(self, ids: list[str]) -> None:
        self.rows: dict[str, dict[str, Any]] = {i: {"thread_id": i, "metadata": {}} for i in ids}

    async def get(self, thread_id, *, user_id=None):
        return self.rows.get(thread_id)

    async def update_metadata(self, thread_id, metadata, *, user_id=None):
        if thread_id in self.rows:
            self.rows[thread_id]["metadata"].update(metadata)


def _request(store) -> Any:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(thread_store=store)))


def _input(text: str) -> dict:
    return {"messages": [HumanMessage(content=text)]}


def test_the_switch_is_per_chat_and_holds_from_that_turn_on() -> None:
    from app.gateway.routers.thread_memory import chat_memory_off, set_chat_memory_off
    from app.gateway.services import _memory_off_for_run

    store = _Threads(["a", "b"])
    body = SimpleNamespace(context={})
    run = lambda t, text, own=True: asyncio.run(_memory_off_for_run(_request(store), t, body, _input(text), own_turn=own))  # noqa: E731
    assert run("a", "What can you do for me, do not reference my past chats") == (True, "message")
    asyncio.run(set_chat_memory_off(store, "a", True, "message"))
    # The next message in that chat: still off (stored), nothing to store again.
    assert run("a", "and what else?") == (True, None)
    # Another chat is untouched: the switch is per chat, never global.
    assert run("b", "what can you do?") == (False, None)
    assert asyncio.run(chat_memory_off(store, "b")) == (False, None)
    # A relayed message (not the owner's own turn) never switches it.
    assert run("b", "do not use my memory", own=False) == (False, None)
    # The composer toggle sent with a new chat's first message.
    assert asyncio.run(_memory_off_for_run(_request(store), "b", SimpleNamespace(context={"memory_off": True}), _input("hi"), own_turn=True)) == (True, "toggle")
    # The owner switches it back on.
    asyncio.run(set_chat_memory_off(store, "a", False, "toggle"))
    assert run("a", "and now?") == (False, None)


def test_a_client_cannot_set_the_switch_through_thread_metadata_or_run_context() -> None:
    from app.gateway.routers.threads import _SERVER_RESERVED_METADATA_KEYS
    from app.gateway.services import _CLIENT_CONTEXT_KEYS, SERVER_OWNED_RUN_KEYS

    assert {"memory_off", "memory_off_source"} <= _SERVER_RESERVED_METADATA_KEYS
    assert "memory_off" in SERVER_OWNED_RUN_KEYS and "memory_off" not in _CLIENT_CONTEXT_KEYS
