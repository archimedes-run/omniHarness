"""Surface 1 — pending Tier 3 confirmations (FR-001 … FR-009).

THIS ROUTER DECIDES NOTHING. Recognition, the scope threshold, the atomic claim
and execution all live in `app.policy.confirm_flow`, and this calls into it
through `explicit()`. The chat path calls the same object.

That is FR-004, and it is not a style preference: the claim is a one-shot file
link, and it is the only thing standing between two confirmation routes and one
action executing twice. `tests/gates/test_single_confirmation_path.py` asserts a
single production call site of `claim(`, so a second implementation here would
fail the build rather than ship.

WHY THE TOOL SURFACE IS REBUILT FROM THE THREAD. Executing a confirmed action
needs the tool, and an HTTP request has no agent to take one from. The pending
action records its `thread_id`, so the same selection that thread was using is
reassembled through `get_available_tools` — which also applies the FR-012 deny
filter, so a capability absent from the conversation stays absent here. Handing
this route a broader surface than the thread had would make the UI a way to run
what chat could not.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import get_thread_tool_selection_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/confirmations", tags=["confirmations"])


class PendingActionResponse(BaseModel):
    id: str
    tool_name: str
    plan_text: str
    targets: list[str]
    requester: str
    delegation_chain: list[str]
    expires_at: str
    thread_id: str | None = None
    #: Above this many targets a bare confirmation is not enough (FR-009).
    threshold_targets: int
    requires_typed_count: bool


class PendingListResponse(BaseModel):
    actions: list[PendingActionResponse]
    #: FR-008. `readable=False` means we could not tell what is pending, which
    #: is a different fact from nothing being pending. A UI that renders an
    #: empty list for both tells the user the opposite of the truth in one case.
    readable: bool = True
    error: str = ""


class ResolveRequest(BaseModel):
    #: Required above the threshold; the count of resolved targets (FR-009).
    typed_count: int | None = Field(default=None)


class ResolveResponse(BaseModel):
    #: One of the flow's outcomes, passed through verbatim. NEVER collapsed
    #: into ok/error: "someone else already confirmed it", "it expired" and
    #: "the items changed" need different responses from the person reading.
    outcome: str
    action_id: str | None = None
    message: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)


def _policy(request: Request):
    """The store, the middleware and the flow, built from app config."""
    from app.policy.confirm_flow import ConfirmationFlow
    from app.policy.registration import build
    from omniharness.config import get_app_config

    app_config = get_app_config()
    middleware = build(app_config)
    if middleware is None:
        # Disabled means no policy layer at all, so there is nothing pending by
        # construction — and saying so is not the same as an empty store.
        raise HTTPException(status_code=409, detail="the permission policy engine is disabled")
    flow = ConfirmationFlow(store=middleware.pending, middleware=middleware, now=lambda: datetime.now(UTC))
    return app_config, middleware, flow


async def _runner(request: Request, thread_id: str | None, user_id: str):
    """Rebuild the tool surface this action's THREAD was using."""
    from omniharness.config import get_app_config
    from omniharness.tools.tools import get_available_tools

    sources: set[str] = set()
    if thread_id:
        # Annotated because the dependency is generic; without it mypy cannot
        # infer the repo's type and the whole function goes unchecked.
        selection: Any = get_thread_tool_selection_repo(request)
        sources = set(await selection.get_sources(thread_id=thread_id))

    tools = get_available_tools(selected_sources=sources, user_id=user_id, app_config=get_app_config())
    registry = {getattr(t, "name", ""): t for t in tools}

    def run(tool_name: str, arguments: dict) -> Any:
        tool = registry.get(tool_name)
        if tool is None:
            # Loud. A confirmation that cannot execute must say why; the defect
            # this whole feature exists to close was a quiet one.
            raise LookupError(f"tool {tool_name!r} is not available to this thread, so the confirmation cannot be completed")
        return tool.invoke(arguments)

    return run


def _view(action, threshold: int) -> PendingActionResponse:
    return PendingActionResponse(
        id=action.id,
        tool_name=action.tool_name,
        plan_text=action.plan_text,
        targets=list(action.targets),
        requester=action.requester,
        delegation_chain=list(action.delegation_chain),
        expires_at=action.expires_at.isoformat(),
        thread_id=action.thread_id,
        threshold_targets=threshold,
        requires_typed_count=len(action.targets) > threshold,
    )


def read_pending(middleware, now: datetime) -> PendingListResponse:
    """The read, separated from the route so it can be tested directly.

    It used to live inline, and the test for it asserted the response MODEL's
    fields rather than this function's behaviour — so sabotaging the route to
    report `readable=True` unconditionally changed nothing and the suite stayed
    green. A test that cannot see the code it names is worse than none.
    """
    try:
        rules = middleware.loader.load()
        actions = middleware.pending.open_actions(now)
    except Exception as exc:  # noqa: BLE001 — FR-008: say we cannot tell
        logger.exception("the pending set could not be read")
        return PendingListResponse(actions=[], readable=False, error=str(exc))

    return PendingListResponse(actions=[_view(a, rules.threshold_targets) for a in actions], readable=True)


@router.get("", response_model=PendingListResponse)
@require_permission("threads", "read")
async def list_pending(request: Request) -> PendingListResponse:
    """Every open action, from every worker (FR-001).

    The store is a directory on shared state, so this sees actions created by
    any worker rather than only the one answering.
    """
    _, middleware, _flow = _policy(request)
    return read_pending(middleware, datetime.now(UTC))


async def _resolve(request: Request, action_id: str, *, confirm: bool, body: ResolveRequest) -> ResolveResponse:
    from app.gateway.authz import get_auth_context

    _, middleware, flow = _policy(request)
    action = middleware.pending.get(action_id)
    ctx = get_auth_context(request)
    user_id = getattr(ctx, "user_id", None) or "default"

    run_tool = await _runner(request, action.thread_id if action else None, user_id)
    current = list(action.targets) if action else None

    result = flow.explicit(
        action_id,
        confirm=confirm,
        run_tool=run_tool,
        supplied_count=body.typed_count,
        current_targets=current,
    )
    return ResolveResponse(outcome=result.outcome, action_id=result.action_id, message=result.message, detail=result.detail)


@router.post("/{action_id}/confirm", response_model=ResolveResponse)
@require_permission("threads", "write")
async def confirm(action_id: str, body: ResolveRequest, request: Request) -> ResolveResponse:
    return await _resolve(request, action_id, confirm=True, body=body)


@router.post("/{action_id}/decline", response_model=ResolveResponse)
@require_permission("threads", "write")
async def decline(action_id: str, body: ResolveRequest, request: Request) -> ResolveResponse:
    """FR-003: as available and as deterministic as confirming.

    Declining never consults the threshold. Proof of reading is required to ACT,
    not to refuse — making a decline harder than a confirmation would push a
    hesitant user toward the dangerous answer.
    """
    return await _resolve(request, action_id, confirm=False, body=body)
