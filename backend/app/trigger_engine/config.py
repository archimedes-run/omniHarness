"""Rule-file loading, validation and hot reload (FR-001, FR-005, FR-006).

Two properties matter more than the parsing:

  * An invalid config leaves the PREVIOUS one in effect. A config that fails
    open is worse than one that fails to load, because nobody notices.
  * Template fields are validated at LOAD, not at render. A prompt referencing
    a field its trigger type cannot supply is a typo, and a typo should not
    surface as a half-rendered message at 3am.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from string import Formatter

from .models import Destination, Rule, TriggerType

logger = logging.getLogger(__name__)

#: Fields each trigger type can supply to a prompt template. Used at load time
#: so an unavailable field is a config error rather than a render surprise.
AVAILABLE_FIELDS: dict[TriggerType, frozenset[str]] = {
    TriggerType.WATCHER: frozenset({"project", "session_id", "last_message", "state", "idle_reason"}),
    TriggerType.CRON: frozenset({"scheduled_at"}),
    TriggerType.COMPLETION: frozenset({"task_id", "status", "summary"}),
    #: Feature 003. What a calendar event can supply to a prompt template.
    #: `attendees` and `summary` are what FR-026's "who it is with and what it
    #: is about" needs; `minutes_before` lets the wording say how soon.
    TriggerType.CALENDAR: frozenset({"summary", "attendees", "description", "starts_at", "minutes_before"}),
}

DEFAULTS = {
    "coalesce_window_seconds": 60,
    "presence_threshold_seconds": 300,
    "queued_turn_max_wait_seconds": 300,
    #: FR-016d: how long a scheduled message waits behind an exchange.
    "held_schedule_max_wait_seconds": 7200,
    "fingerprint_retention_seconds": 86400,
}


#: A rule's display name, as long as a list row can show.
NAME_MAX = 80

#: Feature 006-F. What an agent name may be once normalised: the gateway's own
#: rule (services._normalise_agent_name), so a name the engine accepts is one
#: the gateway resolves to the same agent.
AGENT_NAME = re.compile(r"[a-z0-9-]+")
#: The lead agent. A rule for it names no agent; naming it (any case) is the
#: same thing, so a file written before Feature 006-F (whose docs said to write
#: `agent:`) keeps running as it did.
LEAD_AGENT = "lead_agent"


def parse_agent(rid: str, raw) -> str | None:
    """A rule's `agent`, normalised, or None for the lead. Raises RuleRefused:
    a bad name refuses that one rule, never the file (main ignored the key)."""
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise RuleRefused(f"rule {rid!r}: agent must be a custom agent's name; leave it out to run as the lead agent")
    name = raw.strip().lower()
    if name == LEAD_AGENT:
        return None
    if not AGENT_NAME.fullmatch(name):
        raise RuleRefused(f"rule {rid!r}: agent {raw!r} is not an agent name (letters, digits and hyphens)")
    return name


def standard_cron_problem(schedule) -> str | None:
    """Why `schedule` is not a standard five-field cron, in words, or None.

    For WRITES only (Studio schedules, Automations): croniter also accepts a
    sixth (seconds) field, so `* * * * * *` would fire every second. The
    loader keeps accepting what croniter does, so no rule file that loads
    today stops loading."""
    from croniter import croniter

    text = str(schedule or "").strip()
    if len(text.split()) != 5 or not croniter.is_valid(text):
        return f"{schedule!r} is not a valid cron schedule: five fields, minute hour day month weekday (e.g. '0 18 * * 1-5')."
    return None


class ConfigError(ValueError):
    """The configuration is invalid. The previous one stays in effect."""


class RuleRefused(ConfigError):
    """One rule is invalid in a way that refuses only it (Feature 006-F's
    `agent` and `show_on_home`, keys a file written before them may carry
    with any value): every other rule loads, and this one is reported in
    EngineConfig.refused. A write that introduces one is still refused."""


@dataclass(frozen=True)
class RefusedRule:
    id: str
    error: str


@dataclass(frozen=True)
class QuietHours:
    start: str = "22:00"
    end: str = "07:30"
    timezone: str = "UTC"
    #: Quiet hours must be switchable off from the rules file. Without this the
    #: only way to disable them was to edit code, and every value the user set
    #: was enforced whether they wanted the mechanism or not.
    enabled: bool = True


@dataclass(frozen=True)
class EngineConfig:
    rules: tuple[Rule, ...] = ()
    quiet_hours: QuietHours = field(default_factory=QuietHours)
    coalesce_window: timedelta = timedelta(seconds=DEFAULTS["coalesce_window_seconds"])
    presence_threshold: timedelta = timedelta(seconds=DEFAULTS["presence_threshold_seconds"])
    queued_turn_max_wait: timedelta = timedelta(seconds=DEFAULTS["queued_turn_max_wait_seconds"])
    held_schedule_max_wait: timedelta = timedelta(seconds=DEFAULTS["held_schedule_max_wait_seconds"])
    fingerprint_retention: timedelta = timedelta(seconds=DEFAULTS["fingerprint_retention_seconds"])
    #: Rules not loaded, each with why (RuleRefused); the others run.
    refused: tuple[RefusedRule, ...] = ()


def _template_fields(rid: str, prompt: str) -> set[str]:
    try:
        return {f for _, f, _, _ in Formatter().parse(prompt) if f}
    except ValueError as exc:
        # A lone "{" or "}": refused at load and on write (422), never a
        # parse error that surfaces as a 500 or fails every firing.
        raise ConfigError(f"rule {rid!r}: the prompt has an unmatched brace ({exc}). Use {{{{ and }}}} for a literal {{ or }}.") from exc


def _parse_rule(raw: dict, seen: set[str]) -> Rule:
    rid = raw.get("id")
    if not isinstance(rid, str) or not rid.strip():
        raise ConfigError("every rule needs a non-empty id")
    if rid in seen:
        # The id is the thread-map key, so a duplicate would silently merge two
        # rules' conversation histories.
        raise ConfigError(f"duplicate rule id {rid!r}; ids are the thread-map key")
    seen.add(rid)

    try:
        rtype = TriggerType(raw.get("type"))
    except ValueError as exc:
        raise ConfigError(f"rule {rid!r}: unknown type {raw.get('type')!r}") from exc
    if rtype is TriggerType.CALENDAR and "minutes_before" not in (raw.get("match") or {}):
        # Implemented in Feature 003 as a new source (sources/calendar.py). The
        # rejection that used to sit here is gone, replaced by the one thing a
        # calendar rule cannot do without: how far ahead to fire.
        raise ConfigError(f"rule {rid!r}: a calendar rule needs match.minutes_before")

    prompt = raw.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ConfigError(f"rule {rid!r}: prompt is required")
    unknown = _template_fields(rid, prompt) - AVAILABLE_FIELDS[rtype]
    if unknown:
        raise ConfigError(f"rule {rid!r}: prompt references {sorted(unknown)}, which a {rtype} event cannot supply. Available: {sorted(AVAILABLE_FIELDS[rtype])}")

    match = raw.get("match")
    if not isinstance(match, dict):
        raise ConfigError(f"rule {rid!r}: match must be an object")
    if rtype is TriggerType.CRON and not match.get("schedule"):
        raise ConfigError(f"rule {rid!r}: a cron rule needs match.schedule")
    if rtype is TriggerType.CRON:
        # Checked at load, so an edit that breaks it is refused while the
        # previous rules stay in force, instead of failing on every evaluation.
        from croniter import croniter

        if not croniter.is_valid(str(match["schedule"])):
            raise ConfigError(f"rule {rid!r}: match.schedule {match['schedule']!r} is not a valid cron expression (minute hour day month weekday, e.g. '45 8 * * 1-5')")
    if rtype is TriggerType.CRON and match.get("timezone"):
        # Rejected at load, like any other invalid rule: an unknown zone would
        # otherwise raise on every evaluation, or worse, be read as UTC.
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(match["timezone"])
        except Exception as exc:  # noqa: BLE001 — any failure means "not a zone"
            raise ConfigError(f"rule {rid!r}: match.timezone {match['timezone']!r} is not an IANA time zone (e.g. America/New_York)") from exc
    if rtype is TriggerType.WATCHER and not match.get("event"):
        raise ConfigError(f"rule {rid!r}: a watcher rule needs match.event")

    name = raw.get("name", "")
    if not isinstance(name, str) or len(name) > NAME_MAX:
        raise ConfigError(f"rule {rid!r}: name must be text of at most {NAME_MAX} characters")

    try:
        dest = Destination(raw.get("destination", "auto"))
    except ValueError as exc:
        raise ConfigError(f"rule {rid!r}: unknown destination {raw.get('destination')!r}") from exc

    # Last, after every check that refuses the whole file: these refuse only
    # this rule (RuleRefused).
    agent = parse_agent(rid, raw.get("agent"))
    show_on_home = _flag(rid, raw, "show_on_home", default=True)
    return Rule(
        id=rid,
        type=rtype,
        match=match,
        prompt=prompt,
        destination=dest,
        urgent=bool(raw.get("urgent", False)),
        enabled=bool(raw.get("enabled", True)),
        name=name.strip(),
        agent=agent,
        show_on_home=show_on_home,
    )


def _flag(rid: str, raw: dict, key: str, *, default: bool) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise RuleRefused(f"rule {rid!r}: {key} must be true or false")
    return value


def parse(doc: dict) -> EngineConfig:
    raw_rules = doc.get("rules")
    if not isinstance(raw_rules, list):
        raise ConfigError("`rules` must be a list")
    seen: set[str] = set()
    parsed: list[Rule] = []
    refused: list[RefusedRule] = []
    for raw in raw_rules:
        try:
            parsed.append(_parse_rule(raw, seen))
        except RuleRefused as exc:
            refused.append(RefusedRule(id=str(raw.get("id")), error=str(exc)))
    rules = tuple(parsed)

    qh_raw = doc.get("quiet_hours") or {}
    qh = QuietHours(
        start=qh_raw.get("start", "22:00"),
        end=qh_raw.get("end", "07:30"),
        timezone=qh_raw.get("timezone", "UTC"),
        enabled=bool(qh_raw.get("enabled", True)),
    )
    d = doc.get("defaults") or {}

    def secs(key: str) -> timedelta:
        # `d.get(key)` alone decides presence. `int(v) or DEFAULT` read an
        # explicit 0 as unset, so "coalesce_window_seconds: 0" became 60.
        value = d.get(key)
        return timedelta(seconds=int(DEFAULTS.get(key, 0) if value is None else value))

    return EngineConfig(
        rules=rules,
        quiet_hours=qh,
        coalesce_window=secs("coalesce_window_seconds"),
        presence_threshold=secs("presence_threshold_seconds"),
        queued_turn_max_wait=secs("queued_turn_max_wait_seconds"),
        held_schedule_max_wait=secs("held_schedule_max_wait_seconds"),
        fingerprint_retention=timedelta(seconds=DEFAULTS["fingerprint_retention_seconds"]),
        refused=tuple(refused),
    )


#: What each trigger type needs connected before a rule of that type can fire.
#: Named in the error, so the operator learns what is missing, not merely that
#: something is.
FEED_FOR: dict[TriggerType, str] = {
    TriggerType.WATCHER: "session-watcher feed",
    TriggerType.CRON: "scheduler",
    TriggerType.CALENDAR: "calendar feed",
    TriggerType.COMPLETION: "completion feed",
}


def check_sources(cfg: EngineConfig, supported: frozenset[TriggerType]) -> None:
    """Reject an ENABLED rule whose type has no source in this engine.

    Before this, such a rule loaded, was evaluated every cycle, and was skipped
    with a debug log (runner.py) — "silently never fires", the worst of the
    three options, and what happened to every calendar and completion rule.
    A disabled rule is left alone: it does nothing either way, and a draft
    kept for when its feed exists is a reasonable thing to keep.
    """
    for rule in cfg.rules:
        if rule.enabled and rule.type not in supported:
            feed = FEED_FOR.get(rule.type, f"{rule.type} source")
            raise ConfigError(f"rule {rule.id!r}: a {rule.type} rule needs a {feed}, and no {feed} is connected to the trigger engine, so it would load and never fire. Disable or remove the rule until one is.")


@dataclass
class ConfigLoader:
    """Loads and hot-reloads the rule file, holding the last VALID config."""

    path: Path
    #: Trigger types this engine has a source for. Production always passes it
    #: (trigger_engine_wiring); None skips the check, for tests of parsing alone.
    supported_types: frozenset[TriggerType] | None = None
    _config: EngineConfig | None = None
    _mtime: float | None = None
    last_error: str | None = None

    @property
    def config(self) -> EngineConfig:
        return self._config or EngineConfig()

    def load(self) -> EngineConfig:
        """Reload if the file changed. On error, keep the previous config.

        Returns whatever config is now in effect — which on failure is the one
        that was already there. The caller does not have to remember to check.
        """
        try:
            mtime = self.path.stat().st_mtime
        except OSError as exc:
            self.last_error = f"cannot stat rule file: {exc}"
            logger.error("rule file unreadable, keeping previous config: %s", exc)
            return self.config
        if self._config is not None and mtime == self._mtime:
            return self._config
        try:
            doc = json.loads(self.path.read_text())
            cfg = parse(doc)
            if self.supported_types is not None:
                check_sources(cfg, self.supported_types)
        except (json.JSONDecodeError, ConfigError, OSError) as exc:
            self.last_error = str(exc)
            logger.error(
                "invalid rule file, KEEPING PREVIOUS config (%d rules active): %s",
                len(self.config.rules),
                exc,
            )
            return self.config
        self._config, self._mtime, self.last_error = cfg, mtime, None
        logger.info("rule config loaded: %d rule(s)", len(cfg.rules))
        for refused in cfg.refused:
            logger.error("rule %s NOT loaded (the other rules run): %s", refused.id, refused.error)
        from .scheduler import DEFAULT_TIMEZONE

        for rule in cfg.rules:
            if rule.type is TriggerType.CRON and not rule.match.get("timezone"):
                # The migration note, where an operator reads it: this rule's
                # schedule moved zones in Feature 006 (scheduler.DEFAULT_TIMEZONE).
                logger.info('rule %s names no timezone: it runs in %s (before Feature 006 it ran in UTC; add "timezone": "UTC" to keep that)', rule.id, DEFAULT_TIMEZONE)
        return cfg
