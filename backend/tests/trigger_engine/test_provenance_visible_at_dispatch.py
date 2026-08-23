"""Feature 002's synthetic-turn marker must be readable at TOOL DISPATCH.

This protects an existing guarantee, and is not groundwork for a later feature.
FR-009 says a trigger-injected turn is distinguishable from a real user turn
structurally — a marker in the run's configuration, where a message body cannot
reach it. That is only a guarantee if the code enforcing it can read the marker.

The reader that matters is a middleware's ``wrap_tool_call``. Its
``ToolCallRequest`` carries ``{tool_call, tool, state, runtime}`` and no run
config at all, and ``Runtime`` has no config either. The only container that
reaches it is ``config["context"]``, built by ``_build_runtime_context``.

The injector writes the marker to ``configurable`` and ``metadata``. LangGraph
used to bridge those into tool context by falling back to ``configurable``; that
fallback was removed in >=1.1.9. Nothing failed at the time, because nothing was
reading provenance from tool context yet — the guarantee quietly became
unenforceable while every test stayed green.

These tests are what makes the next such upgrade fail loudly.
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware

from app.gateway.services import _CONTEXT_CONFIGURABLE_KEYS, build_run_config
from app.trigger_engine.injector import PROVENANCE_KEY, RULE_KEY, SYNTHETIC

# The worker builds ToolRuntime.context from config["context"]; import the real
# functions rather than reimplementing the rule they encode.
from omniharness.runtime.runs.worker import _build_runtime_context, _install_runtime_context


def _injected_payload_config(thread_id: str = "t1", rule_id: str = "r1") -> dict[str, Any]:
    """Exactly what TurnInjector.inject posts, kept in sync by test_matches_injector."""
    return {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
            PROVENANCE_KEY: SYNTHETIC,
            RULE_KEY: rule_id,
        }
    }


def _runtime_context_for(request_config: dict[str, Any], *, thread_id: str = "t1") -> dict[str, Any]:
    """Run the real gateway + worker pipeline and return ToolRuntime.context."""
    config = build_run_config(thread_id, request_config, {PROVENANCE_KEY: SYNTHETIC})
    runtime_ctx = _build_runtime_context(thread_id, "run-1", config.get("context"), None)
    _install_runtime_context(config, runtime_ctx)
    return config["context"]


# ---------------------------------------------------------------------------
# The guarantee
# ---------------------------------------------------------------------------


def test_synthetic_marker_reaches_tool_runtime_context():
    ctx = _runtime_context_for(_injected_payload_config())

    assert ctx.get(PROVENANCE_KEY) == SYNTHETIC, (
        "a trigger-injected turn is not identifiable from ToolRuntime.context. FR-009's structural guarantee is unenforceable at dispatch: no middleware can refuse an action on the grounds that a synthetic turn requested it."
    )
    assert ctx.get(RULE_KEY) == "r1"


def test_a_real_user_turn_carries_no_marker():
    """The guarantee is only worth anything if it discriminates."""
    ctx = _runtime_context_for({"configurable": {"thread_id": "t1"}})

    assert PROVENANCE_KEY not in ctx


def test_thread_id_survives_the_mirroring():
    """The mirroring must not be achieved by sending both containers.

    build_run_config prefers `context` when a request carries both and drops
    `configurable` wholesale — taking thread_id with it, which breaks
    checkpointing. This pins the failure so nobody "simplifies" it back.
    """
    config = build_run_config("t1", _injected_payload_config(), None)

    assert config["configurable"]["thread_id"] == "t1"
    assert config["context"][PROVENANCE_KEY] == SYNTHETIC


def test_sending_both_containers_still_drops_configurable():
    """Documents the trap this design avoids, so the behaviour is not a surprise."""
    config = build_run_config(
        "t1",
        {
            "configurable": {"thread_id": "t1", PROVENANCE_KEY: SYNTHETIC},
            "context": {PROVENANCE_KEY: SYNTHETIC},
        },
        None,
    )

    assert config.get("configurable") is None, "build_run_config no longer drops configurable when both are sent — the injector comment and _mirror_runtime_visible_keys docstring both cite this behaviour and must be updated"


def test_marker_keys_are_whitelisted():
    """A key absent from the whitelist is silently dropped by
    merge_run_context_overrides, which is how this broke the first time."""
    assert PROVENANCE_KEY in _CONTEXT_CONFIGURABLE_KEYS
    assert RULE_KEY in _CONTEXT_CONFIGURABLE_KEYS


def test_matches_injector():
    """Pins this fixture to the real payload.

    If TurnInjector.inject changes shape, these tests must be updated with it
    rather than passing against a payload the injector no longer sends.
    """
    import inspect

    from app.trigger_engine.injector import TurnInjector

    src = inspect.getsource(TurnInjector.inject)
    assert '"configurable"' in src
    assert "PROVENANCE_KEY: SYNTHETIC" in src
    assert '"context"' not in src.split("payload = {")[1].split("}")[0], "the injector now sends a top-level 'context' — build_run_config will drop 'configurable' and thread_id with it"


# ---------------------------------------------------------------------------
# The reader that matters: inside wrap_tool_call
# ---------------------------------------------------------------------------


class _ProvenanceProbe(AgentMiddleware):
    """A stand-in for Feature 003's policy layer: reads provenance where a
    policy decision would actually be made."""

    def __init__(self) -> None:
        super().__init__()
        self.seen: list[dict[str, Any]] = []

    def wrap_tool_call(self, request, handler):  # type: ignore[override]
        ctx = getattr(request.runtime, "context", None) or {}
        self.seen.append(
            {
                "tool": request.tool.name if request.tool is not None else None,
                "provenance": ctx.get(PROVENANCE_KEY),
                "rule_id": ctx.get(RULE_KEY),
            }
        )
        return handler(request)


def _run_probe(request_config: dict[str, Any]) -> dict[str, Any]:
    """Drive a real middleware through the real ToolCallRequest shape."""
    from types import SimpleNamespace

    from langchain_core.tools import tool as make_tool

    @make_tool
    def do_thing(x: int) -> str:
        """A tool a policy layer would classify."""
        return str(x)

    probe = _ProvenanceProbe()
    ctx = _runtime_context_for(request_config)
    request = SimpleNamespace(
        tool_call={"name": "do_thing", "args": {"x": 1}, "id": "tc1", "type": "tool_call"},
        tool=do_thing,
        state={"messages": []},
        runtime=SimpleNamespace(context=ctx),
    )

    probe.wrap_tool_call(request, lambda _r: "executed")
    assert probe.seen, "wrap_tool_call did not run"
    return probe.seen[0]


def test_middleware_sees_a_synthetic_turn():
    """The whole point. A policy layer must be able to refuse a Tier 3 action
    on the grounds that a trigger, not the user, asked for it."""
    seen = _run_probe(_injected_payload_config())

    assert seen["provenance"] == SYNTHETIC
    assert seen["rule_id"] == "r1"


def test_middleware_sees_a_user_turn_as_unmarked():
    seen = _run_probe({"configurable": {"thread_id": "t1"}})

    assert seen["provenance"] is None


def test_middleware_can_refuse_based_on_provenance():
    """Deny must be expressible: wrap_tool_call may decline to call the handler.

    Without this, provenance is observable but not actionable.
    """
    from types import SimpleNamespace

    executed: list[str] = []

    class _Refuser(AgentMiddleware):
        def wrap_tool_call(self, request, handler):  # type: ignore[override]
            ctx = getattr(request.runtime, "context", None) or {}
            if ctx.get(PROVENANCE_KEY) == SYNTHETIC:
                return "refused: synthetic turn"
            return handler(request)

    ctx = _runtime_context_for(_injected_payload_config())
    request = SimpleNamespace(
        tool_call={"name": "do_thing", "args": {}, "id": "tc1", "type": "tool_call"},
        tool=None,
        state={"messages": []},
        runtime=SimpleNamespace(context=ctx),
    )

    result = _Refuser().wrap_tool_call(request, lambda _r: executed.append("ran") or "ran")

    assert result == "refused: synthetic turn"
    assert not executed, "the tool ran despite the middleware refusing it"


def test_tool_call_request_still_carries_no_config():
    """Pins the constraint that forces the mirroring to exist.

    If a future LangChain adds config to ToolCallRequest, the mirroring becomes
    optional and this test says so.
    """
    import dataclasses

    from langchain.agents.middleware.types import ToolCallRequest

    fields = {f.name for f in dataclasses.fields(ToolCallRequest)}
    assert "config" not in fields, "ToolCallRequest now exposes config — _mirror_runtime_visible_keys may no longer be the only way to reach provenance at dispatch"
