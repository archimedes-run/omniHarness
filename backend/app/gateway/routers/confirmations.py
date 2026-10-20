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

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.gateway.authz import require_permission
from app.gateway.deps import get_thread_tool_selection_repo
from app.gateway.display_redaction import all_for_display, for_display

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
    #: The plan or a target failed redaction and is not shown (FR-031, SC-015).
    withheld: bool = False
    #: The call's arguments, for tools whose plan can be edited before it is
    #: confirmed (Feature 005: ledger_apply). Absent for every other tool, and
    #: absent when they failed redaction.
    arguments: dict[str, Any] | None = None
    #: What caused the proposal (FR-006): "user", "content", "automation" or
    #: "unknown". Anything but "user" can only be confirmed here, by button.
    origin: str = "user"
    #: For "content": the tool(s) whose output suggested it.
    origin_source: str = ""
    #: The sentence the card shows, e.g. "Suggested by content from web_fetch".
    origin_label: str = ""
    #: For a subagent's request: the agent the content reached it through.
    #: The full path is `delegation_chain`.
    origin_via: str = ""
    confirmable_by_typing: bool = True
    #: Whose run stated it (security baseline); the list is filtered by it.
    owner_id: str | None = None
    #: Every call's arguments, for the card to show one row each, each value
    #: as text that passed redaction ("Withheld" where it did not). Display
    #: only: a confirmation runs the STORED arguments, never these.
    arguments_display: dict[str, str] | None = None


class PendingListResponse(BaseModel):
    actions: list[PendingActionResponse]
    #: FR-008. `readable=False` means we could not tell what is pending, which
    #: is a different fact from nothing being pending. A UI that renders an
    #: empty list for both tells the user the opposite of the truth in one case.
    readable: bool = True
    error: str = ""


class ResolveRequest(BaseModel):
    #: NOTHING ELSE IS ACCEPTED. The call that runs is the one recorded when it
    #: was proposed, with the arguments the card shows; a request naming a
    #: tool, arguments or a tool surface is refused (422), not ignored.
    model_config = ConfigDict(extra="forbid")

    #: Required above the threshold; the count of resolved targets (FR-009).
    typed_count: int | None = Field(default=None)


class EditRequest(BaseModel):
    #: The full replacement arguments, as the edited card shows them.
    arguments: dict[str, Any]
    #: Required above the threshold, as for a confirmation (FR-009).
    typed_count: int | None = Field(default=None)


#: Tools whose stated plan the user may edit before confirming. The edit is a
#: new plan stated by the user's own hand, through this trusted channel.
EDITABLE_TOOLS = frozenset({"ledger_apply"})


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


def _user_id(ctx) -> str:
    """The confirming user's id. AuthContext carries it as `.user.id`; this
    read `ctx.user_id`, which does not exist, so every confirmation from the
    card ran its tool as "default" (found by the ledger, whose rows are owned
    by the user)."""
    user = getattr(ctx, "user", None)
    return str(user.id) if user is not None and getattr(user, "id", None) else "default"


async def _runner(request: Request, thread_id: str | None, user_id: str):
    """Rebuild the tool surface this action's THREAD was using."""
    from omniharness.config import get_app_config
    from omniharness.tools.tools import get_available_tools

    sources: set[str] = set()
    current: list[str] | None = None
    if thread_id:
        # Annotated because the dependency is generic; without it mypy cannot
        # infer the repo's type and the whole function goes unchecked.
        selection: Any = get_thread_tool_selection_repo(request)
        current = list(await selection.get_sources(thread_id=thread_id))
        sources = set(current)

    tools = get_available_tools(selected_sources=sources, user_id=user_id, app_config=get_app_config())
    registry = {getattr(t, "name", ""): t for t in tools}

    def run(tool_name: str, arguments: dict) -> Any:
        from app.policy.surface_run import confirming_action, run_on_surface

        action = confirming_action()
        if action is not None and action.surface:
            # The PROPOSING run's tools, rebuilt (plan.md §2.0). The thread's
            # selection alone has no `task` and none of a subagent's own tools,
            # so a confirmed delegation or subagent action failed here with
            # LookupError (AUDIT-2026-10 addendum).
            return run_on_surface(action, tool_name, arguments, selection=current)
        tool = registry.get(tool_name)
        if tool is None:
            # Loud. A confirmation that cannot execute must say why; the defect
            # this whole feature exists to close was a quiet one.
            raise LookupError(f"tool {tool_name!r} is not available to this thread, so the confirmation cannot be completed")
        # The thread and user the action belongs to reach a tool that reads
        # its runtime (the ledger tools do). Invoking with the stored arguments
        # alone failed validation for any such tool, after the claim had been
        # taken (the chat path already does this; see _with_injected).
        from types import SimpleNamespace

        from app.policy.surface_run import invoke

        runtime = SimpleNamespace(context={"thread_id": thread_id, "user_id": user_id}, config={}, stream_writer=None, store=None)
        return invoke(tool, arguments, runtime=runtime, state={}, call_id=f"confirmed-{tool_name}")

    def unavailable(action: Any) -> str | None:
        from app.policy.surface_run import unavailable_reason

        return unavailable_reason(action, current)

    run.unavailable = unavailable  # type: ignore[attr-defined]
    return run


async def post_to_thread(request: Request, thread_id: str, message: Any) -> bool:
    """Append one message to a thread's latest checkpoint. False if it could not.

    How a call confirmed from its CARD reaches the conversation: the card's
    route has no run to answer in, so the result is written into the thread,
    attributed to the agent that proposed it (plan.md §2.0). The same shape
    `POST /api/threads/{id}/state` writes.
    """
    from app.gateway.deps import get_checkpointer
    from omniharness.utils.time import now_iso

    checkpointer = get_checkpointer(request)
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    try:
        current = await checkpointer.aget_tuple(config)
        if current is None:
            return False
        checkpoint: dict[str, Any] = dict(getattr(current, "checkpoint", {}) or {})
        metadata: dict[str, Any] = dict(getattr(current, "metadata", {}) or {})
        values: dict[str, Any] = dict(checkpoint.get("channel_values", {}))
        values["messages"] = [*list(values.get("messages") or []), message]
        checkpoint["channel_values"] = values
        metadata.update({"updated_at": now_iso(), "source": "update", "step": metadata.get("step", 0) + 1})
        await checkpointer.aput({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}, checkpoint, metadata, {})
        return True
    except Exception:  # noqa: BLE001 — reported to the caller, which says so
        logger.exception("could not post the confirmed result to thread %s", thread_id)
        return False


def _arguments_for_display(arguments: dict[str, Any]) -> dict[str, str]:
    shown: dict[str, str] = {}
    for key, value in (arguments or {}).items():
        text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
        safe, withheld = for_display(text)
        shown[str(key)] = "Withheld" if withheld else safe
    return shown


def _view(action, threshold: int) -> PendingActionResponse:
    # The plan names what it acts on, often in the words of an email or a page.
    plan_text, plan_withheld = for_display(action.plan_text)
    targets, targets_withheld = all_for_display(list(action.targets))
    arguments = None
    if action.tool_name in EDITABLE_TOOLS:
        _, args_withheld = for_display(json.dumps(action.arguments, default=str))
        arguments = None if args_withheld else action.arguments
    return PendingActionResponse(
        id=action.id,
        tool_name=action.tool_name,
        plan_text=plan_text,
        targets=targets,
        requester=action.requester,
        delegation_chain=list(action.delegation_chain),
        expires_at=action.expires_at.isoformat(),
        thread_id=action.thread_id,
        threshold_targets=threshold,
        requires_typed_count=len(action.targets) > threshold,
        withheld=plan_withheld or targets_withheld,
        arguments=arguments,
        origin=action.origin,
        origin_source=action.origin_source,
        origin_label=action.origin_label(),
        origin_via=action.origin_via,
        confirmable_by_typing=action.confirmable_by_typing,
        owner_id=action.owner_id,
        arguments_display=_arguments_for_display(action.arguments),
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
    from app.gateway.ownership import filter_accessible

    _, middleware, _flow = _policy(request)
    result = read_pending(middleware, datetime.now(UTC))
    # Ownership: only the caller's own plans (and, for the owner, the system's).
    result.actions = await filter_accessible(request, result.actions, lambda view: view.owner_id)
    return result


async def _resolve(request: Request, action_id: str, *, confirm: bool, body: ResolveRequest) -> ResolveResponse:
    from app.gateway.authz import get_auth_context
    from app.gateway.ownership import require_access, require_person

    require_person(request)
    _, middleware, flow = _policy(request)
    action = middleware.pending.get(action_id)
    if action is not None:
        await require_access(request, action.owner_id, what="Confirmation", ident=action_id)
    ctx = get_auth_context(request)
    user_id = _user_id(ctx)

    run_tool = await _runner(request, action.thread_id if action else None, user_id)

    # No targets passed: the flow re-checks them itself (FR-029). This route
    # used to pass the action's own recorded targets, so the check compared the
    # record with itself and drift could never be detected here.
    # OFF THE EVENT LOOP: a confirmed delegation runs its subagent to the end
    # before the flow returns, and that must not stall every other request.
    answered = {"via": "button", "thread_id": None, "user_id": user_id, "message_id": None}
    result = await asyncio.to_thread(flow.explicit, action_id, confirm=confirm, run_tool=run_tool, supplied_count=body.typed_count, answered=answered)
    detail = dict(result.detail)
    message = result.message
    if result.outcome == "executed" and action is not None and action.thread_id and action.surface:
        from app.policy.surface_run import report_message

        report = report_message(action, detail.get("result"))
        message = str(report.content)
        detail["continue_agent"] = report.additional_kwargs["confirmation"]["continue_agent"]
        # FAILING SOURCES ARE VISIBLE: when the thread could not be written,
        # the card says so rather than implying the chat shows it.
        detail["posted_to_thread"] = await post_to_thread(request, action.thread_id, report)
    return ResolveResponse(outcome=result.outcome, action_id=result.action_id, message=message, detail=detail)


@router.post("/{action_id}/edit", response_model=ResolveResponse)
@require_permission("threads", "write")
async def edit_and_confirm(action_id: str, body: EditRequest, request: Request) -> ResolveResponse:
    """The user edits a stated plan and confirms the edited one (Feature 005 FR-010).

    The original is claimed and resolved SUPERSEDED, never run. The edit
    becomes a NEW pending action whose plan and targets are stated from the
    edited arguments by the same functions chat uses, and it is confirmed in
    the same step: the person who wrote the edit is the person confirming
    it, through this trusted channel. Only tools in EDITABLE_TOOLS.
    """
    from app.gateway.authz import get_auth_context
    from app.gateway.ownership import require_access, require_person
    from app.policy.confirm_flow import take_claim
    from app.policy.models import Outcome, PendingAction, Tier, default_expiry

    require_person(request)
    _, middleware, flow = _policy(request)
    now = datetime.now(UTC)
    action = middleware.pending.get(action_id)
    if action is not None:
        await require_access(request, action.owner_id, what="Confirmation", ident=action_id)
    if action is None or action.outcome is not None or action.is_expired(now):
        return ResolveResponse(outcome="already_resolved", action_id=action_id, message="That plan is no longer open, so it cannot be edited.")
    if action.tool_name not in EDITABLE_TOOLS:
        raise HTTPException(status_code=422, detail=f"{action.tool_name} plans cannot be edited here")
    claimed = take_claim(middleware.pending, action_id, "edit")
    if claimed is None:
        return ResolveResponse(outcome="already_resolved", action_id=action_id, message="Another route resolved that plan first.")

    arguments = body.arguments
    targets = list(middleware.resolve_targets(action.tool_name, arguments)) if middleware.resolve_targets else [f"{action.tool_name}({arguments})"]
    ruleset = middleware.loader.load()
    edited = PendingAction(
        plan_text="",
        tool_name=action.tool_name,
        arguments=arguments,
        targets=targets,
        tier_at_statement=Tier.TIER_3,
        expires_at=default_expiry(now, ruleset.expires_after_seconds),
        thread_id=action.thread_id,
        requester=action.requester,
        delegation_chain=action.delegation_chain,
        owner_id=action.owner_id,
        origin=action.origin,
        origin_source=action.origin_source,
        origin_via=action.origin_via,
        # The SERVER's record of who proposed it and with what tools, carried
        # over; the edit changes the arguments, never the proposer.
        surface=dict(action.surface),
    )
    edited.plan_text = middleware._plan_text_for(edited)
    middleware.pending.save(edited)
    middleware.pending.resolve(claimed, Outcome.SUPERSEDED, f"replaced by your edit ({edited.id}); the original was NOT run")

    ctx = get_auth_context(request)
    user_id = _user_id(ctx)
    run_tool = await _runner(request, edited.thread_id, user_id)
    answered = {"via": "edit", "thread_id": None, "user_id": user_id, "message_id": None}
    result = await asyncio.to_thread(flow.explicit, edited.id, confirm=True, run_tool=run_tool, supplied_count=body.typed_count, answered=answered)
    return ResolveResponse(outcome=result.outcome, action_id=result.action_id, message=result.message, detail={**result.detail, "replaced": action_id})


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
