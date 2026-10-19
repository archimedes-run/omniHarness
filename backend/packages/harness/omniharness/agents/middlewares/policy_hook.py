"""Registration point for a permission policy middleware.

WHY A HOOK RATHER THAN AN IMPORT. The policy layer lives in `app/policy/` — it
belongs to the application, not the harness. `omniharness-harness` is a
standalone distributable package with its own dependency list, and nothing in it
imports from `app/`. An import here would invert that and make the harness
unimportable outside this repository.

So the harness owns the SEAM and the application fills it. The harness knows
that a policy middleware may exist and where in the chain it goes; it knows
nothing about tiers, rules, or confirmation.

This mirrors how the project already handles extension points — config-loaded
`use:` paths, MCP tool interceptors — rather than inventing a new mechanism.

REGISTERING IS NOT OPTIONAL. `app/` registers at gateway startup. If nothing
registers while the policy is enabled — the default — every tool call is
refused with the reason, rather than run unchecked. A bare library consumer
either registers a builder or opts out with `policy.enabled: false`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

#: Set by the application at startup. Takes the resolved AppConfig, returns a
#: middleware or None.
_builder: Callable[[Any], Any] | None = None


def register_policy_middleware_builder(builder: Callable[[Any], Any] | None) -> None:
    """Install the application's policy middleware factory."""
    global _builder
    _builder = builder
    logger.info("policy middleware builder %s", "registered" if builder else "cleared")


def build_policy_middleware(app_config: Any):
    """The policy gate for this agent. None ONLY when the operator opted out.

    FAILS CLOSED. It used to return None when the builder raised, or when no
    builder was registered — and None means NO GATE: every tool ran unchecked
    behind one log line (audit P-2; Article II: no feature may bypass the
    policy engine). Now, with the policy enabled, a gate that cannot be built
    is replaced by one that refuses every tool call and says why. A broken
    policy layer stops the agent's actions; it never removes their check.

    `policy.enabled: false` is the one way to run without a gate, and it is an
    explicit choice, not a fallback.
    """
    policy = getattr(app_config, "policy", None)
    if not getattr(policy, "enabled", True):
        return None
    if _builder is None:
        reason = (
            "the permission policy is enabled, but no policy layer is installed in this process (the gateway installs it at startup with app.policy.registration.install(); an embedded client must do the same, or set policy.enabled: false)"
        )
        logger.error("refusing tool calls: %s", reason)
        return RefuseToolCalls(reason)
    try:
        gate = _builder(app_config)
    except Exception as exc:  # noqa: BLE001 — see the docstring
        logger.exception("the permission policy failed to build; REFUSING tool calls until it is fixed")
        return RefuseToolCalls(f"the permission policy failed to load: {type(exc).__name__}: {exc}")
    if gate is None:
        return RefuseToolCalls("the permission policy is enabled, but its builder produced no gate")
    return gate


def _refusal(request: Any, reason: str):
    from langchain_core.messages import ToolMessage

    call = getattr(request, "tool_call", None) or {}
    name = call.get("name", "this tool")
    return ToolMessage(
        content=f"Refused: {name} was not run, because {reason}. No tool can run until the permission policy is working.",
        tool_call_id=call.get("id", ""),
        name=name,
        status="error",
    )


def _middleware_base():
    from langchain.agents.middleware import AgentMiddleware

    return AgentMiddleware


class RefuseToolCalls(_middleware_base()):
    """The gate when the real one cannot be built: every tool call refused."""

    def __init__(self, reason: str) -> None:
        super().__init__()
        self.reason = reason

    def wrap_tool_call(self, request, handler):
        return _refusal(request, self.reason)

    async def awrap_tool_call(self, request, handler):
        return _refusal(request, self.reason)
