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
"""

from __future__ import annotations

import json
import logging
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
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


class AgentDraft(BaseModel):
    display_name: str
    description: str
    instructions: str
    tool_groups: list[str]
    skills: list[str]


class SkillDraft(BaseModel):
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
  "skills": skills it should load every run, chosen ONLY from: {skills}.
Never invent a tool group or skill. Use [] when none fit."""

SKILL_PROMPT = """You draft an agent skill (a SKILL.md) from the user's one sentence.
Return ONLY a JSON object with these keys:
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
async def draft(kind: DraftKind, request: DraftRequest, config: AppConfig = Depends(get_config)) -> DraftResponse:
    if kind == "agent":
        from omniharness.skills.storage import get_or_new_skill_storage

        groups = [g.name for g in config.tool_groups]
        skills = [s.name for s in get_or_new_skill_storage(app_config=config).load_skills(enabled_only=True)]
        from omniharness.runtime.user_context import get_effective_user_id

        # Whose agent picks the model: the caller's, passed explicitly.
        model_name = _agent_model(request.agent_name, config, get_effective_user_id())
        system = AGENT_PROMPT.format(groups=", ".join(groups) or "(none)", skills=", ".join(skills) or "(none)")
        data = _json_object(await _ask(model_name, system, request.sentence, config))
        suggested_groups, suggested_skills = _names(data.get("tool_groups")), _names(data.get("skills"))
        dropped = [g for g in suggested_groups if g not in groups] + [s for s in suggested_skills if s not in skills]
        result = AgentDraft(
            display_name=_text(data.get("display_name"), 80),
            description=_text(data.get("description"), 300),
            instructions=_text(data.get("instructions"), 8_000),
            tool_groups=[g for g in suggested_groups if g in groups],
            skills=[s for s in suggested_skills if s in skills],
        )
        if not result.instructions:
            raise HTTPException(status_code=502, detail="The model returned no instructions. Try again or rephrase.")
        return DraftResponse(kind=kind, model=model_name, agent=result, dropped=dropped)

    model_name = _resolve_model_name(None, app_config=config)
    existing = ""
    if request.name or request.body:
        existing = f"The skill so far:\nName: {request.name or '(none)'}\n{request.body or ''}"
    data = _json_object(await _ask(model_name, SKILL_PROMPT.format(existing=existing), request.sentence, config))
    result = SkillDraft(description=_text(data.get("description"), 600), body=_text(data.get("body"), 20_000))
    if not (result.description or result.body):
        raise HTTPException(status_code=502, detail="The model returned an empty draft. Try again or rephrase.")
    return DraftResponse(kind=kind, model=model_name, skill=result)
