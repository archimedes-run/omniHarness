"""The three read-only checks a connector source must pass (Spec 011 FR-010).

Independent on purpose: each answers its own question from its own data, and
any ONE failing refuses the source (fail closed). Removing one check still
leaves the others standing.

  1. allowlist: the tool is in the catalog's read allowlist (catalog.py).
  2. tier: the policy rules in force classify the call Tier 1, under every
     lineage flag (after content, after a private read), with no exception
     raising it and no refusal. Unreadable rules fail it.
  3. floor: no runtime floor applies to the tool (policy runtime_floors).

They run at registration (a manifest naming a source that fails is refused)
and on EVERY bridge call and refresh, before the cache is read: a rules change
that lifts a tool out of Tier 1 stops the source at once, cached data included.

First-party (service) sources run fixed in-process readers that only read;
there is no tool to classify. They pass only when their entry is one the
catalog itself defines (the allowlist question for services).
"""

from __future__ import annotations

from typing import Any

from app.gateway.apps.catalog import CATALOG, READ_ALLOWLIST, Entry
from app.policy.classify import classify
from app.policy.models import Tier
from app.policy.runtime_floors import runtime_floor
from omniharness.tools.names import canonical_tool_name

#: Every combination of the lineage flags an exception can read.
_LINEAGES = ((False, False), (True, False), (False, True), (True, True))


def check_allowlist(entry: Entry) -> str | None:
    if entry.kind == "service":
        return None if CATALOG.get(entry.id) is entry and entry.read is not None else "not a reader the catalog defines"
    if entry.tool not in READ_ALLOWLIST:
        return f"{entry.tool} is not in the catalog's read allowlist"
    return None


def check_tier(entry: Entry, arguments: dict[str, Any], ruleset) -> str | None:
    if entry.kind == "service":
        return None
    if ruleset is None or getattr(ruleset, "unreadable", True):
        return "the policy rules could not be read"
    for after_content, private_read in _LINEAGES:
        decision = classify(entry.policy_name, arguments, ruleset, after_content=after_content, private_read=private_read)
        if decision.refused:
            return f"{entry.tool} has no policy rule"
        if decision.tier != Tier.TIER_1 or decision.raised_by is not None:
            return f"{entry.tool} is not Tier 1 in the policy rules"
    return None


def check_floor(entry: Entry) -> str | None:
    if entry.kind == "service":
        return None
    if runtime_floor(canonical_tool_name(entry.policy_name)) is not None:
        return f"a runtime floor applies to {entry.tool}"
    return None


def read_only_refusal(entry: Entry, arguments: dict[str, Any], ruleset) -> str | None:
    """None when all three pass; else the first refusal's reason."""
    for reason in (check_allowlist(entry), check_tier(entry, arguments, ruleset), check_floor(entry)):
        if reason is not None:
            return reason
    return None


def rules_in_force(app_state) -> Any:
    """The policy rules every agent is held to (the shared loader), read
    without notifying listeners (a read surface). None when they cannot be
    loaded: check_tier then refuses."""
    from app.policy.registration import shared_loader

    try:
        return shared_loader(app_state.config.policy).load(notify=False)
    except Exception:  # noqa: BLE001 - no rules: fail closed
        return None
