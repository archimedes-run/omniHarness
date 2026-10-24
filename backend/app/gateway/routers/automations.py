"""Automations — create, edit, enable/disable and delete trigger rules (Phase 2.5).

THE write router for the trigger rule file. The triggers router stays
read-only (tests/gates/test_read_surfaces_do_not_write.py names exactly which
routers may write). Every change goes through app.gateway.automations_store:
validated with the engine's own parser, written atomically, refused if the file
changed since the page read it, and applied by the engine's hot reload. An
invalid change returns 422 with the engine's reason, and the rules in force are
untouched.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.gateway.authz import require_permission
from app.gateway.automations_store import TEMPLATES, RulesEditError, read_rules, with_rule, without_rule, write_rules
from app.gateway.ownership import require_owner_account

# Install-wide records: the owner account only (security baseline).
router = APIRouter(prefix="/api/automations", tags=["automations"], dependencies=[Depends(require_owner_account)])


class RuleWrite(BaseModel):
    #: The rule as the rule file holds it: id, type, enabled, match, prompt,
    #: destination, urgent. Validated by the engine's parser, not here.
    rule: dict[str, Any]
    #: The version (RulesView.version) this edit was based on.
    version: str


class EnabledWrite(BaseModel):
    enabled: bool
    version: str


class WriteResult(BaseModel):
    version: str


class Template(BaseModel):
    template: str
    title: str
    description: str
    rule: dict[str, Any]


def _target(request: Request):
    from app.gateway.trigger_engine_wiring import SUPPORTED_SOURCE_TYPES, _resolve_rules_path

    cfg = request.app.state.config.trigger_engine
    return _resolve_rules_path(cfg), bool(getattr(cfg, "rules_path", "")), SUPPORTED_SOURCE_TYPES


def edit_rules(app_config, change, version: str | None) -> str:
    """THE rule-file write path, for this router and for Agent Studio's
    schedules (Feature 006-F): read, apply `change` to the document, validate
    with the engine's parser, write atomically. `version` is the one the
    caller read (refused with 409 when stale); None means "the file as it is
    now" (the agent-delete hook, which has no page). Raises RulesEditError."""
    from app.gateway.trigger_engine_wiring import SUPPORTED_SOURCE_TYPES, _resolve_rules_path

    cfg = app_config.trigger_engine
    path, writable = _resolve_rules_path(cfg), bool(getattr(cfg, "rules_path", ""))
    try:
        current = read_rules(path)
        doc = change(current.doc)
        return write_rules(path, doc, expected_version=current.version if version is None else version, supported_types=SUPPORTED_SOURCE_TYPES, writable=writable)
    except (OSError, ValueError) as exc:
        if isinstance(exc, RulesEditError):
            raise
        raise RulesEditError(f"Could not read or write the rules file: {exc}", 500) from exc


def _apply(request: Request, change, version: str) -> WriteResult:
    try:
        return WriteResult(version=edit_rules(request.app.state.config, change, version))
    except RulesEditError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


async def _require_agent(rule: dict) -> None:
    """A rule may name only an agent that exists (Feature 006-F): one naming a
    missing agent would never run, and is never run as the lead instead."""
    from app.gateway.agent_schedules import agent_exists

    name = rule.get("agent")
    # "lead_agent" is the engine parser's to refuse ("leave agent out").
    if rule.get("enabled", True) and isinstance(name, str) and name.strip() not in ("", "lead_agent") and not await agent_exists(name):
        raise HTTPException(status_code=422, detail=f"There is no agent called {name.strip().lower()!r}. A rule runs only as an agent that exists, never as the lead agent in its place.")


@router.get("/templates", response_model=list[Template])
@require_permission("threads", "read")
async def templates(request: Request) -> list[Template]:
    return [Template(**t) for t in TEMPLATES]


@router.post("/rules", response_model=WriteResult, status_code=201)
@require_permission("threads", "write")
async def create_rule(body: RuleWrite, request: Request) -> WriteResult:
    await _require_agent(body.rule)
    return _apply(request, lambda doc: with_rule(doc, body.rule, replace=None), body.version)


@router.put("/rules/{rule_id}", response_model=WriteResult)
@require_permission("threads", "write")
async def replace_rule(rule_id: str, body: RuleWrite, request: Request) -> WriteResult:
    if body.rule.get("id") != rule_id:
        raise HTTPException(status_code=422, detail="A rule's id cannot be changed: it keys the rule's conversation thread. Create a new automation instead.")
    await _require_agent(body.rule)
    return _apply(request, lambda doc: with_rule(doc, body.rule, replace=rule_id), body.version)


@router.patch("/rules/{rule_id}/enabled", response_model=WriteResult)
@require_permission("threads", "write")
async def set_enabled(rule_id: str, body: EnabledWrite, request: Request) -> WriteResult:
    if body.enabled:
        path, _, _ = _target(request)
        try:
            named = next((r for r in read_rules(path).doc.get("rules") or [] if r.get("id") == rule_id), None)
        except (OSError, ValueError):
            named = None
        if named is not None:
            await _require_agent({**named, "enabled": True})

    def change(doc: dict) -> dict:
        rules = doc.get("rules") or []
        current = next((r for r in rules if r.get("id") == rule_id), None)
        if current is None:
            raise RulesEditError(f"No rule with id {rule_id!r}.", 404)
        return with_rule(doc, {**current, "enabled": body.enabled}, replace=rule_id)

    return _apply(request, change, body.version)


@router.delete("/rules/{rule_id}", response_model=WriteResult)
@require_permission("threads", "delete")
async def delete_rule(rule_id: str, version: str, request: Request) -> WriteResult:
    return _apply(request, lambda doc: without_rule(doc, rule_id), version)
