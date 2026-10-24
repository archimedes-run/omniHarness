"""Agent Studio's read side (Feature 006, Phase 3).

What the Agents panel needs beside the agents API: the tool groups an agent
may be limited to, the model a run would use, and an agent's schedule and
recent runs from the trigger engine. The agent itself is written through
/api/agents; its schedules (Feature 006-F) through the Automations write path.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.agent_runs_view import AgentRunsView, describe_agent_runs
from app.gateway.authz import permission_dependency, require_permission
from app.gateway.deps import get_config
from app.gateway.display_safe import safe_field
from app.gateway.ownership import require_owner_account
from omniharness.config.app_config import AppConfig

router = APIRouter(prefix="/api/studio", tags=["studio"])


class StudioOptions(BaseModel):
    tool_groups: list[str] = Field(..., description="Tool groups configured in config.yaml, in order")
    default_model: str | None = Field(..., description="The model a run uses when the agent names none")


@router.get("/options", dependencies=[Depends(permission_dependency("threads", "read"))], response_model=StudioOptions, summary="Agent Studio options")
async def studio_options(config: AppConfig = Depends(get_config)) -> StudioOptions:
    return StudioOptions(
        tool_groups=[group.name for group in config.tool_groups],
        default_model=config.models[0].name if config.models else None,
    )


def _agent_key(name: str) -> str:
    return name if name == "lead_agent" else name.strip().lower()


@router.get("/agents/{name}/runs", response_model=AgentRunsView, dependencies=[Depends(require_owner_account)], summary="An agent's schedule and recent runs")
@require_permission("threads", "read")
async def agent_runs(name: str, request: Request) -> AgentRunsView:
    """From the trigger engine's own files: its rules, quiet hours and audit
    log. Install-wide records, so the owner account only (like Automations)."""
    from pathlib import Path

    from app.gateway.automations_store import read_rules
    from app.gateway.trigger_engine_wiring import _quiet_hours, _resolve_rules_path
    from app.trigger_engine.audit import AuditLog
    from app.trigger_engine.config import ConfigLoader

    cfg = request.app.state.config.trigger_engine
    path = _resolve_rules_path(cfg)
    loader = ConfigLoader(path=path)
    engine_config = loader.load()
    audit = AuditLog(path=Path(cfg.state_dir) / "audit.jsonl", actor=cfg.actor).entries()
    view = describe_agent_runs(
        agent=_agent_key(name),
        rules=list(engine_config.rules),
        quiet_hours=_quiet_hours(engine_config),
        audit=audit,
        engine_enabled=cfg.enabled,
        rules_error=loader.last_error,
    )
    try:
        view.rules_version = read_rules(path).version
    except (OSError, ValueError):
        view.rules_version = None
    view.writable = bool(getattr(cfg, "rules_path", "")) and view.rules_version is not None
    return view


# -- per-agent schedules (Feature 006-F) -------------------------------------
#
# A schedule IS a cron trigger rule naming the agent. Written through the
# Automations write path (automations.edit_rules: the engine's own parser,
# atomic, refused on a stale version), so the rule file stays the engine's
# source of truth and its hot reload applies the change with no restart.


class ScheduleWrite(BaseModel):
    schedule: str = Field(..., description="Cron: minute hour day month weekday")
    timezone: str = Field(..., description="IANA time zone, e.g. America/New_York")
    telegram: bool = Field(True, description="Send the result to Telegram (the existing channel delivery)")
    show_on_home: bool = Field(True, description="Show its upcoming runs and results on Home")
    prompt: str | None = Field(None, max_length=4000, description="What the firing asks the agent; a default when empty")
    name: str | None = Field(None, max_length=80, description="Display name")
    enabled: bool = True
    version: str = Field(..., description="The rule file version (AgentRunsView.rules_version) this edit was based on")


class ScheduleWritten(BaseModel):
    rule_id: str
    version: str


async def _schedule_agent(name: str) -> str:
    """The agent a schedule is for: the lead, or a custom agent that exists
    for the owner (404 otherwise: a schedule never names a missing agent)."""
    from app.gateway.agent_schedules import agent_exists

    agent = _agent_key(name)
    if agent == "lead_agent":
        return agent
    if not agent or not all(ch.isalnum() or ch == "-" for ch in agent):
        raise HTTPException(status_code=422, detail=f"{name!r} is not an agent name")
    if not await agent_exists(agent):
        raise HTTPException(status_code=404, detail=f"Agent '{agent}' not found")
    return agent


def _write_schedule(request: Request, change, version: str | None) -> str:
    from app.gateway.automations_store import RulesEditError
    from app.gateway.routers.automations import edit_rules

    try:
        return edit_rules(request.app.state.config, change, version)
    except RulesEditError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


def _check_schedule(body: ScheduleWrite) -> None:
    from app.gateway.agent_schedules import schedule_problem

    problem = schedule_problem(body.schedule, body.timezone)
    if problem:
        raise HTTPException(status_code=422, detail=problem)


def _owned_rule(doc: dict, agent: str, rule_id: str) -> dict:
    """The rule `rule_id` if it is this agent's schedule; 404 otherwise, so a
    schedule edit can never reach another agent's rule or the lead's."""
    from app.gateway.automations_store import RulesEditError

    rule = next((r for r in doc.get("rules") or [] if r.get("id") == rule_id), None)
    named = rule.get("agent") if rule else None
    owner = named.strip().lower() if isinstance(named, str) and named.strip() else "lead_agent"
    if rule is None or owner != agent or rule.get("type") != "cron":
        raise RulesEditError(f"{agent} has no schedule {rule_id!r}.", 404)
    return rule


@router.post("/agents/{name}/schedules", response_model=ScheduleWritten, status_code=201, dependencies=[Depends(require_owner_account)], summary="Give an agent a schedule (a cron rule that runs as it)")
@require_permission("threads", "write")
async def create_schedule(name: str, body: ScheduleWrite, request: Request) -> ScheduleWritten:
    from app.gateway.agent_schedules import schedule_rule, schedule_rule_id
    from app.gateway.automations_store import with_rule

    agent = await _schedule_agent(name)
    _check_schedule(body)
    made: dict[str, str] = {}

    def change(doc: dict) -> dict:
        rule_id = schedule_rule_id(agent, {r.get("id") for r in doc.get("rules") or []})
        made["id"] = rule_id
        rule = schedule_rule(rule_id=rule_id, agent=agent, schedule=body.schedule, timezone=body.timezone, telegram=body.telegram, show_on_home=body.show_on_home, prompt=body.prompt, name=body.name, enabled=body.enabled)
        return with_rule(doc, rule, replace=None)

    version = _write_schedule(request, change, body.version)
    return ScheduleWritten(rule_id=made["id"], version=version)


@router.put("/agents/{name}/schedules/{rule_id}", response_model=ScheduleWritten, dependencies=[Depends(require_owner_account)], summary="Change one of an agent's schedules")
@require_permission("threads", "write")
async def update_schedule(name: str, rule_id: str, body: ScheduleWrite, request: Request) -> ScheduleWritten:
    from app.gateway.agent_schedules import schedule_rule
    from app.gateway.automations_store import with_rule

    agent = await _schedule_agent(name)
    _check_schedule(body)

    def change(doc: dict) -> dict:
        current = _owned_rule(doc, agent, rule_id)
        rule = schedule_rule(
            rule_id=rule_id,
            agent=agent,
            schedule=body.schedule,
            timezone=body.timezone,
            telegram=body.telegram,
            show_on_home=body.show_on_home,
            prompt=body.prompt or current.get("prompt"),
            name=body.name if body.name is not None else current.get("name"),
            enabled=body.enabled,
        )
        # Keep what this editor does not edit (urgent, comments, future keys).
        return with_rule(doc, {**current, **rule}, replace=rule_id)

    return ScheduleWritten(rule_id=rule_id, version=_write_schedule(request, change, body.version))


@router.delete("/agents/{name}/schedules/{rule_id}", response_model=ScheduleWritten, dependencies=[Depends(require_owner_account)], summary="Delete one of an agent's schedules")
@require_permission("threads", "delete")
async def delete_schedule(name: str, rule_id: str, version: str, request: Request) -> ScheduleWritten:
    from app.gateway.automations_store import without_rule

    agent = _agent_key(name)

    def change(doc: dict) -> dict:
        _owned_rule(doc, agent, rule_id)
        return without_rule(doc, rule_id)

    return ScheduleWritten(rule_id=rule_id, version=_write_schedule(request, change, version))


# -- autonomy: standing grants (app/policy/grants.py) ------------------------


class ActionClassView(BaseModel):
    id: str
    label: str
    allows: str = Field(..., description="What it lets the agent do, in plain words")
    granted: bool
    grantable: bool
    not_grantable_reason: str = ""


class AutonomyView(BaseModel):
    agent: str
    version: int = Field(..., description="The agent's current version; send it back as base_version")
    classes: list[ActionClassView]
    cap_per_run: int
    always_waits: list[str] = Field(..., description="Tier 3 rules that are not reversible, from the rules in force")
    rules_error: str | None = None


class AutonomyUpdate(BaseModel):
    granted: list[str] = Field(..., description="Action class ids to grant; every other one is revoked")
    base_version: int = Field(..., ge=0)


def _agent_or_404(name: str, user_id: str) -> str:
    from omniharness.config import config_versions

    name = name.strip().lower() if name != config_versions.LEAD_AGENT else name
    try:
        exists = name == config_versions.LEAD_AGENT or config_versions.current_agent_snapshot(user_id, name) is not None
    except ValueError as e:  # a malformed name never reaches the filesystem
        raise HTTPException(status_code=422, detail=str(e))
    if not exists:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    return name


def _rules(config: AppConfig):
    from app.policy.registration import shared_loader

    loader = shared_loader(config.policy)
    return loader.load(notify=False), loader.last_error


def _autonomy_view(agent: str, user_id: str, config: AppConfig) -> AutonomyView:
    from app.policy.grants import ACTION_CLASSES, GRANT_CAP_PER_RUN, always_waits, grantable, granted_classes
    from omniharness.config import config_versions

    ruleset, error = _rules(config)
    granted = set(granted_classes(user_id, agent))
    classes = []
    for action in ACTION_CLASSES:
        ok, why = grantable(action.id, ruleset)
        classes.append(ActionClassView(id=action.id, label=action.label, allows=action.allows, granted=action.id in granted and ok, grantable=ok, not_grantable_reason=why))
    return AutonomyView(agent=agent, version=config_versions.agent_version(user_id, agent), classes=classes, cap_per_run=GRANT_CAP_PER_RUN, always_waits=always_waits(ruleset), rules_error=error)


def _require_agents_api_enabled() -> None:
    """Grants are part of an agent's config: the same switch as the agents API."""
    from app.gateway.routers.agents import _require_agents_api_enabled as require

    require()


@router.get("/agents/{name}/autonomy", dependencies=[Depends(permission_dependency("threads", "read"))], response_model=AutonomyView, summary="What an agent may do on its own in a scheduled run")
async def get_autonomy(name: str, config: AppConfig = Depends(get_config)) -> AutonomyView:
    from omniharness.runtime.user_context import get_effective_user_id

    _require_agents_api_enabled()
    user_id = get_effective_user_id()
    return _autonomy_view(_agent_or_404(name, user_id), user_id, config)


@router.put("/agents/{name}/autonomy", dependencies=[Depends(permission_dependency("threads", "write"))], response_model=AutonomyView, summary="Grant or revoke standing permissions (a new agent version)")
async def put_autonomy(name: str, request: AutonomyUpdate, config: AppConfig = Depends(get_config)) -> AutonomyView:
    """Refuses, server-side, any class that is not reversible in the rules in
    force: the checkbox being absent in the UI is not the guarantee."""
    from app.policy.grants import AUTONOMY_KEY, grantable
    from omniharness.config import config_versions
    from omniharness.runtime.user_context import get_effective_user_id

    _require_agents_api_enabled()
    user_id = get_effective_user_id()
    agent = _agent_or_404(name, user_id)
    ruleset, _ = _rules(config)
    refused = [(class_id, why) for class_id in request.granted for ok, why in [grantable(class_id, ruleset)] if not ok]
    if refused:
        raise HTTPException(status_code=422, detail="Not granted: " + "; ".join(why for _, why in refused))
    snapshot = config_versions.current_agent_snapshot(user_id, agent) or {"config": {}, "soul": ""}
    agent_config = dict(snapshot.get("config") or {})
    agent_config[AUTONOMY_KEY] = sorted(set(request.granted))
    soul = snapshot.get("soul")
    if agent == config_versions.LEAD_AGENT:
        # The lead agent's SOUL.md is shared; leave it exactly as it is.
        from omniharness.config.agents_config import load_agent_soul

        soul = load_agent_soul(None) or ""
    try:
        # The one write that may change grants: this explicit Autonomy action.
        config_versions.write_agent(user_id, agent, {"config": agent_config, "soul": soul or ""}, who=f"user:{user_id}", source="manual", base_version=request.base_version, sets_autonomy=True)
    except config_versions.StaleWriteError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _autonomy_view(agent, user_id, config)


class GrantUse(BaseModel):
    at: str
    firing_id: str | None = None
    write_id: str | None = None
    source_label: str | None = None
    tool: str
    classes: list[str]
    targets: list[str]
    thread_id: str | None
    rule_id: str | None
    origin: str = Field(..., description="automation (the schedule's own turn), content (something the agent read), or unknown")
    origin_source: str
    count_in_run: int


@router.get("/agents/{name}/grant-uses", dependencies=[Depends(permission_dependency("threads", "read"))], response_model=list[GrantUse], summary="What an agent did on its own under its grants, newest first")
async def grant_uses(name: str, config: AppConfig = Depends(get_config)) -> list[GrantUse]:
    from pathlib import Path

    from app.policy.audit import PolicyAuditLog
    from omniharness.runtime.user_context import get_effective_user_id

    _require_agents_api_enabled()
    user_id = get_effective_user_id()
    agent = name.strip().lower() if name != "lead_agent" else name
    entries = PolicyAuditLog(path=Path(config.policy.state_dir) / "audit.jsonl", actor="default").entries()
    mine = [e for e in entries if e.get("kind") == "grant-use" and e.get("agent") == agent and e.get("user_id") == user_id]
    mine.sort(key=lambda e: e.get("at", ""), reverse=True)
    out = []
    for e in mine[:50]:
        fields = {k: e.get(k) for k in GrantUse.model_fields}
        fields["targets"] = [safe_field(t) for t in e.get("targets") or []]
        fields["source_label"] = safe_field(e.get("source_label") or "")
        out.append(GrantUse(**fields))
    return out


# -- a scheduled run's summary: what it did on its own, and Undo all --------


class RunWrite(BaseModel):
    at: str
    tool: str
    classes: list[str]
    targets: list[str]
    source_label: str = Field("", description='What the write came from, in words: "from: email “…”", "from: page “…”" (redacted; never the body)')
    write_id: str | None
    undone: bool


class RunSummary(BaseModel):
    firing_id: str
    rule_id: str | None
    agent: str
    writes: list[RunWrite]
    all_undone: bool


def _run_entries(request: Request, config: AppConfig, firing_id: str, user_id: str) -> list[dict]:
    from pathlib import Path

    from app.policy.audit import PolicyAuditLog

    entries = PolicyAuditLog(path=Path(config.policy.state_dir) / "audit.jsonl", actor="default").entries()
    return [e for e in entries if e.get("kind") == "grant-use" and e.get("firing_id") == firing_id and e.get("user_id") == user_id]


def _run_summary(request: Request, config: AppConfig, firing_id: str) -> RunSummary:
    from omniharness.runtime.user_context import get_effective_user_id

    user_id = get_effective_user_id()
    mine = _run_entries(request, config, firing_id, user_id)
    if not mine:
        raise HTTPException(status_code=404, detail="No run with that id did anything on its own")
    service = getattr(request.app.state, "ledger_service", None)
    writes = []
    for e in sorted(mine, key=lambda e: e.get("at", "")):
        write_id = e.get("write_id")
        undone = bool(service is not None and write_id and service.write_undone(user_id=user_id, write_id=write_id))
        writes.append(
            RunWrite(
                at=e.get("at", ""),
                tool=e.get("tool", ""),
                classes=e.get("classes") or [],
                targets=[safe_field(t) for t in e.get("targets") or []],
                source_label=safe_field(e.get("source_label") or ""),
                write_id=write_id,
                undone=undone,
            )
        )
    return RunSummary(firing_id=firing_id, rule_id=mine[0].get("rule_id"), agent=mine[0].get("agent") or "", writes=writes, all_undone=all(w.undone for w in writes))


@router.get("/runs/{firing_id}", dependencies=[Depends(permission_dependency("threads", "read"))], response_model=RunSummary, summary="What a scheduled run did on its own, each with what it came from")
async def run_summary(firing_id: str, request: Request, config: AppConfig = Depends(get_config)) -> RunSummary:
    import asyncio

    return await asyncio.to_thread(_run_summary, request, config, firing_id)


@router.post("/runs/{firing_id}/undo", dependencies=[Depends(permission_dependency("threads", "write"))], response_model=RunSummary, summary="Undo everything a scheduled run did on its own, all or nothing")
async def undo_run(firing_id: str, request: Request, config: AppConfig = Depends(get_config)) -> RunSummary:
    """Reverts every granted write of this run in one transaction; refused
    (409, nothing changed) if any was edited since or was already undone."""
    import asyncio

    from app.ledger.service import LedgerError

    summary = await asyncio.to_thread(_run_summary, request, config, firing_id)
    service = getattr(request.app.state, "ledger_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="the project ledger needs a database")
    pending = [w.write_id for w in summary.writes if w.write_id and not w.undone]
    if not pending:
        raise HTTPException(status_code=409, detail="everything this run did is already undone")
    from omniharness.runtime.user_context import get_effective_user_id

    user_id = get_effective_user_id()
    try:
        await asyncio.to_thread(service.undo_writes, user_id=user_id, write_ids=pending)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LedgerError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await asyncio.to_thread(_run_summary, request, config, firing_id)
