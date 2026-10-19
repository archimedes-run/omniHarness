"""The policy inspector (Feature 004, US4). Read-only.

GET /api/policy/rules    the rules in force — including after a refused edit (FR-029)
GET /api/policy/explain  a tool's tier, the deciding rule, the default marker (FR-025..027)
GET /api/policy/audit    recent Tier 3 executions with plan and authoriser (FR-028)

The rules come from the same shared loader every agent's policy layer uses
(app.policy.registration.shared_loader), so the inspector describes what
dispatch is actually enforcing, not a fresh read of the file.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request

from app.gateway.authz import require_permission
from app.policy.inspect import RulesInForce, Tier3Execution, TierCheck, recent_tier3, rules_in_force, tier_check

router = APIRouter(prefix="/api/policy", tags=["policy"])


def _policy_config():
    from omniharness.config import get_app_config

    policy = getattr(get_app_config(), "policy", None)
    if policy is None or not policy.enabled:
        raise HTTPException(status_code=409, detail="the permission policy is disabled (policy.enabled: false)")
    return policy


@router.get("/rules", response_model=RulesInForce)
@require_permission("threads", "read")
async def policy_rules(request: Request) -> RulesInForce:
    from app.policy.registration import shared_loader

    return rules_in_force(shared_loader(_policy_config()))


@router.get("/explain", response_model=TierCheck)
@require_permission("threads", "read")
async def policy_explain(request: Request, tool: str = Query(..., min_length=1), args: str = Query(default="{}")) -> TierCheck:
    from app.policy.registration import shared_loader

    try:
        arguments = json.loads(args)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"args must be a JSON object: {exc}") from exc
    if not isinstance(arguments, dict):
        raise HTTPException(status_code=422, detail="args must be a JSON object")
    return tier_check(tool, arguments, shared_loader(_policy_config()).load(notify=False))


@router.get("/audit", response_model=list[Tier3Execution])
@require_permission("threads", "read")
async def policy_audit(request: Request) -> list[Tier3Execution]:
    from app.policy.audit import PolicyAuditLog

    policy = _policy_config()
    return recent_tier3(PolicyAuditLog(path=Path(policy.state_dir) / "audit.jsonl", actor="default").entries())
