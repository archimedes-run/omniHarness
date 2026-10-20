"""Every registered tool resolves to an EXPLICIT rule, or it is refused (007).

The bug this closes: the Google Calendar MCP server names its tools
`create-event`, `search-events`, ...; the rules said `create_event`. Nothing
matched, the no-rule default (Tier 3) applied, and nothing anywhere said so —
the default hid the mismatch. The same mismatch on a rule that RAISES a tier
would have silently made a write less strict.

So a default tier is no longer given. A tool no rule names is:

  * not offered to the model (PolicyMiddleware.wrap_model_call drops it);
  * not run if called anyway (PolicyMiddleware.wrap_tool_call refuses it, with
    the reason below);
  * listed in the log — at startup for the tools registered then, and when MCP
    tools load (they load lazily, after startup);
  * shown as "No policy rule" on its source in GET /api/tool-sources.

Matching is `classify()`, the same function dispatch uses, so this check and
the gate cannot disagree about what "has a rule" means.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from dataclasses import dataclass

from .classify import classify
from .config import RuleSet

logger = logging.getLogger(__name__)


def has_rule(tool_name: str, ruleset: RuleSet) -> bool:
    """True when an explicit rule names this tool (or the rules are unreadable,
    in which case everything is Tier 3 and nothing is refused)."""
    return not classify(tool_name, {}, ruleset).refused


def refusal_text(tool_name: str) -> str:
    """What the model (and so the user) is told when it calls an unruled tool."""
    return (
        f"Refused: {tool_name} was not run, because no permission policy rule covers it, "
        "and a tool without a rule is never run on a default. To use it, add a rule naming it "
        "to the policy rules file (the Policy page shows which file is in force)."
    )


@dataclass(frozen=True)
class CoverageReport:
    checked: tuple[str, ...]
    unruled: tuple[str, ...]


#: Names already reported, so a per-turn check does not repeat the same line
#: on every model call.
_reported: set[str] = set()
_reported_lock = threading.Lock()


def check(tool_names: Iterable[str], ruleset: RuleSet, *, where: str) -> CoverageReport:
    """Which of these tools have no rule; logs each newly seen one, once."""
    names = tuple(dict.fromkeys(n for n in tool_names if n))
    unruled = tuple(n for n in names if not has_rule(n, ruleset))
    with _reported_lock:
        new = [n for n in unruled if n not in _reported]
        _reported.update(new)
    if new:
        logger.warning(
            "policy: %d tool(s) have NO policy rule and are REFUSED (not offered to the model, not run) [%s]: %s",
            len(new),
            where,
            ", ".join(sorted(new)),
        )
    return CoverageReport(checked=names, unruled=unruled)


def startup_check(app_config) -> CoverageReport | None:
    """At gateway startup: every tool registrable now has a rule, or is listed."""
    from omniharness.tools.tools import registrable_tool_names

    from .registration import shared_loader

    policy = getattr(app_config, "policy", None)
    if not getattr(policy, "enabled", True):
        return None
    ruleset = shared_loader(policy).load(notify=False)
    report = check(registrable_tool_names(app_config), ruleset, where="startup")
    if not report.unruled:
        logger.info("policy: all %d registered tool(s) resolve to an explicit rule", len(report.checked))
    return report


def on_mcp_tools_loaded(tools) -> None:
    """Listener for the MCP cache: the same check, for the tools just loaded."""
    from omniharness.config import get_app_config

    from .registration import shared_loader

    policy = getattr(get_app_config(), "policy", None)
    if not getattr(policy, "enabled", True):
        return
    ruleset = shared_loader(policy).load(notify=False)
    report = check([getattr(t, "name", "") for t in tools], ruleset, where="MCP tools loaded")
    if not report.unruled and report.checked:
        logger.info("policy: all %d MCP tool(s) resolve to an explicit rule", len(report.checked))


def unruled_by_server(tool_names: dict[str, tuple[str, ...]], app_config) -> dict[str, list[str]] | None:
    """Per MCP server, its loaded tools that no rule names (for GET /api/tool-sources).

    None when the policy is off: nothing is refused then, and saying "no rule"
    would describe a gate that is not there.
    """
    from .registration import shared_loader

    policy = getattr(app_config, "policy", None)
    if not getattr(policy, "enabled", True):
        return None
    ruleset = shared_loader(policy).load(notify=False)
    return {server: [n for n in names if not has_rule(n, ruleset)] for server, names in tool_names.items()}
