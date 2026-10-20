"""FR-023: the honest-limits wording (app/policy/limits.py) reaches people.

limits.py was built and never called (the wiring gate's fifth "built, never
called" instance). These drive the production paths that now use it: a real
agent through PolicyMiddleware for the expiry sentence, and the gateway's
policy inspector for the tier wording and the capabilities that do not exist.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage

from app.gateway.routers import policy as policy_router
from app.policy.config import ConfigLoader
from app.policy.disclose import DisclosureLedger
from app.policy.middleware import PolicyMiddleware
from app.policy.models import PendingAction, Tier

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)

RULES = """
policy:
  rules:
    - pattern: "calendar_read"
      tier: 1
    - pattern: "calendar_decline"
      tier: 3
"""


class RecordingFake(GenericFakeChatModel):
    """Records what the model was shown, so the test reads the agent's input."""

    seen: list = []

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, *args, **kwargs):
        RecordingFake.seen.append([str(m.content) for m in messages])
        return super()._generate(messages, *args, **kwargs)


def test_an_expired_action_is_announced_in_the_limits_wording(tmp_path):
    (tmp_path / "policy.yaml").write_text(RULES)
    expired = PendingAction(
        plan_text="decline Standup",
        tool_name="calendar_decline",
        arguments={"event_id": "e1"},
        targets=["Standup"],
        tier_at_statement=Tier.TIER_3,
        expires_at=NOW - timedelta(minutes=5),
    )
    remaining = [expired]

    def expire_due(now):
        out = list(remaining)
        remaining.clear()
        return out

    middleware = PolicyMiddleware(
        loader=ConfigLoader(path=tmp_path / "policy.yaml"),
        pending=SimpleNamespace(save=lambda a: a, open_actions=lambda now: [], get=lambda i: None, expire_due=expire_due),
        ledger=DisclosureLedger(),
        actor="default",
        now=lambda: NOW,
    )
    RecordingFake.seen = []
    agent = create_agent(model=RecordingFake(messages=iter([AIMessage(content="Hello.")])), tools=[], middleware=[middleware])
    agent.invoke({"messages": [HumanMessage(content="hi")]})

    shown = " ".join(RecordingFake.seen[0])
    assert "I asked to use calendar_decline" in shown
    assert "did NOT do it" in shown and "Nothing changed" in shown


@pytest.fixture
def client(tmp_path, monkeypatch):
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES)
    app_config = SimpleNamespace(policy=SimpleNamespace(enabled=True, rules_path=str(rules), state_dir=str(tmp_path / "state")))
    monkeypatch.setattr("omniharness.config.get_app_config", lambda: app_config)
    app = make_authed_test_app()
    app.include_router(policy_router.router)
    return TestClient(app)


def _explain(client, tool):
    resp = client.get("/api/policy/explain", params={"tool": tool, "args": json.dumps({})})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_the_inspector_says_what_will_happen_in_plain_words(client):
    assert _explain(client, "calendar_read")["in_plain_words"] == "I'll use calendar_read to look that up."
    assert "until you confirm" in _explain(client, "calendar_decline")["in_plain_words"]


def test_a_capability_that_does_not_exist_is_called_absent_not_forbidden(client):
    """ "I can't send email" is true; "I'm not allowed to" invites "allow it then"."""
    body = _explain(client, "send email")
    assert body["absent"].startswith("I can't send email")
    assert _explain(client, "calendar_read")["absent"] is None


def test_the_rules_list_what_the_assistant_cannot_do(client):
    resp = client.get("/api/policy/rules")
    assert resp.status_code == 200, resp.text
    assert [c["capability"] for c in resp.json()["cannot_do"]] == ["send email"]
