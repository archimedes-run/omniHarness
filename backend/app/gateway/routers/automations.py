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

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.gateway.authz import require_permission
from app.gateway.automations_store import TEMPLATES, RulesEditError, read_rules, with_rule, without_rule, write_rules

router = APIRouter(prefix="/api/automations", tags=["automations"])


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


def _apply(request: Request, change, version: str) -> WriteResult:
    path, writable, supported = _target(request)
    try:
        current = read_rules(path)
        doc = change(current.doc)
        return WriteResult(version=write_rules(path, doc, expected_version=version, supported_types=supported, writable=writable))
    except RulesEditError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"Could not read or write the rules file: {exc}") from exc


@router.get("/templates", response_model=list[Template])
@require_permission("threads", "read")
async def templates(request: Request) -> list[Template]:
    return [Template(**t) for t in TEMPLATES]


@router.post("/rules", response_model=WriteResult, status_code=201)
@require_permission("threads", "write")
async def create_rule(body: RuleWrite, request: Request) -> WriteResult:
    return _apply(request, lambda doc: with_rule(doc, body.rule, replace=None), body.version)


@router.put("/rules/{rule_id}", response_model=WriteResult)
@require_permission("threads", "write")
async def replace_rule(rule_id: str, body: RuleWrite, request: Request) -> WriteResult:
    if body.rule.get("id") != rule_id:
        raise HTTPException(status_code=422, detail="A rule's id cannot be changed: it keys the rule's conversation thread. Create a new automation instead.")
    return _apply(request, lambda doc: with_rule(doc, body.rule, replace=rule_id), body.version)


@router.patch("/rules/{rule_id}/enabled", response_model=WriteResult)
@require_permission("threads", "write")
async def set_enabled(rule_id: str, body: EnabledWrite, request: Request) -> WriteResult:
    def change(doc: dict) -> dict:
        rules = doc.get("rules") or []
        current = next((r for r in rules if r.get("id") == rule_id), None)
        if current is None:
            raise RulesEditError(f"No rule with id {rule_id!r}.", 404)
        return with_rule(doc, {**current, "enabled": body.enabled}, replace=rule_id)

    return _apply(request, change, body.version)


@router.delete("/rules/{rule_id}", response_model=WriteResult)
@require_permission("threads", "write")
async def delete_rule(rule_id: str, version: str, request: Request) -> WriteResult:
    return _apply(request, lambda doc: without_rule(doc, rule_id), version)
