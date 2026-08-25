"""Composition root for the Feature 002 trigger engine.

This lives on the GATEWAY side, not inside app/trigger_engine/, and that
placement is load-bearing rather than incidental. Gate 1 bans the engine from
importing agent core (Article I), and assembling the engine requires reading
`AppConfig` — so the module that knows about both cannot be inside the engine.
It was written in the engine package first and the gate rejected it, which is
the gate doing its job: a composition root knows both sides, so it belongs to
neither, and by convention sits with the caller.

Everything here is construction. No policy lives in this file, so that what the
engine does stays readable in the modules that do it.

The engine is started by exactly one worker. See trigger_engine/election.py for
why, and for what is lost when the holder dies mid-window.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.trigger_engine.audit import AuditLog
from app.trigger_engine.config import ConfigLoader
from app.trigger_engine.destinations.base import DestinationRegistry, QuietDestination
from app.trigger_engine.election import SingleRunnerLock, build_lock
from app.trigger_engine.engine import SupervisedEngine
from app.trigger_engine.fingerprint import FingerprintStore
from app.trigger_engine.injector import TurnInjector
from app.trigger_engine.loop import TriggerLoop
from app.trigger_engine.models import TriggerType
from app.trigger_engine.persistence import PendingStore
from app.trigger_engine.politeness.coalesce import CoalesceWindow
from app.trigger_engine.politeness.interrupt import InterruptQueue
from app.trigger_engine.politeness.quiet_hours import DeferralQueue
from app.trigger_engine.politeness.quiet_hours import QuietHours as EnforcedQuietHours
from app.trigger_engine.politeness.release import Releaser
from app.trigger_engine.presence import PresenceSignal
from app.trigger_engine.runner import RuleRunner
from app.trigger_engine.scheduler import Scheduler
from app.trigger_engine.sources.cron import CronSource
from app.trigger_engine.sources.watcher import WatcherSource
from app.trigger_engine.threads import RuleThreadMap
from omniharness.config.app_config import AppConfig

logger = logging.getLogger(__name__)


#: Rules that ship with the engine. Resolved here, on the composition side, for
#: the same reason the policy layer's are: the module that owns the default and
#: the module that reads configuration are not the same layer.
DEFAULT_RULES = Path(__file__).resolve().parents[1] / "trigger_engine" / "default_rules.json"


def _resolve_rules_path(cfg) -> Path:
    """The rule file to load.

    Falls back to the shipped defaults ONLY when nothing is configured. A
    configured path that cannot be read is NOT replaced by them — that would run
    a different rule set than the operator wrote, which is a second guarantee
    lost while fixing the first.
    """
    configured = getattr(cfg, "rules_path", "") or ""
    return Path(configured) if configured else DEFAULT_RULES


def _redactor():
    """Feature 001's redactor, consumed as an injected callable.

    Imported here rather than in release.py so the politeness code keeps no
    opinion about where redaction comes from, and so the dependency direction
    stays visible at the wiring seam. `session-watcher` is a declared workspace
    member of the backend; the import ban runs the other way (that package must
    not import core).
    """
    from session_watcher.redaction import Channel, redact_or_suppress

    def _redact(text: str) -> tuple[str, bool]:
        # Channel.REMOTE: worker output crossing to a remote destination gets
        # the widest pattern set. redact_or_suppress fails closed — it returns
        # (text, False) rather than raising, and Releaser suppresses delivery.
        return redact_or_suppress(text, channel=Channel.REMOTE)

    return _redact


def _quiet_hours(engine_config) -> EnforcedQuietHours:
    """Adapt the CONFIG QuietHours to the ENFORCING QuietHours.

    Two different classes share the name. `config.QuietHours` is frozen data
    parsed from the rules file (start / end / timezone) with no behaviour;
    `politeness.QuietHours` carries `enabled` and the `contains()` that decides
    whether a firing is suppressed. Nothing converted between them, so what the
    user wrote in `quiet_hours:` never reached the mechanism enforcing it —
    every test passed because each constructed the enforcing type directly.

    Both types now carry the full set — `enabled` was added to the config type
    so quiet hours can be switched off from the rules file, and `timezone` to
    the enforcing type, which previously parsed a zone and then compared naive
    local times. This adapter therefore copies rather than guessing.
    """
    return EnforcedQuietHours(
        start=engine_config.quiet_hours.start,
        end=engine_config.quiet_hours.end,
        enabled=engine_config.quiet_hours.enabled,
        timezone=engine_config.quiet_hours.timezone,
    )


def build_loop(config: AppConfig, *, gateway_post, gateway_put, gateway_get, fetch_sessions) -> TriggerLoop:
    """Construct the engine. Raises on misconfiguration — the caller decides
    whether that is fatal (it is not; see lifespan.start)."""
    cfg = config.trigger_engine
    state = Path(cfg.state_dir)

    audit = AuditLog(path=state / "audit.jsonl", actor=cfg.actor)
    scheduler = Scheduler(path=state / "scheduler.json")
    fingerprints = FingerprintStore(path=state / "fingerprints.json")
    pending = PendingStore(path=state / "pending.json")
    injector = TurnInjector(post=gateway_post, put=gateway_put, get=gateway_get)
    threads = RuleThreadMap(
        path=state / "threads.json",
        create_thread=injector.create_thread,
    )
    destination = QuietDestination()
    loader = ConfigLoader(path=_resolve_rules_path(cfg))
    engine_config = loader.load()

    # Article XIV. A missing rule file used to produce an empty config, a logged
    # error, and a handle reporting `running: True` — so every proactive-message
    # requirement was silently inert while the operator surface said healthy.
    # Absence must fail loudly. lifespan.start() catches this and records it in
    # `handle.error`, so the gateway still starts; what changes is that the
    # engine does not pretend to be working.
    if not engine_config.rules and loader.last_error:
        raise RuntimeError(f"trigger engine: no rules are in effect ({loader.last_error}). Expected a rule file at {_resolve_rules_path(cfg)}. The engine will not start rather than run with nothing to evaluate and report itself healthy.")

    runner = RuleRunner(
        sources={
            TriggerType.WATCHER: WatcherSource(fetch_sessions=fetch_sessions),
            TriggerType.CRON: CronSource(scheduler=scheduler),
        },
        fingerprints=fingerprints,
        threads=threads,
        injector=injector,
        releaser=Releaser(
            redact=_redactor(),
            still_true=lambda firing: True,
            audit=lambda firing, now: audit.record(firing, now),
        ),
        registry=DestinationRegistry(remote=destination, quiet=destination),
        presence=PresenceSignal(),
        audit=audit,
        config=engine_config,
        # Take quiet hours and the coalescing window from the loaded rule
        # config, not from defaults constructed here. Hardcoding
        # QuietHours(enabled=False) would disable FR-013 entirely while every
        # unit test for it kept passing, because those construct their own.
        # See _quiet_hours for why an adapter is needed at all.
        quiet=_quiet_hours(engine_config),
        deferrals=DeferralQueue(store=pending),
        interrupts=InterruptQueue(),
        thread_state=gateway_get,
        window=CoalesceWindow(window=engine_config.coalesce_window, store=pending),
    )

    return TriggerLoop(
        loader=loader,
        runner=runner,
        engine=SupervisedEngine(evaluate=lambda rule, now: None),
        scheduler=scheduler,
        fingerprints=fingerprints,
        threads=threads,
        presence=PresenceSignal(),
        now=lambda: datetime.now(UTC),
    )


def elect(config: AppConfig) -> SingleRunnerLock | None:
    """Contend for leadership. Returns the held lock, or None on losing.

    Losing is the expected outcome for most workers and is not an error: three
    of four are meant to lose.
    """
    lock = build_lock(
        backend=config.database.backend,
        postgres_url=config.database.postgres_url,
        lock_dir=Path(config.trigger_engine.state_dir),
    )
    if lock.acquire():
        logger.info("trigger engine: won single-runner election (%s)", type(lock).__name__)
        return lock
    logger.info("trigger engine: another worker holds the runner lock; not starting one here")
    return None


def describe(config: AppConfig, lock: Any | None) -> dict:
    """Operator-readable state. Distinguishes the three cases that otherwise
    look alike from outside: disabled, running here, running elsewhere."""
    if not config.trigger_engine.enabled:
        return {"enabled": False, "role": "disabled"}
    return {"enabled": True, "role": "runner" if lock is not None else "standby"}
