"""Trigger engine status — why the engine is or is not doing anything.

Before this, a trigger engine that refused to start recorded why in
`handle.error` and nowhere a person could read it; the gateway then dropped the
handle. A calendar rule rejected for having no calendar feed, a rule file that
failed to reload, an unreachable watcher: each was a log line.

Read-only. It describes THIS worker's view, and says so: under several uvicorn
workers one runs the engine and the rest are standby, and a standby worker
reports that rather than guessing at another process's state. Feature 004's
triggers surface (T051) extends this router with rules and firings.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.ownership import require_owner_account

# Install-wide records: the owner account only (security baseline).
from app.gateway.triggers_view import FiringsView, RulesView, RunsView, describe_firings, describe_rules, describe_runs

router = APIRouter(prefix="/api/triggers", tags=["triggers"], dependencies=[Depends(require_owner_account)])


class EngineStatus(BaseModel):
    #: disabled | runner | standby | failed
    role: str
    running: bool = False
    #: Why the engine did not start — e.g. a rule whose feed is not connected.
    error: str | None = None
    #: Why the most recent rule-file reload was rejected; the previous rules
    #: stay in force meanwhile.
    rules_error: str | None = None
    rules: list[dict[str, Any]] = Field(default_factory=list)
    #: Per trigger type, whether its source could be read on the last attempt.
    sources: dict[str, dict[str, Any]] = Field(default_factory=dict)


def describe_engine(app_state: Any) -> EngineStatus:
    """The status, from what the lifespan left on app.state. Pure read."""
    config = getattr(app_state, "config", None)
    if config is None or not config.trigger_engine.enabled:
        return EngineStatus(role="disabled")
    handle = getattr(app_state, "trigger_engine", None)
    if handle is None:
        return EngineStatus(role="standby", error=None)
    if handle.error:
        return EngineStatus(role="failed", error=handle.error)
    loop = handle.loop
    return EngineStatus(
        role="runner",
        running=handle.running,
        rules_error=loop.loader.last_error,
        rules=[{"id": r.id, "type": str(r.type), "enabled": r.enabled} for r in loop.loader.config.rules],
        sources={str(kind): source.describe() for kind, source in loop.runner.sources.items() if hasattr(source, "describe")},
    )


def _engine_state(app_state):
    """The rule file, evaluation log and audit log, read from disk — the same
    files the engine writes, so any worker can answer."""
    from pathlib import Path

    from app.gateway.trigger_engine_wiring import _resolve_rules_path
    from app.trigger_engine.audit import AuditLog
    from app.trigger_engine.config import ConfigLoader
    from app.trigger_engine.evaluations import EvaluationLog

    cfg = app_state.config.trigger_engine
    state = Path(cfg.state_dir)
    rules_path = _resolve_rules_path(cfg)
    loader = ConfigLoader(path=rules_path)
    config = loader.load()
    rules = config.rules
    log = EvaluationLog(path=state / "evaluations.json")
    evaluated = {r.id: (log.last_evaluated_at(r.id).isoformat() if log.last_evaluated_at(r.id) else None) for r in rules}
    audit = AuditLog(path=state / "audit.jsonl", actor=cfg.actor).entries()
    # Quiet hours as the file says them; None when no version of it was ever
    # read (an unreadable file must not show the built-in defaults as yours).
    quiet = config.quiet_hours if config.rules or loader.last_error is None else None
    return rules, evaluated, audit, loader.last_error, rules_path, bool(getattr(cfg, "rules_path", "")), quiet


@router.get("/rules", response_model=RulesView)
@require_permission("threads", "read")
async def trigger_rules(request: Request) -> RulesView:
    """T051. Every loaded rule, and whether it is evaluating, firing, or neither."""
    from app.gateway.automations_store import version_of

    rules, evaluated, audit, error, path, configured, quiet = _engine_state(request.app.state)
    try:
        version = version_of(path.read_bytes())
    except OSError:
        version = None
    reason = None if configured else "No rules file is configured; the engine is running the shipped defaults. Set trigger_engine.rules_path in config.yaml to edit rules here."
    return describe_rules(
        rules=list(rules),
        evaluated=evaluated,
        audit=audit,
        engine_enabled=request.app.state.config.trigger_engine.enabled,
        rules_error=error,
        version=version,
        writable=configured and version is not None,
        not_writable_reason=reason,
        quiet_hours=quiet,
    )


@router.get("/firings", response_model=FiringsView)
@require_permission("threads", "read")
async def trigger_firings(request: Request) -> FiringsView:
    """T051. The chronological firing log, newest first, reasons verbatim."""
    _, _, audit, _, _, _, _ = _engine_state(request.app.state)
    return describe_firings(audit)


@router.get("/rules/{rule_id}/runs", response_model=RunsView)
@require_permission("threads", "read")
async def trigger_runs(rule_id: str, request: Request) -> RunsView:
    """Feature 006. One automation's runs, each worded from its audit records
    (delivered, held then delivered, delivered with others, failed, or not
    settled yet), newest first."""
    _, _, audit, _, _, _, _ = _engine_state(request.app.state)
    history = getattr(request.app.state, "run_history", None)
    stored = None
    if history is not None:
        try:
            stored = history.list(kind="automation", source_id=rule_id, limit=500)
        except Exception:  # noqa: BLE001 — unreadable history reads as "unavailable", not "none"
            stored = None
    return describe_runs(audit, rule_id, stored=stored)


@router.get("/status", response_model=EngineStatus)
@require_permission("threads", "read")
async def engine_status(request: Request) -> EngineStatus:
    return describe_engine(request.app.state)
