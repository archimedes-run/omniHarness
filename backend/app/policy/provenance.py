"""Who is speaking (FR-004).

A DIFFERENT MECHANISM from content lineage, and deliberately kept separate.

    FR-004  who is speaking?          -> runtime context, this module
    FR-005  where did this come from? -> message state, lineage.py

Article III states both in one sentence. In code they read different places and
fail differently: a trigger-injected turn and a user turn quoting a web page are
both "the user speaking" as far as run configuration is concerned, and a genuine
user turn is a genuine user turn regardless of what the run config says. Merging
them is how one gets half-implemented.

WHERE THE MARKER LIVES, AND WHY THAT IS NOT OBVIOUS. Feature 002 writes
`turn_provenance` into the run's `configurable` and `metadata`, deliberately, so
message content cannot forge it. But `ToolCallRequest` carries no run config at
all — `{tool_call, tool, state, runtime}` — and `Runtime` has none either. The
only container that reaches a middleware is `runtime.context`.

LangGraph used to bridge those, falling back from context to configurable. That
fallback was removed in >=1.1.9, and nothing failed at the time because nothing
was reading provenance at dispatch yet: the guarantee quietly became
unenforceable while every test stayed green. The gateway now mirrors the
whitelisted keys across, and
`backend/tests/trigger_engine/test_provenance_visible_at_dispatch.py` guards it.

DO NOT assume this works. Read it, and test it from inside a middleware.
"""

from __future__ import annotations

#: Set by Feature 002's injector. Structural — a message body cannot reach it.
PROVENANCE_KEY = "turn_provenance"
RULE_KEY = "trigger_rule_id"

#: The one value meaning "this turn was generated, not sent by a person".
SYNTHETIC = "synthetic-trigger"


def is_synthetic_turn(runtime_context: dict | None) -> bool:
    """True when the current turn was injected rather than sent by the user.

    Absence of the marker means a user turn: Feature 002 marks what it injects,
    and everything else is a person. That direction is deliberate — the
    alternative would require every human path to assert its own humanity, and
    a path that forgot would be silently treated as a machine.
    """
    if not runtime_context:
        return False
    return runtime_context.get(PROVENANCE_KEY) == SYNTHETIC


def firing_rule(runtime_context: dict | None) -> str | None:
    """Which rule injected this turn, when one did. For the audit trail."""
    if not runtime_context:
        return None
    return runtime_context.get(RULE_KEY)
