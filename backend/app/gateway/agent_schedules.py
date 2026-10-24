"""Per-agent schedules (Feature 006-F): a trigger rule that runs AS a custom agent.

The rule file stays the engine's source of truth. This module only shapes what
Agent Studio writes into it (through the Automations write path,
`routers.automations.edit_rules`) and answers the two questions every write and
every firing asks:

  * does this agent exist? Agents are per user, and the rules file is the
    install owner's, so the agent is looked up in the OWNER's directory, the
    same resolution the gateway uses when it runs the firing
    (services._scheduled_agent_owner);
  * which rules are this agent's? Exactly those whose `agent` names it; the
    lead's are those naming none (agent_runs_view.rule_agent).

Delivery is two rule fields, so politeness applies to an agent's firing exactly
as to any other: `destination` ("auto" sends to Telegram when away, the
existing channel delivery; "quiet" does not) and `show_on_home`.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

LEAD_AGENT = "lead_agent"

#: What a schedule asks the agent when it names no prompt of its own. The
#: agent's instructions say what its work is; the prompt only starts it.
DEFAULT_PROMPT = "It is {scheduled_at}. Do your scheduled run now, following your instructions, and reply with what you found and did."


async def owner_id() -> str:
    """The install owner's id: whose agents a rule may name. With no accounts
    (auth off) the system user, which is then everyone."""
    from app.gateway.ownership import owner_user_id
    from omniharness.runtime.user_context import DEFAULT_USER_ID

    return await owner_user_id() or DEFAULT_USER_ID


async def agent_exists(name: str) -> bool:
    from omniharness.config.agents_config import load_agent_config

    try:
        load_agent_config(name.strip().lower(), user_id=await owner_id())
    except (FileNotFoundError, ValueError):
        return False
    return True


def delivery_destination(telegram: bool) -> str:
    """The Telegram toggle as a rule destination: on is "auto" (the channel
    when the person is away, which with no local voice is always), off is
    "quiet" (no message is sent; the run is still recorded)."""
    return "auto" if telegram else "quiet"


def sends_to_telegram(destination: str) -> bool:
    return destination in ("auto", "remote")


def schedule_rule_id(agent: str, taken: set[str]) -> str:
    """A free rule id for a new schedule: "<agent>-schedule", then -2, -3..."""
    base = f"{re.sub(r'[^a-z0-9-]', '-', agent.lower()).strip('-') or 'agent'}-schedule"
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def schedule_rule(*, rule_id: str, agent: str, schedule: str, timezone: str, telegram: bool, show_on_home: bool, prompt: str | None, name: str | None, enabled: bool = True) -> dict:
    """A cron rule as the rule file holds it. A rule for the lead names no
    agent (config.parse_agent refuses "lead_agent")."""
    rule = {
        "id": rule_id,
        "name": (name or "").strip(),
        "type": "cron",
        "enabled": enabled,
        "match": {"schedule": schedule.strip(), "timezone": timezone.strip()},
        "prompt": (prompt or "").strip() or DEFAULT_PROMPT,
        "destination": delivery_destination(telegram),
        "show_on_home": show_on_home,
    }
    if agent != LEAD_AGENT:
        rule["agent"] = agent
    return rule


def schedule_problem(schedule: str, timezone: str) -> str | None:
    """Why a schedule cannot be saved, in words, or None. The engine's parser
    checks both again on write; this names the field."""
    from croniter import croniter

    if not schedule.strip() or not croniter.is_valid(schedule.strip()):
        return f"{schedule!r} is not a valid cron schedule (minute hour day month weekday, e.g. '0 18 * * 1-5')."
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(timezone.strip())
    except Exception:  # noqa: BLE001 — any failure means "not a zone"
        return f"{timezone!r} is not an IANA time zone (e.g. America/New_York)."
    return None


def disable_agent_rules(doc: dict, agent: str) -> dict:
    """The rule file with every enabled rule naming `agent` switched off. The
    rules are kept (their history and the agent's name stay visible), and
    re-enabling one is refused until the agent exists again."""
    rules = []
    for rule in doc.get("rules") or []:
        named = rule.get("agent")
        if isinstance(named, str) and named.strip().lower() == agent and rule.get("enabled", True):
            rule = {**rule, "enabled": False}
        rules.append(rule)
    return {**doc, "rules": rules}


async def on_agent_deleted(app_config, agent: str, deleted_by: str) -> int:
    """Switch off the rules naming a deleted agent (Feature 006-F). Only the
    owner's agents are named by the owner's rule file, so a deletion by anyone
    else changes nothing. Returns how many rules were switched off. Never
    raises: the engine and the gateway each refuse a firing as a missing agent
    anyway, so a rule file that cannot be written is logged, not fatal."""
    from app.gateway.automations_store import RulesEditError, read_rules
    from app.gateway.routers.automations import edit_rules
    from app.gateway.trigger_engine_wiring import _resolve_rules_path

    if deleted_by != await owner_id():
        return 0
    try:
        before = read_rules(_resolve_rules_path(app_config.trigger_engine)).doc
    except (OSError, ValueError):
        return 0
    count = sum(1 for r in before.get("rules") or [] if isinstance(r.get("agent"), str) and r["agent"].strip().lower() == agent and r.get("enabled", True))
    if not count:
        return 0
    for _ in range(3):  # the file may change between the read and the write
        try:
            edit_rules(app_config, lambda doc: disable_agent_rules(doc, agent), None)
            logger.info("agent %s deleted: switched off %d rule(s) naming it", agent, count)
            return count
        except RulesEditError as exc:
            if exc.status != 409 or "changed since" not in str(exc):
                logger.warning("agent %s deleted, but its rules could not be switched off: %s", agent, exc)
                return 0
    logger.warning("agent %s deleted, but its rules could not be switched off: the rule file kept changing", agent)
    return 0
