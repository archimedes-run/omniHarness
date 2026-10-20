"""Agent Studio's read side (Feature 006, Phase 3).

What the Agents panel needs beside the agents API: the tool groups an agent
may be limited to, the model a run would use, and an agent's schedule and
recent runs from the trigger engine. Read only; the agent itself is written
through /api/agents.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.gateway.agent_runs_view import AgentRunsView, describe_agent_runs
from app.gateway.authz import require_permission
from app.gateway.deps import get_config
from omniharness.config.app_config import AppConfig

router = APIRouter(prefix="/api/studio", tags=["studio"])


class StudioOptions(BaseModel):
    tool_groups: list[str] = Field(..., description="Tool groups configured in config.yaml, in order")
    default_model: str | None = Field(..., description="The model a run uses when the agent names none")


@router.get("/options", response_model=StudioOptions, summary="Agent Studio options")
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
