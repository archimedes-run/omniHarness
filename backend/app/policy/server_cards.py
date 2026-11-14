"""Cards a server component raises itself (Spec 010: the builder's own save
card and the permission card after a save). Only the builder service calls
`raise_card` (tests/gates/test_server_cards_gate.py).

The policy middleware states a card from a tool call; these come from the
builder, with no tool call to wrap. The middleware does not call this module's
`raise_card`; both use the SAME helpers for who asked and the run's markers
(`requester_of`, `run_markers_of`, which the middleware's `_requester` and
`_run_markers` delegate to), the same turn key (`turn_key_of`: the id of the
message that started the turn, from `private_reads_in_turn`, the middleware's
`privacy.turn_key`), the same tool surface, expiry and plan text, the same
per-chat lock (`middleware._proposing`, held by the caller across its own
checks too: `card_lock`), and the same trace step stamp
(`needs_confirmation` with the card id).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import PendingAction, Tier, default_expiry
from .pending import PendingStore


def requester_of(context: dict | None) -> str:
    """Who asked: an invited agent, a custom agent's own chat, else the lead.
    The bootstrap flow is the lead setting up a new agent (spec 010)."""
    ctx = context or {}
    return ctx.get("invited_agent") or (None if ctx.get("is_bootstrap") else ctx.get("agent_name")) or "lead_agent"


def chain_of(context: dict | None) -> tuple[str, ...]:
    return tuple((context or {}).get("delegation_chain") or ())


def run_markers_of(context: dict | None) -> tuple[tuple[str, str], ...]:
    """A scheduled run's markers in this context, if any."""
    from .provenance import FIRING_KEY, GRANTS_OWNER_KEY, PROVENANCE_KEY, RULE_KEY

    ctx = context or {}
    return tuple((k, str(ctx[k])) for k in (PROVENANCE_KEY, RULE_KEY, FIRING_KEY, GRANTS_OWNER_KEY) if ctx.get(k))


def turn_key_of(messages: list[Any] | None, policy: Any) -> str:
    """The turn a card belongs to, as the middleware groups a proposed card:
    the id of the message that started the turn (`privacy.turn_key`)."""
    from .private_reads import private_reads_in_turn
    from .registration import shared_loader

    return private_reads_in_turn(messages, shared_loader(policy).load(notify=False)).turn_key


def card_lock(context: dict | None):
    """The per-chat lock a card is stated under (middleware._proposing),
    re-entrant, so a caller holds it across its own checks and the raise."""
    from .middleware import _proposing

    ctx = context or {}
    return _proposing(str(ctx["user_id"]) if ctx.get("user_id") else None, ctx.get("thread_id"))


def raise_card(
    *,
    policy: Any,
    tool_name: str,
    arguments: dict,
    note: str,
    context: dict | None = None,
    messages: list[Any] | None = None,
    origin: str,
    origin_source: str = "",
    button_only_reason: str = "",
    like: PendingAction | None = None,
) -> PendingAction:
    """Record a Tier 3 card raised by the server. `context` and `messages`:
    the run it is raised in and its messages (the turn key); `like`: an
    existing card whose run it belongs to (a card raised after another was
    confirmed). Stamps the current tool call's trace step like a proposed
    card's."""
    from omniharness.agents.tool_surface import surface_of

    from .middleware import PolicyMiddleware, _proposing, _step
    from .registration import shared_loader
    from .targets import resolve_targets

    ctx = dict(context or {})
    targets = resolve_targets(tool_name, arguments)
    ruleset = shared_loader(policy).load(notify=False)
    card = PendingAction(
        plan_text="",
        tool_name=tool_name,
        arguments=arguments,
        targets=targets,
        tier_at_statement=Tier.TIER_3,
        expires_at=default_expiry(datetime.now(UTC), ruleset.expires_after_seconds),
        thread_id=like.thread_id if like else ctx.get("thread_id"),
        requester=like.requester if like else requester_of(ctx),
        delegation_chain=like.delegation_chain if like else chain_of(ctx),
        origin=origin if origin in ("user", "content", "automation", "unknown") else "unknown",
        origin_source=origin_source,
        owner_id=like.owner_id if like else (str(ctx["user_id"]) if ctx.get("user_id") else None),
        surface=dict(like.surface or {}) if like else surface_of(ctx),
        run_markers=like.run_markers if like else run_markers_of(ctx),
        private_read=like.private_read if like else True,
        # A card raised after another was answered is its own group: the lead
        # resumes on the first answer, not when both are answered.
        group_key=f"after:{like.id}" if like else turn_key_of(messages, policy),
        button_only_reason=button_only_reason,
    )
    card.plan_text = PolicyMiddleware._plan_text(tool_name, targets, card.requester, card.delegation_chain, card.id, arguments, origin_note=card.origin_note())
    if note:
        card.plan_text = f"{card.plan_text}\n\n{note}"
    with _proposing(card.owner_id, card.thread_id):
        PendingStore(directory=Path(policy.state_dir) / "pending").save(card)
    _step().update({"outcome": "needs_confirmation", "card_id": card.id, "tier": int(card.tier_at_statement)})
    return card
