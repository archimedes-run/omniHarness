"""The chat builder's cards in the confirmations store (Spec 010, Slice 2).

A builder save, grant or undo is an ordinary Tier 3 pending action: the same
store, claim, card and typed-reply gate as every other (confirm_flow). Two
things are particular to it, both here:

- BEFORE THE CARD (`builder_precheck`): the builder checks the proposal, so a
  card the owner would approve and then see fail is never shown (the draft is
  this chat's, its base version is still current, its target is not the
  proposing agent or its call chain), and supplies the card's text: the draft
  or the before/after diff. Until Slice 3's dedicated cards, the existing
  pending-action card renders it as plain text.
- ONE OPEN BUILD CARD PER CHAT (`refuse_open_builder_cards`): a new draft's
  card replaces the older ones in the same chat, and dropping the build (the
  chip's x) refuses its open cards, so a stale or dropped draft can never be
  saved by a later press. Claimed through the one claim site, so a
  confirmation racing it either won (and ran) or finds it resolved.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .builder_rules import PROPOSING_TOOLS
from .confirm_flow import take_claim
from .models import Outcome, PendingAction
from .pending import PendingStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BuilderCheck:
    """What the builder said about a proposal before its card."""

    refused: str | None = None
    #: The card's text for the OWNER (the draft or diff, in full).
    note: str = ""
    #: The arguments the card records (a save pins its exact draft).
    arguments: dict = field(default_factory=dict)
    #: A draft's own cause, when it was not the owner's request: the card's
    #: origin may only degrade to it, never improve.
    origin: tuple[str, str] | None = None
    #: Why only the card's button confirms it ("" when typing may).
    button_only: str = ""


#: What the MODEL reads in place of the builder's card text: the card shows the
#: owner the draft, which can hold stored text; the model's copy never does.
MODEL_NOTE = "The draft or change is shown to the user in full on its card."


def builder_precheck(tool_name: str, arguments: dict, context: dict | None, store: PendingStore | None) -> BuilderCheck:
    """The builder's check of a proposal before its card. Not a builder
    proposal: nothing to say, arguments unchanged."""
    if tool_name not in PROPOSING_TOOLS:
        return BuilderCheck(arguments=arguments)
    from omniharness.runtime.builder.controller import get_builder_controller

    controller = get_builder_controller()
    precheck = getattr(controller, "precheck", None)
    if not callable(precheck):
        return BuilderCheck(refused="the builder is not available here, so nothing can be saved.", arguments=arguments)
    out = precheck(tool_name, dict(arguments or {}), dict(context or {}))
    pinned = out.get("arguments") or arguments
    if out.get("refused") is None and out.get("replaces") and store is not None:
        ctx = context or {}
        refuse_open_builder_cards(store, ctx.get("thread_id"), ctx.get("user_id"), keep_draft=str(pinned.get("draft_id") or ""), reason="A newer draft replaced this one, so it was not saved.")
    origin = out.get("origin")
    return BuilderCheck(refused=out.get("refused"), note=out.get("note") or "", arguments=pinned, origin=tuple(origin) if origin else None, button_only=out.get("button_only") or "")


def refuse_open_builder_cards(store: PendingStore, thread_id: str | None, owner_id: str | None, *, reason: str, keep_draft: str = "", include_grants: bool = False) -> list[PendingAction]:
    """Refuse (never run) every open builder save and undo card in this chat
    (and its grant cards with `include_grants`: dropping the build), except a
    save card for `keep_draft`. Returns the refused actions."""
    if not thread_id:
        return []
    refused: list[PendingAction] = []
    for action in store.open_in_thread(thread_id, datetime.now(UTC)):
        if action.tool_name not in PROPOSING_TOOLS or (action.tool_name == "builder_grant" and not include_grants):
            continue
        if owner_id is not None and action.owner_id is not None and str(action.owner_id) != str(owner_id):
            continue
        if keep_draft and str((action.arguments or {}).get("draft_id") or "") == keep_draft:
            continue
        claimed = take_claim(store, action.id, "builder")
        if claimed is None:
            continue
        store.resolve(claimed, Outcome.SUPERSEDED, reason)
        refused.append(claimed)
    if refused:
        logger.info("builder: refused %d open card(s) in thread %s", len(refused), thread_id)
    return refused
