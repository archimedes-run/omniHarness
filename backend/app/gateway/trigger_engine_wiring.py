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

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.gateway.watcher_client import WatcherClient
from app.trigger_engine.audit import AuditLog
from app.trigger_engine.config import ConfigLoader
from app.trigger_engine.destinations.base import DestinationRegistry, QuietDestination
from app.trigger_engine.election import SingleRunnerLock, build_lock
from app.trigger_engine.engine import SupervisedEngine
from app.trigger_engine.evaluations import EvaluationLog
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


#: The trigger types this gateway supplies a source for. The engine's loader
#: rejects an enabled rule of any other type, and the automations write path
#: validates against the same set, so an edit is refused for exactly the reasons
#: the engine would refuse it.
SUPPORTED_SOURCE_TYPES = frozenset({TriggerType.WATCHER, TriggerType.CRON})


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


def _still_true(fetch_sessions):
    """FR-013b: is a deferred watcher alert's condition still true at release?

    Asks the watcher again. True only when the same session is still in the
    same state over the same question; a session that was answered, finished,
    or moved on to a different question is not re-announced at 07:30 for
    something resolved at 02:00. (A new question is a new event, with its own
    fingerprint, and fires on its own.)

    When the watcher cannot be reached, or reports itself unobservable, the
    answer is NO: unverifiable is not true, and FR-013c's rule — expire rather
    than deliver blind — applies to "could not look" as much as to "nothing to
    look at". This was `lambda firing: True`.
    """

    def _check(firing) -> bool:
        wanted = firing.event.fields
        try:
            payload = fetch_sessions()
        except Exception as exc:  # noqa: BLE001
            logger.warning("re-check of %s: watcher unreachable, not delivering unverified: %s", firing.event.event_id, exc)
            return False
        if not payload.get("observable", False):
            logger.info("re-check of %s: watcher not observable, not delivering unverified", firing.event.event_id)
            return False
        for session in payload.get("sessions", []):
            if str(session.get("session_id")) == str(firing.event.event_id):
                return session.get("state") == wanted.get("state") and (session.get("summary") or "") == (wanted.get("last_message") or "")
        return False

    return _check


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


def build_loop(config: AppConfig, *, gateway_post, gateway_put, gateway_get, fetch_sessions, exchange_state, remote) -> TriggerLoop:
    """Construct the engine. Raises on misconfiguration — the caller decides
    whether that is fatal (it is not; see lifespan.start)."""
    cfg = config.trigger_engine
    state = Path(cfg.state_dir)

    audit = AuditLog(path=state / "audit.jsonl", actor=cfg.actor)
    scheduler = Scheduler(path=state / "scheduler.json")
    fingerprints = FingerprintStore(path=state / "fingerprints.json")
    evaluations = EvaluationLog(path=state / "evaluations.json")
    pending = PendingStore(path=state / "pending.json")
    injector = TurnInjector(post=gateway_post, put=gateway_put, get=gateway_get)
    threads = RuleThreadMap(
        path=state / "threads.json",
        create_thread=injector.create_thread,
    )
    sources = {
        TriggerType.WATCHER: WatcherSource(fetch_sessions=fetch_sessions),
        TriggerType.CRON: CronSource(scheduler=scheduler),
    }
    # The loader rejects an enabled rule whose type is not a key here, on every
    # reload — not only at startup, since a rule added to a running engine's
    # file would otherwise load and be skipped silently.
    if frozenset(sources) != SUPPORTED_SOURCE_TYPES:
        raise RuntimeError("SUPPORTED_SOURCE_TYPES must name exactly the sources built here")
    loader = ConfigLoader(path=_resolve_rules_path(cfg), supported_types=SUPPORTED_SOURCE_TYPES)
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
        sources=sources,
        fingerprints=fingerprints,
        threads=threads,
        injector=injector,
        releaser=Releaser(
            redact=_redactor(),
            still_true=_still_true(fetch_sessions),
            audit=lambda firing, now: audit.record(firing, now),
        ),
        # `remote` is the IM channel (trigger_destinations.ChannelDestination).
        # It was a QuietDestination — the same object as `quiet` — so every
        # remote and auto delivery went to an in-memory list (audit T-2).
        registry=DestinationRegistry(remote=remote, quiet=QuietDestination()),
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
        # From the rule file. InterruptQueue() used its built-in 5 minutes, so
        # queued_turn_max_wait_seconds was parsed and never reached the queue.
        interrupts=InterruptQueue(max_wait=engine_config.queued_turn_max_wait, schedule_max_wait=engine_config.held_schedule_max_wait),
        thread_state=exchange_state,
        window=CoalesceWindow(window=engine_config.coalesce_window, store=pending),
        run_footer=_run_footer(config),
    )

    return TriggerLoop(
        loader=loader,
        runner=runner,
        engine=SupervisedEngine(evaluate=lambda rule, now: None, rule_timeout=_rule_timeout()),
        scheduler=scheduler,
        fingerprints=fingerprints,
        evaluations=evaluations,
        threads=threads,
        presence=PresenceSignal(),
        now=lambda: datetime.now(UTC),
    )


def _run_footer(config: AppConfig):
    """What a firing did on its own (Feature 006), for the end of its message:
    each granted write with what it came from, and a LINK to its run summary
    on the web page, where "Undo all for this run" is. Nothing in the channel
    acts; the redactor still runs over the whole message before delivery."""
    from app.policy.audit import PolicyAuditLog

    state_dir = getattr(getattr(config, "policy", None), "state_dir", None)

    def footer(firing_id: str) -> str:
        if not state_dir:
            return ""  # no policy layer, so no standing grants
        audit_path = Path(state_dir) / "audit.jsonl"
        try:
            entries = [e for e in PolicyAuditLog(path=audit_path, actor="default").entries() if e.get("kind") == "grant-use" and e.get("firing_id") == firing_id]
        except Exception:  # noqa: BLE001 — a summary that cannot be read is said, not hidden
            logger.warning("trigger engine: could not read what firing %s did on its own", firing_id, exc_info=True)
            return "This run may have changed your projects on its own; I could not read what it did. Check Agent Studio."
        if not entries:
            return ""
        from app.gateway.display_safe import safe_field

        # Every content line is ONE line (safe_field strips line breaks and
        # bidi controls and defangs links) and starts with "- ", inside
        # quotes, so content can neither start a line of its own nor look like
        # the link line. The link is the only live one, built here, last, on
        # its own fixed line.
        lines = ["Done on its own in this run (standing grants):"]
        for entry in entries:
            what = safe_field("; ".join(entry.get("targets") or []) or entry.get("tool", ""))
            source = safe_field(entry.get("source_label") or "")
            lines.append(f"- “{what}”" + (f" ({source})" if source else ""))
        lines.append(f"Review or undo them all: {_web_base_url()}/workspace/runs/{quote(firing_id, safe='')}")
        return "\n".join(lines)

    return footer


def _web_base_url() -> str:
    """The web UI's address: the first allowed CORS origin (the frontend)."""
    from app.gateway.config import get_gateway_config

    origins = get_gateway_config().cors_origins or ["http://localhost:3000"]
    return origins[0].rstrip("/")


#: One gateway call, including a whole agent turn for runs/wait.
GATEWAY_CALL_TIMEOUT_SECONDS = 120.0


def _rule_timeout() -> timedelta:
    """How long one rule's work may take before the engine reports it hung.

    DERIVED, not chosen: create the rule's thread (one gateway call), run the
    agent (one gateway call), deliver (the channel's bound). It was the engine's
    30 s default, which never fired while rule work blocked the event loop —
    wait_for cannot interrupt a blocking call — and fired on every ordinary
    agent run once the work moved to a thread. Three of those mute a rule
    (engine.BACKOFF_AFTER). Found in the live end-to-end check.
    """
    from app.gateway.trigger_destinations import DELIVERY_TIMEOUT_SECONDS

    return timedelta(seconds=2 * GATEWAY_CALL_TIMEOUT_SECONDS + DELIVERY_TIMEOUT_SECONDS)


def _gateway_base_url() -> str:
    """This process's own gateway. Read from the same variable the gateway binds
    with (app/gateway/config.py), rather than a hard-coded 8001 that silently
    pointed elsewhere whenever GATEWAY_PORT was set."""
    return f"http://127.0.0.1:{os.getenv('GATEWAY_PORT', '8001')}"


def _gateway_call(method: str):
    def _call(path: str, body: dict | None = None) -> dict:
        import json

        import httpx

        from app.gateway.csrf_middleware import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token
        from app.gateway.internal_auth import TRIGGER_GRANT_HEADER_NAME, create_internal_auth_headers, issue_trigger_grant

        url = f"{_gateway_base_url()}{path}"
        # The gateway's CSRF middleware checks every POST/PUT, internal calls
        # included, and answered the engine's 403 'CSRF token missing' — so no
        # rule could ever create its thread. Found in the live end-to-end check.
        # Same double-submit pair the channel manager sends (channels/manager.py).
        csrf = generate_csrf_token()
        headers = {**create_internal_auth_headers(), CSRF_HEADER_NAME: csrf, "Cookie": f"{CSRF_COOKIE_NAME}={csrf}"}
        content = json.dumps(body).encode() if body is not None else b""
        if body is not None:
            headers["Content-Type"] = "application/json"
        if path.endswith("/runs/wait"):
            # A scheduled run: a single-use grant bound to these exact bytes
            # (internal_auth.issue_trigger_grant). Nothing else may mark one.
            headers[TRIGGER_GRANT_HEADER_NAME] = issue_trigger_grant(method, path, content)
        with httpx.Client(timeout=GATEWAY_CALL_TIMEOUT_SECONDS) as client:
            resp = client.request(method, url, content=content or None, headers=headers)
            if resp.is_error:
                raise GatewayCallFailed(method, path, resp)
            return resp.json() if resp.content else {}

    return _call


class GatewayCallFailed(RuntimeError):
    """A gateway call answered non-2xx, with the gateway's own explanation.

    For a run, that is the run's status and error (services.wait_result) — the
    reason a user reads in the audit, rather than httpx's 'Server error 500 for
    url ...', which names the transport and not what went wrong.
    """

    def __init__(self, method: str, path: str, resp) -> None:
        try:
            detail = resp.json().get("detail", resp.text)
        except ValueError:
            detail = resp.text
        if isinstance(detail, dict) and "status" in detail:
            explained = f"the agent run ended '{detail['status']}': {detail.get('error') or 'no error recorded'}"
        else:
            explained = f"{method} {path} answered {resp.status_code}: {detail}"
        super().__init__(explained)


#: Run statuses that mean an exchange is under way. From RunStatus; the engine
#: holds a proactive message while any of these is open.
_ACTIVE_RUN_STATUSES = frozenset({"pending", "running"})


def _destination_conversations(config: AppConfig) -> list[str]:
    """Threads behind the chat a remote delivery lands in.

    The exchange a proactive message would interrupt is in THAT conversation —
    the user's Telegram chat — not in the rule's own thread, where the user
    never types. Every topic of the chat counts. No channel service, or no
    recipient configured, means there is no such conversation to protect.
    """
    from app.channels.service import get_channel_service

    remote = getattr(config.trigger_engine, "remote", None)
    service = get_channel_service()
    if remote is None or service is None:
        return []
    return [e["thread_id"] for e in service.store.list_entries(remote.channel) if str(e.get("chat_id")) == str(remote.chat_id) and e.get("thread_id")]


def _exchange_state(config: AppConfig, run_store, main_loop: asyncio.AbstractEventLoop):
    """Whether an exchange is in progress where this firing would land (FR-016).

    Read from the RUN STORE, not `GET /api/threads/{id}/runs`: that route reads
    one worker's in-memory RunManager, so under `--workers 4` a run on another
    worker is invisible — every politeness check per-process, Article XI's
    first row. The SQL run store is shared by every worker.

    It replaces a call that could never work: the engine passed `gateway_get`
    a bare thread id (URL `http://127.0.0.1:8001<uuid>`), and read a `status`
    field the thread-state response does not have.

    Runs on the engine's worker thread; the store's sessions belong to the
    gateway's loop, so the query is sent there and awaited from here.
    """

    def _state(thread_id: str) -> dict:
        threads = dict.fromkeys(t for t in [thread_id, *_destination_conversations(config)] if t)
        active = []
        for tid in threads:
            # user_id=None, EXPLICITLY: every user's runs on this thread. The
            # SQL store's default reads the caller's user context, and the
            # engine has none, so it refused every query and each alert was
            # held for the full five-minute bound (found in the live E2E).
            rows = asyncio.run_coroutine_threadsafe(run_store.list_by_thread(tid, user_id=None), main_loop).result(timeout=10)
            active += [r["run_id"] for r in rows if r.get("status") in _ACTIVE_RUN_STATUSES]
        return {"status": "busy" if active else "idle", "active_runs": active}

    return _state


def _remote_destination(config: AppConfig, main_loop: asyncio.AbstractEventLoop):
    """The configured chat, or a destination that fails naming the missing setting."""
    from app.gateway.trigger_destinations import ChannelDestination, UnconfiguredRemote

    remote = getattr(config.trigger_engine, "remote", None)
    if remote is None:
        logger.warning("trigger engine: no trigger_engine.remote recipient configured; remote deliveries will fail and say so")
        return UnconfiguredRemote()
    return ChannelDestination(channel=remote.channel, chat_id=str(remote.chat_id), main_loop=main_loop)


def build_production_loop(config: AppConfig, *, run_store) -> TriggerLoop:
    """The engine exactly as the gateway starts it.

    The ONLY place production's arguments to `build_loop` are chosen. The
    gateway lifespan calls this, and so does the Article XI integration test —
    so a stub passed here is a stub the test sees. Before this function existed
    the arguments were closures inside `app.py`, every engine test built its own
    loop by hand, and four stub arguments shipped with a green suite
    (specs/AUDIT-2026-10.md, §1.1).
    """
    return build_loop(
        config,
        gateway_post=_gateway_call("POST"),
        gateway_put=_gateway_call("PUT"),
        gateway_get=_gateway_call("GET"),
        # Feature 001's watcher over MCP, at the URL in extensions_config. Was a
        # stub returning observable=False, so no watcher rule ever fired.
        fetch_sessions=WatcherClient().list_sessions_blocking,
        exchange_state=_exchange_state(config, run_store, asyncio.get_running_loop()),
        remote=_remote_destination(config, asyncio.get_running_loop()),
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
