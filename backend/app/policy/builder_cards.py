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
from datetime import UTC, datetime

from .builder_rules import PROPOSING_TOOLS
from .confirm_flow import take_claim
from .models import Outcome, PendingAction
from .pending import PendingStore

logger = logging.getLogger(__name__)


def builder_precheck(tool_name: str, arguments: dict, context: dict | None, store: PendingStore | None) -> tuple[str | None, str]:
    """(why it is refused, or None; the text the card adds). Not a builder
    proposal: (None, "")."""
    if tool_name not in PROPOSING_TOOLS:
        return None, ""
    from omniharness.runtime.builder.controller import get_builder_controller

    controller = get_builder_controller()
    precheck = getattr(controller, "precheck", None)
    if not callable(precheck):
        return "the builder is not available here, so nothing can be saved.", ""
    refused, note, replaces = precheck(tool_name, dict(arguments or {}), dict(context or {}))
    if refused is None and replaces and store is not None:
        ctx = context or {}
        refuse_open_builder_cards(store, ctx.get("thread_id"), ctx.get("user_id"), keep_draft=str(arguments.get("draft_id") or ""), reason="A newer draft replaced this one, so it was not saved.")
    return refused, note


def refuse_open_builder_cards(store: PendingStore, thread_id: str | None, owner_id: str | None, *, reason: str, keep_draft: str = "") -> list[PendingAction]:
    """Refuse (never run) every open builder save card in this chat, except
    one for `keep_draft`. Returns the refused actions."""
    if not thread_id:
        return []
    refused: list[PendingAction] = []
    for action in store.open_in_thread(thread_id, datetime.now(UTC)):
        if action.tool_name not in PROPOSING_TOOLS or action.tool_name == "builder_grant":
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
