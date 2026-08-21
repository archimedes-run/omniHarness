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
}

DEFAULTS = {
    "coalesce_window_seconds": 60,
    "presence_threshold_seconds": 300,
    "queued_turn_max_wait_seconds": 300,
    "fingerprint_retention_seconds": 86400,
}


class ConfigError(ValueError):
    """The configuration is invalid. The previous one stays in effect."""


@dataclass(frozen=True)
class QuietHours:
    start: str = "22:00"
    end: str = "07:30"
    timezone: str = "UTC"


@dataclass(frozen=True)
class EngineConfig:
    rules: tuple[Rule, ...] = ()
    quiet_hours: QuietHours = field(default_factory=QuietHours)
    coalesce_window: timedelta = timedelta(seconds=DEFAULTS["coalesce_window_seconds"])
    presence_threshold: timedelta = timedelta(seconds=DEFAULTS["presence_threshold_seconds"])
    queued_turn_max_wait: timedelta = timedelta(seconds=DEFAULTS["queued_turn_max_wait_seconds"])
    fingerprint_retention: timedelta = timedelta(seconds=DEFAULTS["fingerprint_retention_seconds"])


def _template_fields(prompt: str) -> set[str]:
    return {f for _, f, _, _ in Formatter().parse(prompt) if f}


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
    if rtype is TriggerType.CALENDAR:
        raise ConfigError(f"rule {rid!r}: calendar triggers are not implemented in this feature. The type is reserved in the schema so adding it later is a new source.")

    prompt = raw.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ConfigError(f"rule {rid!r}: prompt is required")
    unknown = _template_fields(prompt) - AVAILABLE_FIELDS[rtype]
    if unknown:
        raise ConfigError(f"rule {rid!r}: prompt references {sorted(unknown)}, which a {rtype} event cannot supply. Available: {sorted(AVAILABLE_FIELDS[rtype])}")

    match = raw.get("match")
    if not isinstance(match, dict):
        raise ConfigError(f"rule {rid!r}: match must be an object")
    if rtype is TriggerType.CRON and not match.get("schedule"):
        raise ConfigError(f"rule {rid!r}: a cron rule needs match.schedule")
    if rtype is TriggerType.WATCHER and not match.get("event"):
        raise ConfigError(f"rule {rid!r}: a watcher rule needs match.event")

    try:
        dest = Destination(raw.get("destination", "auto"))
    except ValueError as exc:
        raise ConfigError(f"rule {rid!r}: unknown destination {raw.get('destination')!r}") from exc

    return Rule(
        id=rid,
        type=rtype,
        match=match,
        prompt=prompt,
        destination=dest,
        urgent=bool(raw.get("urgent", False)),
        enabled=bool(raw.get("enabled", True)),
    )


def parse(doc: dict) -> EngineConfig:
    raw_rules = doc.get("rules")
    if not isinstance(raw_rules, list):
        raise ConfigError("`rules` must be a list")
    seen: set[str] = set()
    rules = tuple(_parse_rule(r, seen) for r in raw_rules)

    qh_raw = doc.get("quiet_hours") or {}
    qh = QuietHours(
        start=qh_raw.get("start", "22:00"),
        end=qh_raw.get("end", "07:30"),
        timezone=qh_raw.get("timezone", "UTC"),
    )
    d = doc.get("defaults") or {}

    def secs(key: str) -> timedelta:
        return timedelta(seconds=int(d.get(key, DEFAULTS.get(key, 0)) or DEFAULTS.get(key, 0)))

    return EngineConfig(
        rules=rules,
        quiet_hours=qh,
        coalesce_window=secs("coalesce_window_seconds"),
        presence_threshold=secs("presence_threshold_seconds"),
        queued_turn_max_wait=secs("queued_turn_max_wait_seconds"),
        fingerprint_retention=timedelta(seconds=DEFAULTS["fingerprint_retention_seconds"]),
    )


@dataclass
class ConfigLoader:
    """Loads and hot-reloads the rule file, holding the last VALID config."""

    path: Path
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
        return cfg
