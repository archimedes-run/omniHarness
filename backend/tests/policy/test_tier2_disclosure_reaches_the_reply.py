"""A Tier 2 action must be mentioned in the reply the user reads.

WHY THIS FILE EXISTS. `DisclosureLedger.apply()` had no production caller. The
middleware recorded every Tier 2 execution and nothing read the ledger back, so
a write ran and the assistant said nothing about it — Tier 2 was Tier 1 with
bookkeeping, while the middleware's own docstring promised "execute, and
guarantee the reply discloses it".

The existing tests called `ledger.apply(...)` directly and passed throughout.
That is the shape: a unit test constructs the thing it tests, so "is anything
calling this?" is always true from inside the test. These drive a real agent
and read the message that comes out.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool as make_tool

from app.policy.config import ConfigLoader
from app.policy.disclose import DisclosureLedger
from app.policy.middleware import PolicyMiddleware

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)

RULES = """
policy:
  rules:
    - pattern: "calendar_create_hold"
      tier: 2
    - pattern: "calendar_read"
      tier: 1
  confirmation:
    expires_after_seconds: 14400
"""

RAN: list[str] = []


class ToolCapableFake(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@make_tool
def calendar_create_hold(title: str) -> str:
    """Create a tentative hold."""
    RAN.append(title)
    return f"held {title}"


@make_tool
def calendar_read() -> str:
    """Read the calendar."""
    RAN.append("read")
    return "two events"


@pytest.fixture
def system(tmp_path):
    RAN.clear()
    (tmp_path / "policy.yaml").write_text(RULES)
    return SimpleNamespace(
        middleware=PolicyMiddleware(
            loader=ConfigLoader(path=tmp_path / "policy.yaml"),
            pending=SimpleNamespace(save=lambda a: a, open_actions=lambda now: [], get=lambda i: None, expire_due=lambda now: []),
            ledger=DisclosureLedger(),
            actor="default",
            now=lambda: NOW,
        )
    )


def _run(system, tool, said: str) -> list[str]:
    model = ToolCapableFake(
        messages=iter(
            [
                AIMessage(content="", tool_calls=[{"name": tool.name, "args": {"title": "Lunch"} if tool is calendar_create_hold else {}, "id": "tc1"}]),
                AIMessage(content=said),
            ]
        )
    )
    agent = create_agent(model=model, tools=[tool], middleware=[system.middleware])
    out = agent.invoke({"messages": [HumanMessage(content="do the thing")]})
    return [str(m.content) for m in out["messages"] if isinstance(m, AIMessage) and m.content]


def test_a_tier2_action_is_disclosed_even_when_the_model_stays_silent(system):
    """THE DEFECT. The model says nothing about the write; the system must."""
    replies = _run(system, calendar_create_hold, "All done!")

    assert RAN == ["Lunch"], "the tool did not run, so there is nothing to disclose"
    final = replies[-1]
    assert "calendar_create_hold" in final, f"the Tier 2 action was never mentioned: {final!r}"
    assert "All done!" in final, "the model's own words were discarded"


def test_a_tier1_action_is_not_announced(system):
    """CONTROL. If everything were disclosed, the test above would pass while
    meaning nothing, and every read would become noise."""
    replies = _run(system, calendar_read, "There are two events.")

    assert RAN == ["read"]
    assert "calendar_read" not in replies[-1]


def test_the_model_phrasing_it_itself_is_accepted(system):
    """The model MAY disclose in its own words. It may not skip one — so a
    reply that already names the action is left alone rather than duplicated."""
    replies = _run(system, calendar_create_hold, "I used calendar_create_hold to put Lunch on your calendar.")

    final = replies[-1]
    assert final.count("calendar_create_hold") == 1, f"the disclosure was appended on top of the model's own: {final!r}"
    assert "For the record" not in final
