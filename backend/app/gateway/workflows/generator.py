"""Workflow spec generator — Phase 1 Slice 4a.

Single constrained LLM call that turns an instruction_prompt into a validated
WorkflowSpec.  This is NOT a run — it creates no thread, sandbox, or lead-agent
invocation.  It is a planning utility that lives alongside executor.py.

Public API:
    WorkflowSpec        — the validated output schema (also used as the API response model)
    WorkflowSpecStep    — one ordered step within a spec
    WorkflowGenerationError — raised when the model fails after one retry
    generate_workflow_spec(instruction_prompt) -> WorkflowSpec
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from omniharness.models import create_chat_model

logger = logging.getLogger(__name__)

_GENERATION_TIMEOUT_SECONDS = 60.0

_SYSTEM_PROMPT = """
You are a workflow specification planner. Given a natural-language workflow instruction, produce a structured specification.

Return ONLY valid JSON matching this exact schema — no markdown fences, no explanation:
{
  "title": "Short descriptive title (≤80 chars)",
  "description": "1-3 sentences describing what this workflow does",
  "steps": [
    {
      "title": "Step title",
      "description": "What this step does and why",
      "suggested_tools": ["tool_name"]
    }
  ],
  "required_capabilities": ["capability_id"],
  "risks": ["Risk description"],
  "approval_policy": "draft_only"
}

Rules:
- steps: break the work into clear, ordered actions. Include at least one step.
- suggested_tools: plain tool-name strings (e.g. "bash", "read_file", "web_search"). Use [] if none.
- required_capabilities: short identifiers (e.g. "web_access", "shell_execution"). Use [] if none.
- risks: concrete operational risks. Use [] if there are none.
- approval_policy must be exactly one of: "draft_only", "approval_required", "execute_low_risk".
  Recommend "approval_required" for irreversible, credentialed, or external write actions.
  Recommend "execute_low_risk" for fully read-only or reversible local operations.
  Default to "draft_only" when uncertain.
  This is a stored recommendation only; it does not enforce anything automatically.
""".strip()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class WorkflowSpecStep(BaseModel):
    title: str
    description: str
    suggested_tools: list[str] = Field(default_factory=list)


class WorkflowSpec(BaseModel):
    title: str = Field(min_length=1)
    description: str
    steps: list[WorkflowSpecStep] = Field(min_length=1)
    required_capabilities: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    approval_policy: Literal["draft_only", "approval_required", "execute_low_risk"]


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------


class WorkflowGenerationError(Exception):
    """Raised when the LLM fails to produce a valid WorkflowSpec after one retry."""


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


async def generate_workflow_spec(instruction_prompt: str) -> WorkflowSpec:
    """Generate a validated WorkflowSpec from instruction_prompt.

    Uses the first configured model provider.  Retries the structured-output
    call once on any parse/validation failure.  Never creates a thread, run,
    or sandbox.

    Raises:
        WorkflowGenerationError: on timeout or persistent model output failure.
    """
    model = create_chat_model(thinking_enabled=False)
    structured_model = model.with_structured_output(WorkflowSpec)
    messages = [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=instruction_prompt)]

    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            result = await asyncio.wait_for(
                structured_model.ainvoke(messages, config={"run_name": "workflow_spec_generation"}),
                timeout=_GENERATION_TIMEOUT_SECONDS,
            )
            if not isinstance(result, WorkflowSpec):
                raise TypeError(f"Expected WorkflowSpec, got {type(result).__name__}")
            return result
        except TimeoutError as exc:
            raise WorkflowGenerationError(f"Workflow spec generation timed out after {_GENERATION_TIMEOUT_SECONDS:.0f}s") from exc
        except WorkflowGenerationError:
            raise
        except Exception as exc:
            last_exc = exc
            if attempt == 0:
                logger.warning(
                    "Workflow spec generation attempt 1 failed, retrying: %s: %s",
                    type(exc).__name__,
                    exc,
                )

    raise WorkflowGenerationError(f"Model returned invalid spec after 2 attempts: {type(last_exc).__name__}") from last_exc
