"""Where an invited agent's request came from (FR-006 for delegation).

An agent invited by another — a subagent the lead delegates to through the
`task` tool, and (Phase 2) an agent called in with @ — starts with ONE message:
the instructions the inviting agent wrote. By shape that is a HumanMessage, so
a policy layer reading lineage alone takes it for the user speaking. It is not.
If the lead read a web page and then delegated "send this email", the page is
what asked, and the subagent's send must be confirmable only by the card's
button, exactly as if the lead had proposed it.

So the inviting turn's origin travels with the invitation:

    inviting agent's dispatch      ->  inviting_turn(TurnOrigin(...))   [policy layer]
    construction of the invitee    ->  current_inviting_turn()          [here]
    the invitee's runtime context  <-  invited_agent_context(...)       [here]
    the invitee's tool dispatch    ->  reads INVITED_ORIGIN_KEY         [policy layer]

PROVENANCE ONLY DEGRADES. An invited agent can never be more trusted than the
turn that invited it: "user" can become "content", never the reverse, and that
holds at every level of nesting because each level starts from its inviter's
already-combined origin. No inviting turn at all (an invitation made outside a
gated dispatch) is "unknown", which fails toward card-only.

EVERY WAY OF INVITING AN AGENT MUST USE `invited_agent_context`. The subagent
executor does. An @-invited agent (Phase 2) must build its runtime context the
same way, from the turn that @-mentioned it; an invitation path that skips it
starts its agent as if the user had typed the instructions, which is the hole
this module closes.

The harness defines the carrier and knows nothing about tiers; the application's
policy layer fills and reads it (see `policy_hook.py` for why the dependency
points this way).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

#: Runtime-context keys an invited agent starts with.
INVITED_ORIGIN_KEY = "invited_origin"
INVITED_SOURCE_KEY = "invited_origin_source"
#: The agent that did the inviting, for "Suggested via <agent> from ...".
INVITED_VIA_KEY = "invited_via"
#: The invited agent's own name: the requester its Tier 3 plans name. A key of
#: its own, not `agent_name`, which selects a custom agent's config elsewhere.
INVITED_AGENT_KEY = "invited_agent"
DELEGATION_CHAIN_KEY = "delegation_chain"
#: Filled by the policy layer while an invited agent runs: each Tier 3 call it
#: stopped at, as {"id", "tool"}. Its inviter reads it after the run, so the
#: invited agent never ends with its task silently half done.
STOPPED_AT_KEY = "stopped_at"
#: The invited agent's own checkpoint key (one per delegation), set by the
#: subagent executor. The policy layer records it on a Tier 3 call the agent
#: proposes, so "Continue <agent>" re-enters that delegation's history.
DELEGATION_KEY = "delegation_key"

#: No inviting turn was marked: can't-tell, which fails toward card-only.
UNKNOWN = "unknown"


@dataclass(frozen=True)
class TurnOrigin:
    """What caused the inviting agent's current call, and who that agent is."""

    origin: str
    source: str = ""
    #: The inviting agent's chain, ending with the inviting agent itself.
    chain: tuple[str, ...] = ()
    #: Who the content originally reached through, for nested invitations.
    via: str = ""
    #: Run markers the invitee's runtime context starts with, as (key, value)
    #: pairs: the inviting run's own (a scheduled run's provenance, rule and
    #: firing), so an agent invited during a scheduled run is in that run too.
    #: Filled and read by the policy layer; the harness only carries them.
    run_markers: tuple[tuple[str, str], ...] = ()


_INVITING: ContextVar[TurnOrigin | None] = ContextVar("omniharness_inviting_turn", default=None)


@contextmanager
def inviting_turn(origin: TurnOrigin) -> Iterator[None]:
    """Mark every agent invited during this block as invited by `origin`."""
    token = _INVITING.set(origin)
    try:
        yield
    finally:
        _INVITING.reset(token)


def current_inviting_turn() -> TurnOrigin | None:
    return _INVITING.get()


def invited_agent_context(inviting: TurnOrigin | None, invited_name: str) -> dict:
    """The starting provenance for an agent invited by `inviting`.

    None means nobody marked the invitation, which is can't-tell: "unknown",
    card-only. Never "user" by default.
    """
    if inviting is None:
        inviting = TurnOrigin(origin=UNKNOWN)
    chain = tuple(inviting.chain) or ("lead_agent",)
    return {
        **dict(inviting.run_markers),
        INVITED_ORIGIN_KEY: inviting.origin or UNKNOWN,
        INVITED_SOURCE_KEY: inviting.source,
        INVITED_VIA_KEY: inviting.via or chain[-1],
        INVITED_AGENT_KEY: invited_name,
        DELEGATION_CHAIN_KEY: [*chain, invited_name],
    }


def stopped_notice(agent: str, stopped: list[dict] | None) -> str:
    """The line an invited agent's result ends with when it stopped to ask."""
    if not stopped:
        return ""
    asks = ", ".join(f"`{item.get('id')}` ({item.get('tool')})" for item in stopped)
    return f"[{agent} stopped and is waiting for the user to confirm {asks}. It has NOT finished its task; nothing it asked about has run.]"
