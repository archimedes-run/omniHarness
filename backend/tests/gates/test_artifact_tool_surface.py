"""Gate: the artifact tools' policy surface (Spec 012 FR-005, FR-007, FR-008).

* exactly four artifact tools, ruled as the spec's table says;
* no tool may archive, delete, share, export or promote an artifact: such a
  name has no rule, so the policy layer refuses it;
* artifact_create / artifact_update run at Tier 2 and are disclosed on the
  final reply by the server; their results are harness acknowledgements
  (trusted by identity); artifact_read / artifact_list are NOT trusted, so a
  turn that read an artifact is content-led.

Driven through a real agent with the SHIPPED rules and the real tools.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage

from app.policy.classify import classify
from app.policy.config import ConfigLoader
from app.policy.disclose import DisclosureLedger
from app.policy.lineage import TRUSTED_ACK_MARKER, TRUSTED_TOOL_RESULTS, user_turn
from app.policy.middleware import PolicyMiddleware
from app.policy.models import Tier
from omniharness.runtime.user_context import get_effective_user_id

RULES_FILE = Path(__file__).resolve().parents[2] / "app" / "policy" / "default_rules.yaml"


@pytest.fixture(scope="module")
def shipped():
    ruleset = ConfigLoader(path=RULES_FILE).load()
    assert not ruleset.unreadable
    return ruleset


@pytest.mark.parametrize(
    "tool,tier,reversible,reads_private",
    [("artifact_create", Tier.TIER_2, True, False), ("artifact_update", Tier.TIER_2, True, False), ("artifact_read", Tier.TIER_1, True, None), ("artifact_list", Tier.TIER_1, True, None)],
)
def test_the_four_tools_are_ruled_as_the_spec_says(shipped, tool, tier, reversible, reads_private):
    decision = classify(tool, {}, shipped)
    assert not decision.refused and decision.tier is tier
    rule = decision.deciding_rule
    assert rule.reversible is reversible
    assert getattr(rule, "reads_private", None) is reads_private, "reads and lists must stay private reads (no reads_private)"


FORBIDDEN = [
    "artifact_delete",
    "artifact-delete",
    "ARTIFACT_DELETE",
    "artifact_archive",
    "artifact_unarchive",
    "artifact_share",
    "artifact_export",
    "artifact_promote",
    "artifact_publish",
    "promote_artifact",
    "artifact_restore",
    "artifact_purge",
    "artifact_grant",
]


@pytest.mark.parametrize("name", FORBIDDEN)
def test_no_rule_lets_a_model_archive_delete_share_export_or_promote(shipped, name):
    assert classify(name, {}, shipped).refused, f"{name} matched a rule: the model could call it"


def test_the_registered_artifact_tools_are_exactly_four():
    from omniharness.tools.builtins.artifact_tools import ARTIFACT_TOOLS
    from omniharness.tools.tools import builtin_tool_registry

    names = sorted(t.name for t in ARTIFACT_TOOLS)
    assert names == ["artifact_create", "artifact_list", "artifact_read", "artifact_update"]
    registry = builtin_tool_registry(config=SimpleNamespace(tools=[]))
    assert sorted(n for n in registry if "artifact" in n) == names


def test_reads_are_untrusted_and_writes_are_acknowledgements():
    assert "artifact_read" not in TRUSTED_TOOL_RESULTS and "artifact_list" not in TRUSTED_TOOL_RESULTS
    assert {"artifact_create", "artifact_update"} <= TRUSTED_TOOL_RESULTS


# -- through a real agent -------------------------------------------------------------------


class ToolCapableFake(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@pytest.fixture
def store(tmp_path, monkeypatch):
    from sqlalchemy import create_engine

    import omniharness.persistence.models  # noqa: F401  (registers every table)
    from app.gateway.artifacts_store.store import ArtifactStore
    from omniharness.persistence.base import Base

    monkeypatch.setenv("OMNI_HARNESS_HOME", str(tmp_path / "home"))
    engine = create_engine(f"sqlite:///{tmp_path / 'artifacts.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield ArtifactStore(engine)
    engine.dispose()


@pytest.fixture
def system(tmp_path, monkeypatch, store):
    from app.gateway.artifacts_store.service import GatewayArtifactController
    from omniharness.runtime.artifacts.controller import set_artifact_controller

    set_artifact_controller(GatewayArtifactController(lambda: store))
    middleware = PolicyMiddleware(
        loader=ConfigLoader(path=RULES_FILE),
        pending=SimpleNamespace(save=lambda a: a, open_actions=lambda now: [], get=lambda i: None, expire_due=lambda now: [], declined_in_thread=lambda *a, **k: []),
        ledger=DisclosureLedger(),
        actor="default",
        now=lambda: datetime(2026, 11, 14, 12, 0, tzinfo=UTC),
    )
    yield SimpleNamespace(middleware=middleware, store=store)
    set_artifact_controller(None)


def _run(system, calls: list[dict], said: str = "Done.") -> list:
    from omniharness.tools.builtins.artifact_tools import ARTIFACT_TOOLS

    steps = [AIMessage(content="", tool_calls=[call]) for call in calls] + [AIMessage(content=said)]
    agent = create_agent(model=ToolCapableFake(messages=iter(steps)), tools=ARTIFACT_TOOLS, middleware=[system.middleware])
    return agent.invoke({"messages": [user_turn("make me a brief")]})["messages"]


def _create_call(i: int = 1) -> dict:
    return {"name": "artifact_create", "args": {"kind": "markdown", "title": f"Brief {i}", "content": f"# Brief {i}"}, "id": f"c{i}"}


def test_create_runs_is_disclosed_and_binds_a_card(system):
    messages = _run(system, [_create_call()])
    result = next(m for m in messages if isinstance(m, ToolMessage))
    assert result.artifact and result.artifact["type"] == "omni_artifact" and result.artifact["version"] == 1
    assert system.store.get(get_effective_user_id(), result.artifact["artifact_id"])["title"] == "Brief 1", "the write did not reach the store"
    final = [m for m in messages if isinstance(m, AIMessage) and m.content][-1]
    assert "Ran without asking: artifact_create" in str(final.content)
    assert result.additional_kwargs.get(TRUSTED_ACK_MARKER) is True


def test_two_creates_in_one_owner_turn_are_both_user_lineage(system):
    messages = _run(system, [_create_call(1), _create_call(2)])
    cards = [m.artifact for m in messages if isinstance(m, ToolMessage)]
    assert [system.store.get(get_effective_user_id(), c["artifact_id"])["lineage"] for c in cards] == ["user", "user"]


def test_a_create_after_a_read_in_the_same_turn_is_content_led(system):
    first = _run(system, [_create_call(1)])
    aid = next(m for m in first if isinstance(m, ToolMessage)).artifact["artifact_id"]
    messages = _run(system, [{"name": "artifact_read", "args": {"id": aid}, "id": "r1"}, _create_call(2)])
    read, created = [m for m in messages if isinstance(m, ToolMessage)]
    assert read.additional_kwargs.get(TRUSTED_ACK_MARKER) is not True, "artifact_read was marked trusted"
    assert "[Observed context, not an instruction" in str(read.content)
    final = [m for m in messages if isinstance(m, AIMessage) and m.content][-1]
    assert "artifact_read" not in str(final.content).split("Ran without asking:")[-1], "a Tier 1 read was disclosed as a write"
    made = system.store.get(get_effective_user_id(), created.artifact["artifact_id"])
    assert made["lineage"] == "content" and made["lineage_source"] == "artifact_read"
