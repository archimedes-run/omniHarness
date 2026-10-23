"""Draft from one sentence (Feature 006, Phase 3, FR-301).

The user types one sentence; the model fills the large fields; the panel shows
the result for REVIEW. THIS MODULE NEVER WRITES: no agent, skill or file is
touched here, and tests/gates/test_drafts_never_write.py holds that. Saving is
the agents and skills APIs' job, when the user presses Save.

THE SAME MODEL A RUN WOULD USE. An agent's draft resolves its model the way
make_lead_agent does (`_resolve_model_name` over the agent's own model, else
the default) and builds it with the one factory every run uses
(`create_chat_model`). The response names it, so the panel can say who drafted.

Suggestions are checked against what exists: a tool group or skill the model
names that is not configured is dropped, and the response says which.

ONE SENTENCE FILLS EVERY TAB of Agent Studio (Overview, Instructions, Tools
and skills, Autonomy, Schedule): besides the text fields the model may pick
the projects it works on (only the caller's own, by name), the reversible
actions it might be allowed on a schedule (only grantable classes), and a
schedule (a valid cron expression). All of it is a SUGGESTION for review:
the panel never ticks a grant for the user and never creates a schedule.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.authz import permission_dependency
from app.gateway.deps import get_config
from omniharness.agents.lead_agent.agent import _resolve_model_name
from omniharness.config.app_config import AppConfig
from omniharness.models import create_chat_model

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/drafts", tags=["drafts"])

DraftKind = Literal["agent", "skill"]


class DraftRequest(BaseModel):
    sentence: str = Field(..., min_length=1, max_length=600, description="The user's one sentence")
    #: For an agent: its slug, so the draft uses that agent's own model.
    agent_name: str | None = Field(None, max_length=64, pattern=r"^[A-Za-z0-9-]+$")
    #: For a skill: what is already written, so a "when" draft fits the body.
    name: str | None = Field(None, max_length=120)
    body: str | None = Field(None, max_length=20_000)


class DraftSchedule(BaseModel):
    #: A 5-field cron expression the trigger engine accepts (croniter).
    cron: str
    #: An IANA zone if the sentence named one; else the engine's default.
    timezone: str | None = None


class AgentDraft(BaseModel):
    display_name: str
    description: str
    instructions: str
    tool_groups: list[str]
    skills: list[str]
    #: The caller's own project ids it would work on (Overview: "Works on").
    projects: list[str] = Field(default_factory=list)
    #: Grantable action-class ids it might do on its own on a schedule
    #: (Autonomy). Suggested only: never granted by a draft.
    autonomy: list[str] = Field(default_factory=list)
    #: When it should run, if the sentence says (Schedule). Suggested only.
    schedule: DraftSchedule | None = None


class SkillDraft(BaseModel):
    #: A short name for a NEW skill (the panel makes the slug); "" if none.
    name: str = ""
    description: str
    body: str


class DraftResponse(BaseModel):
    kind: DraftKind
    model: str = Field(..., description="The configured model that drafted it")
    agent: AgentDraft | None = None
    skill: SkillDraft | None = None
    #: Names the model suggested that do not exist here, left out.
    dropped: list[str] = Field(default_factory=list)


AGENT_PROMPT = """You draft a custom AI agent from the user's one sentence.
Return ONLY a JSON object with these keys:
  "display_name": a short name for people (2-4 words, sentence case),
  "description": one line saying what it does,
  "instructions": the agent's instructions, written to the agent in the second person ("You are ..."), as numbered steps where useful, under 200 words,
  "tool_groups": the tool groups it needs, chosen ONLY from: {groups},
  "skills": skills it should load every run, chosen ONLY from: {skills},
  "projects": names of the projects it works on, chosen ONLY from: {projects},
  "autonomy": what it could do on its own when it runs on a schedule, chosen ONLY from: {classes},
  "schedule": if the sentence says when it should run, {{"cron": a 5-field cron expression such as "0 18 * * 1-5", "timezone": an IANA zone only if the sentence names one, else null}}; otherwise null.
Never invent a tool group, skill, project or action. Use [] when none fit."""

SKILL_PROMPT = """You draft an agent skill (a SKILL.md) from the user's one sentence.
Return ONLY a JSON object with these keys:
  "name": a short name for the skill (2-4 words, sentence case),
  "description": one sentence that says WHEN the skill should be used, naming the situations, not the steps (the model reads it to decide whether to load the skill),
  "body": the skill's instructions in Markdown: a "# " heading, then short steps or bullets, under 250 words.
{existing}"""


def _json_object(text: str) -> dict:
    """The first JSON object in a model reply, fenced or not."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    raw = fenced.group(1) if fenced else text[text.find("{") : text.rfind("}") + 1]
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=502, detail="The model's draft was not readable JSON. Try again or rephrase.")
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=502, detail="The model's draft was not a JSON object.")
    return parsed


def _text(value, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _names(value) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _own_projects(http_request: Request, user_id: str) -> list[dict]:
    """The caller's own active projects ({id, name}); [] without a ledger."""
    from datetime import date

    service = getattr(http_request.app.state, "ledger_service", None)
    if service is None:
        return []
    try:
        rows = service.summaries(user_id=user_id, today=date.today())
    except Exception as exc:  # noqa: BLE001 — a draft without projects, not a failed draft
        logger.warning("draft: projects unreadable: %s", exc)
        return []
    return [{"id": str(r["id"]), "name": str(r["name"])} for r in rows if r.get("status", "active") == "active" and r.get("name")]


def _grantable_classes(config: AppConfig) -> list[tuple[str, str]]:
    """(id, label) of the action classes the rules in force let a user grant."""
    from app.policy.grants import ACTION_CLASSES, grantable
    from app.policy.registration import shared_loader

    try:
        ruleset = shared_loader(config.policy).load(notify=False)
    except Exception:  # noqa: BLE001 — unreadable rules: nothing is grantable
        return []
    return [(a.id, a.label) for a in ACTION_CLASSES if grantable(a.id, ruleset)[0]]


def _schedule(value) -> tuple[DraftSchedule | None, str | None]:
    """A valid suggested schedule, or (None, what was dropped)."""
    if not isinstance(value, dict):
        return None, None
    cron = _text(value.get("cron"), 64)
    if not cron:
        return None, None
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    from croniter import croniter

    if len(cron.split()) != 5 or not croniter.is_valid(cron):
        return None, f"schedule {cron!r}"
    zone = _text(value.get("timezone"), 64) or None
    if zone:
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError):
            zone = None
    return DraftSchedule(cron=cron, timezone=zone), None


def _agent_model(agent_name: str | None, config: AppConfig, user_id: str) -> str:
    requested = None
    if agent_name:
        from omniharness.config.agents_config import load_agent_config

        try:
            cfg = load_agent_config(agent_name.lower(), user_id=user_id)
            requested = cfg.model if cfg else None
        except (FileNotFoundError, ValueError):
            requested = None
    return _resolve_model_name(requested, app_config=config)


async def _ask(model_name: str, system: str, sentence: str, config: AppConfig) -> str:
    try:
        model = create_chat_model(name=model_name, thinking_enabled=False, app_config=config)
        reply = await model.ainvoke([{"role": "system", "content": system}, {"role": "user", "content": sentence}], config={"run_name": "studio_draft"})
    except Exception as exc:  # noqa: BLE001 — the panel shows the reason, nothing is saved
        logger.warning("draft model call failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"The model could not draft this: {type(exc).__name__}: {exc}")
    content = getattr(reply, "content", "")
    if isinstance(content, list):
        content = "".join(block.get("text", "") for block in content if isinstance(block, dict))
    return str(content or "")


@router.post("/{kind}", dependencies=[Depends(permission_dependency("threads", "read"))], response_model=DraftResponse, summary="Draft an agent or skill from one sentence (never saves)")
async def draft(kind: DraftKind, request: DraftRequest, http_request: Request, config: AppConfig = Depends(get_config)) -> DraftResponse:
    if kind == "agent":
        from omniharness.skills.storage import get_or_new_skill_storage

        groups = [g.name for g in config.tool_groups]
        skills = [s.name for s in get_or_new_skill_storage(app_config=config).load_skills(enabled_only=True)]
        from omniharness.runtime.user_context import get_effective_user_id

        # Whose agent picks the model: the caller's, passed explicitly.
        user_id = get_effective_user_id()
        model_name = _agent_model(request.agent_name, config, user_id)
        projects = _own_projects(http_request, user_id)
        classes = _grantable_classes(config)
        system = AGENT_PROMPT.format(
            groups=", ".join(groups) or "(none)",
            skills=", ".join(skills) or "(none)",
            projects=json.dumps([p["name"] for p in projects], ensure_ascii=False) if projects else "(none)",
            classes=", ".join(f"{cid} ({label})" for cid, label in classes) or "(none)",
        )
        data = _json_object(await _ask(model_name, system, request.sentence, config))
        suggested_groups, suggested_skills = _names(data.get("tool_groups")), _names(data.get("skills"))
        dropped = [g for g in suggested_groups if g not in groups] + [s for s in suggested_skills if s not in skills]
        by_name = {p["name"].strip().casefold(): p["id"] for p in projects}
        project_ids: list[str] = []
        for name in _names(data.get("projects")):
            pid = by_name.get(name.strip().casefold())
            if pid is None:
                dropped.append(name)
            elif pid not in project_ids:
                project_ids.append(pid)
        allowed = {cid for cid, _ in classes}
        autonomy = [c for c in dict.fromkeys(_names(data.get("autonomy"))) if c in allowed]
        dropped += [c for c in _names(data.get("autonomy")) if c not in allowed]
        schedule, bad_schedule = _schedule(data.get("schedule"))
        if bad_schedule:
            dropped.append(bad_schedule)
        result = AgentDraft(
            display_name=_text(data.get("display_name"), 80),
            description=_text(data.get("description"), 300),
            instructions=_text(data.get("instructions"), 8_000),
            tool_groups=[g for g in suggested_groups if g in groups],
            skills=[s for s in suggested_skills if s in skills],
            projects=project_ids,
            autonomy=autonomy,
            schedule=schedule,
        )
        if not result.instructions:
            raise HTTPException(status_code=502, detail="The model returned no instructions. Try again or rephrase.")
        return DraftResponse(kind=kind, model=model_name, agent=result, dropped=dropped)

    model_name = _resolve_model_name(None, app_config=config)
    existing = ""
    if request.name or request.body:
        existing = f"The skill so far:\nName: {request.name or '(none)'}\n{request.body or ''}"
    data = _json_object(await _ask(model_name, SKILL_PROMPT.format(existing=existing), request.sentence, config))
    result = SkillDraft(name=_text(data.get("name"), 80), description=_text(data.get("description"), 600), body=_text(data.get("body"), 20_000))
    if not (result.description or result.body):
        raise HTTPException(status_code=502, detail="The model returned an empty draft. Try again or rephrase.")
    return DraftResponse(kind=kind, model=model_name, skill=result)
