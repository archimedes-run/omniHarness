"""Agent Studio's read side (Feature 006, Phase 3).

What the Agents panel needs beside the agents API: the tool groups an agent
may be limited to, the model a run would use, and an agent's schedule and
recent runs from the trigger engine. Read only; the agent itself is written
through /api/agents.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.agent_runs_view import AgentRunsView, describe_agent_runs
from app.gateway.authz import permission_dependency, require_permission
from app.gateway.deps import get_config
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


@router.get("/agents/{name}/runs", response_model=AgentRunsView, summary="An agent's schedule and recent runs")
@require_permission("threads", "read")
async def agent_runs(name: str, request: Request) -> AgentRunsView:
    """From the trigger engine's own files: its rules, quiet hours and audit log."""
    from pathlib import Path

    from app.gateway.trigger_engine_wiring import _quiet_hours, _resolve_rules_path
    from app.trigger_engine.audit import AuditLog
    from app.trigger_engine.config import ConfigLoader

    cfg = request.app.state.config.trigger_engine
    loader = ConfigLoader(path=_resolve_rules_path(cfg))
    engine_config = loader.load()
    audit = AuditLog(path=Path(cfg.state_dir) / "audit.jsonl", actor=cfg.actor).entries()
    return describe_agent_runs(
        agent=name.strip().lower(),
        rules=list(engine_config.rules),
        quiet_hours=_quiet_hours(engine_config),
        audit=audit,
        engine_enabled=cfg.enabled,
        rules_error=loader.last_error,
    )


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
    return [GrantUse(**{k: e.get(k) for k in GrantUse.model_fields}) for e in mine[:50]]
