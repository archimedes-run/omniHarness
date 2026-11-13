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

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.automations_store import TEMPLATES, RulesEditError, history_dir, put_rule, read_rules, rules_by_id, with_rule, without_rule, write_rules
from app.gateway.ownership import require_owner_account
from omniharness.config import config_versions
from omniharness.runtime.user_context import get_effective_user_id

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


class RuleVersionSummary(BaseModel):
    version: int
    at: str
    who: str
    #: manual, chat, undo, existing (a baseline: the rule as it already was).
    source: str
    #: Which surface wrote it: page, studio, chat, agent-deleted; "hand-edit"
    #: for a baseline recorded because the file was edited by hand.
    via: str
    changed: list[str]
    deleted: bool


class RuleVersions(BaseModel):
    rule_id: str
    #: Send back as base_version. One past the last listed version when the
    #: file holds an edit not yet recorded (`unrecorded`).
    current: int
    #: The rule in the file differs from its last recorded version (a hand
    #: edit, or a rule from before versioning): the next write records it.
    unrecorded: bool
    #: Whether the rule is in the file now.
    exists: bool
    #: Version 0 may be restored: the first version created the rule, so
    #: undoing it deletes the rule (Spec 010 FR-020).
    can_undo_create: bool
    versions: list[RuleVersionSummary]


class RuleUndo(BaseModel):
    to_version: int = Field(..., ge=0, description="The version to restore, as a new version; 0 undoes the create (deletes the rule)")
    base_version: int = Field(..., ge=0, description="RuleVersions.current when the undo was chosen")
    via: Literal["page", "studio"] = Field("page", description="Which surface the undo was pressed on, for the history")


class Template(BaseModel):
    template: str
    title: str
    description: str
    rule: dict[str, Any]


def _target(request: Request):
    from app.gateway.trigger_engine_wiring import SUPPORTED_SOURCE_TYPES, _resolve_rules_path

    cfg = request.app.state.config.trigger_engine
    return _resolve_rules_path(cfg), bool(getattr(cfg, "rules_path", "")), SUPPORTED_SOURCE_TYPES


def edit_rules(app_config, change, version: str | None, *, who: str, source: str = "manual", via: str = "", base_versions: dict[str, int] | None = None) -> str:
    """THE rule-file write path, for this router, Agent Studio's schedules
    (Feature 006-F) and the chat builder (Spec 010): under the versioned
    store's lock, read, apply `change` to the document, validate with the
    engine's parser, write atomically and record a version per changed rule
    (config_versions kind "automation"). `version` is the file version the
    caller read (refused with 409 when stale); None means "the file as it is
    now" (the agent-delete hook and undo, which name a rule version instead).
    `base_versions`: {rule id: the rule version the caller read}, refused with
    409 when stale. Raises RulesEditError."""
    from app.gateway.trigger_engine_wiring import SUPPORTED_SOURCE_TYPES, _resolve_rules_path

    cfg = app_config.trigger_engine
    path, writable = _resolve_rules_path(cfg), bool(getattr(cfg, "rules_path", ""))
    try:
        return write_rules(path, change, expected_version=version, supported_types=SUPPORTED_SOURCE_TYPES, writable=writable, history=history_dir(cfg), who=who, source=source, via=via, base_versions=base_versions)
    except (OSError, ValueError) as exc:
        if isinstance(exc, RulesEditError):
            raise
        raise RulesEditError(f"Could not read or write the rules file: {exc}", 500) from exc


def rule_versions(app_config, rule_id: str) -> tuple[int, list[config_versions.Version], dict | None]:
    """(current version, history oldest first, the rule as the file holds it
    now). Reads only: a hand edit not yet recorded shows as `current` one past
    the last recorded version (config_versions.automation_version)."""
    from app.gateway.trigger_engine_wiring import _resolve_rules_path

    cfg = app_config.trigger_engine
    try:
        on_file = rules_by_id(read_rules(_resolve_rules_path(cfg)).doc).get(rule_id)
    except (OSError, ValueError) as exc:
        raise RulesEditError(f"Could not read the rules file: {exc}", 500) from exc
    hist = history_dir(cfg)
    return config_versions.automation_version(hist, rule_id, on_file), config_versions.automation_history(hist, rule_id), on_file


def undo_rule(app_config, rule_id: str, to_version: int, *, base_version: int, who: str, via: str = "page") -> str:
    """Restore `to_version` of the rule as a NEW version (Spec 010 FR-020): the
    history only grows. `to_version` 0 undoes a create: the rule is removed
    and the new version is a deleted one. Refused (409) when the rule changed
    since `base_version` was read. The one restore path for the Automations
    page, Studio and the chat builder. Raises RulesEditError."""
    try:
        target = config_versions.automation_target(history_dir(app_config.trigger_engine), rule_id, to_version)
    except config_versions.VersionNotFoundError as exc:
        raise RulesEditError(str(exc), 404) from exc
    return edit_rules(app_config, lambda doc: put_rule(doc, rule_id, target), None, who=who, source="undo", via=via, base_versions={rule_id: base_version})


def _who() -> str:
    return f"user:{get_effective_user_id()}"


def _apply(request: Request, change, version: str) -> WriteResult:
    try:
        return WriteResult(version=edit_rules(request.app.state.config, change, version, who=_who(), via="page"))
    except RulesEditError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


def _require_standard_cron(rule: dict) -> None:
    """A cron rule written here has a five-field schedule (croniter would also
    take a seconds field, and `* * * * * *` fires every second). The engine's
    loader is unchanged, so hand-written rules load as before."""
    from app.trigger_engine.config import standard_cron_problem

    match = rule.get("match")
    schedule = match.get("schedule") if isinstance(match, dict) else None
    # Only the field count is checked here; a malformed five-field schedule is
    # the engine parser's to refuse, in its own words.
    if rule.get("type") == "cron" and schedule and len(str(schedule).split()) != 5:
        problem = standard_cron_problem(schedule)
        if problem:
            raise HTTPException(status_code=422, detail=f"rule {rule.get('id')!r}: match.schedule {problem}")


async def _require_agent(rule: dict) -> None:
    """A rule may name only an agent that exists (Feature 006-F): one naming a
    missing agent would never run, and is never run as the lead instead."""
    from app.gateway.agent_schedules import agent_exists

    name = rule.get("agent")
    # "lead_agent" (any case) is the lead: the engine parser reads it so.
    if rule.get("enabled", True) and isinstance(name, str) and name.strip().lower() not in ("", "lead_agent") and not await agent_exists(name):
        raise HTTPException(status_code=422, detail=f"There is no agent called {name.strip().lower()!r}. A rule runs only as an agent that exists, never as the lead agent in its place.")


@router.get("/templates", response_model=list[Template])
@require_permission("threads", "read")
async def templates(request: Request) -> list[Template]:
    return [Template(**t) for t in TEMPLATES]


@router.post("/rules", response_model=WriteResult, status_code=201)
@require_permission("threads", "write")
async def create_rule(body: RuleWrite, request: Request) -> WriteResult:
    _require_standard_cron(body.rule)
    await _require_agent(body.rule)
    return _apply(request, lambda doc: with_rule(doc, body.rule, replace=None), body.version)


@router.put("/rules/{rule_id}", response_model=WriteResult)
@require_permission("threads", "write")
async def replace_rule(rule_id: str, body: RuleWrite, request: Request) -> WriteResult:
    if body.rule.get("id") != rule_id:
        raise HTTPException(status_code=422, detail="A rule's id cannot be changed: it keys the rule's conversation thread. Create a new automation instead.")
    _require_standard_cron(body.rule)
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


def _versions_view(request: Request, rule_id: str) -> RuleVersions:
    try:
        current, versions, on_file = rule_versions(request.app.state.config, rule_id)
    except RulesEditError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    if not versions and on_file is None:
        raise HTTPException(status_code=404, detail=f"No rule with id {rule_id!r}.")
    return RuleVersions(
        rule_id=rule_id,
        current=current,
        unrecorded=current != (versions[-1].version if versions else 0),
        exists=on_file is not None,
        can_undo_create=bool(versions) and versions[0].source != "existing",
        versions=[RuleVersionSummary(**v.summary(), via=v.via) for v in reversed(versions)],
    )


@router.get("/rules/{rule_id}/versions", response_model=RuleVersions)
@require_permission("threads", "read")
async def rule_versions_route(rule_id: str, request: Request) -> RuleVersions:
    """One rule's version history (Spec 010 FR-021), newest first. Reads only."""
    return _versions_view(request, rule_id)


@router.post("/rules/{rule_id}/undo", response_model=RuleVersions)
@require_permission("threads", "write")
async def undo_rule_route(rule_id: str, body: RuleUndo, request: Request) -> RuleVersions:
    """Restore an earlier version of a rule as a new version; to_version 0
    undoes its create. 409 when the rule changed since base_version."""
    config = request.app.state.config
    try:
        target = config_versions.automation_target(history_dir(config.trigger_engine), rule_id, body.to_version)
    except config_versions.VersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if target is not None:
        _require_standard_cron(target)
        await _require_agent(target)
    try:
        undo_rule(config, rule_id, body.to_version, base_version=body.base_version, who=_who(), via=body.via)
    except RulesEditError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return _versions_view(request, rule_id)
