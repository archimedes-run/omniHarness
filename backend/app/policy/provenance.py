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

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

#: Set by Feature 002's injector. Structural — a message body cannot reach it.
PROVENANCE_KEY = "turn_provenance"
RULE_KEY = "trigger_rule_id"
#: Which firing of the rule this run is: the event's fingerprint, the same for
#: every attempt at it. Standing grants count a run's actions under it, so a
#: retry continues the count (grants.GrantRunCounts).
FIRING_KEY = "trigger_firing_id"

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


# -- how a write was authorised, for the record it leaves ---------------------
#
# A ledger row says who made each change (Feature 005, FR-007). Since Feature
# 006 a routine ledger write can run at Tier 2 (disclosed in the reply) or
# under a standing grant in a scheduled run, so "the assistant, confirmed by
# you" is no longer true of every assistant write. The policy middleware sets
# this around the handler it runs; the confirmation route runs tools outside
# it, so the default is the confirmed case.

CONFIRMED = "confirmed"
DISCLOSED = "disclosed"
GRANTED = "granted"

_executed_as: ContextVar[str] = ContextVar("policy_executed_as", default=CONFIRMED)


@contextmanager
def executed_as(how: str) -> Iterator[None]:
    token = _executed_as.set(how)
    try:
        yield
    finally:
        _executed_as.reset(token)


def current_execution() -> str:
    """confirmed, disclosed (Tier 2) or granted (a standing grant)."""
    return _executed_as.get()
