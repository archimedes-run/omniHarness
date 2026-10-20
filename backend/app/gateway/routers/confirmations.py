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
import contextvars
import functools
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
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


class AwaitingPost(BaseModel):
    """A confirmed action whose result is not in its chat: "waiting" (it will
    be), "failed" (retries ran out) or "dropped" (the chat was deleted). The
    last two carry the result, so the card keeps it."""

    id: str
    thread_id: str | None = None
    tool_name: str
    requester: str
    #: Whose action it is; the list is filtered by it, as `actions` is.
    owner_id: str | None = None
    post_state: str = "waiting"
    #: The result as the chat would have shown it (already redacted), for a
    #: post that failed or whose chat is gone; empty while it is waiting.
    result: str = ""


class PendingListResponse(BaseModel):
    actions: list[PendingActionResponse]
    #: Results that ran and are waiting to be posted into their chat (the chat
    #: was replying, or the gateway restarted first). Shown, never hidden.
    awaiting_post: list[AwaitingPost] = Field(default_factory=list)
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


#: Where a confirmed call runs: its own pool, never the event loop's default
#: one. A confirmed `task` runs its subagent to the end before the route
#: returns, minutes perhaps, and the default pool also serves every
#: `asyncio.to_thread` in the gateway; a few confirmations must not starve it.
CONFIRM_WORKERS = 8
#: Confirmed calls one user may have running at once.
CONFIRMS_PER_USER = 4
_CONFIRM_POOL = ThreadPoolExecutor(max_workers=CONFIRM_WORKERS, thread_name_prefix="confirmed-action")


class _ConfirmSlots:
    """Admission to _CONFIRM_POOL: NEVER a queue.

    PER PROCESS. With several gateway workers, each has its own pool and its
    own slots, so one user's limit is CONFIRMS_PER_USER per worker. That is a
    limit on this process's threads, not a global rate limit; the claim (one
    execution per action) is what holds across workers.

    A slot is taken before a confirmed call is claimed and handed to the pool,
    and there are never more slots than workers, so a confirmation either
    starts at once or is refused at once with a reason ("confirm_busy",
    nothing has run, the card stays). Four long confirmations used to fill the
    pool and every later request, declines included, waited behind them
    (review of PR #58). Declines never come here at all.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_user: dict[str, int] = {}

    def take(self, user: str) -> bool:
        with self._lock:
            if sum(self._by_user.values()) >= CONFIRM_WORKERS or self._by_user.get(user, 0) >= CONFIRMS_PER_USER:
                return False
            self._by_user[user] = self._by_user.get(user, 0) + 1
            return True

    def give_back(self, user: str) -> None:
        with self._lock:
            left = self._by_user.get(user, 0) - 1
            if left > 0:
                self._by_user[user] = left
            else:
                self._by_user.pop(user, None)


_SLOTS = _ConfirmSlots()

#: Refused before the claim: too many confirmed calls are running. Nothing ran.
CONFIRM_BUSY = "confirm_busy"
#: Refused, and the card resolved: the chat it belongs to was deleted.
CHAT_DELETED = "chat_deleted"


async def _off_the_request_pool(fn: Any, /, *args: Any, **kwargs: Any) -> Any:
    """Run a confirmation in _CONFIRM_POOL, with this request's context."""
    context = contextvars.copy_context()
    return await asyncio.get_running_loop().run_in_executor(_CONFIRM_POOL, functools.partial(context.run, fn, *args, **kwargs))


def _response_detail(detail: dict[str, Any]) -> dict[str, Any]:
    """What the card is sent: the tool's result and any error, REDACTED.

    The result is the tool's output (an email, a page, a token it printed),
    so it passes the same redactor as every other read surface; one that fails
    redaction reads Withheld, never raw.
    """
    shown = dict(detail)
    for key in ("result", "error"):
        if key in shown and shown[key] is not None:
            text, withheld = for_display(shown[key] if isinstance(shown[key], str) else json.dumps(shown[key], default=str, ensure_ascii=False))
            shown[key] = "Withheld: this could not be safely redacted for display." if withheld else text
    return shown


#: Refused before the claim: the chat this action's result is posted into is
#: running a reply now. Nothing ran; the card stays.
THREAD_BUSY = "thread_busy"


async def _thread_running(request: Request, thread_id: str) -> bool:
    from app.gateway.deps import get_run_manager

    return await get_run_manager(request).thread_busy(thread_id)


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

    from app.policy.surface_run import SurfaceSnapshot

    tools = get_available_tools(selected_sources=sources, user_id=user_id, app_config=get_app_config())
    registry = {getattr(t, "name", ""): t for t in tools}
    # The proposer's tools, built once: checked and run from the same list.
    snapshot = SurfaceSnapshot(current)

    def run(tool_name: str, arguments: dict) -> Any:
        from app.policy.surface_run import confirming_action, run_on_surface

        action = confirming_action()
        if action is not None and action.surface:
            # The PROPOSING run's tools, rebuilt (plan.md §2.0). The thread's
            # selection alone has no `task` and none of a subagent's own tools,
            # so a confirmed delegation or subagent action failed here with
            # LookupError (AUDIT-2026-10 addendum).
            return run_on_surface(action, tool_name, arguments, selection=current, snapshot=snapshot)
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

        return unavailable_reason(action, current, snapshot=snapshot)

    run.unavailable = unavailable  # type: ignore[attr-defined]
    # The card's route posts a confirmed result into its chat afterwards, so
    # the flow records it "waiting" in the same write as EXECUTED.
    run.posts_result = True  # type: ignore[attr-defined]
    return run


WRITTEN, GONE, ERROR = "written", "gone", "error"

#: Transient post failures retried with backoff (seconds), then given up as
#: "failed" (shown on the card). A module value so tests can shorten it.
POST_RETRY_DELAYS: tuple[float, ...] = (1.0, 4.0, 15.0, 60.0)


async def _append_to_checkpoint(checkpointer: Any, thread_id: str, message: Any) -> str:
    """Append one message to a thread's latest checkpoint, then READ IT BACK.

    "written" only when the message is in the thread's latest checkpoint
    afterwards; "gone" when the thread has no checkpoint (deleted): permanent;
    "error" for anything else: transient, retried. IDEMPOTENT by the message's
    id: a post retried (after a restart) is never added twice.
    """
    from omniharness.utils.time import now_iso

    config: dict[str, Any] = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}

    def has_it(snapshot: Any) -> bool:
        stored = ((getattr(snapshot, "checkpoint", None) or {}).get("channel_values") or {}).get("messages") or []
        return any(getattr(m, "id", None) == message.id for m in stored)

    try:
        current = await checkpointer.aget_tuple(config)
        if current is None:
            return GONE
        if has_it(current):
            return WRITTEN
        checkpoint: dict[str, Any] = dict(getattr(current, "checkpoint", {}) or {})
        metadata: dict[str, Any] = dict(getattr(current, "metadata", {}) or {})
        values: dict[str, Any] = dict(checkpoint.get("channel_values", {}))
        values["messages"] = [*list(values.get("messages") or []), message]
        checkpoint["channel_values"] = values
        metadata.update({"updated_at": now_iso(), "source": "update", "step": metadata.get("step", 0) + 1})
        await checkpointer.aput({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}, checkpoint, metadata, {})
        return WRITTEN if has_it(await checkpointer.aget_tuple(config)) else ERROR
    except Exception:  # noqa: BLE001 — classified and reported to the caller
        logger.warning("could not post the confirmed result to thread %s", thread_id, exc_info=True)
        return ERROR


async def post_result(*, checkpointer: Any, run_manager: Any, store: Any, action: Any, message: Any) -> str:
    """Post a confirmed result into its thread.

    Returns "written", "queued" (a run holds the chat; written when it ends),
    "dropped" (the chat is gone: permanent, the result stays on the card),
    "retrying" (a transient failure; retried with backoff) or "failed" (the
    retries ran out; shown on the card).

    How a call confirmed from its CARD reaches the conversation: the card's
    route has no run to answer in, so the result is written into the thread,
    attributed to the agent that proposed it (plan.md §2.0).

    THROUGH THE RUN MANAGER, NEVER AROUND IT. A run holds the thread's state in
    memory and checkpoints it as it goes, so writing the checkpoint while one
    runs was overwritten by the run's next step and the result vanished from
    the chat (review of PR #58). The run manager writes it now if the thread is
    idle, with no run able to start meanwhile, or queues it until the run ends.

    DURABLE: the action is recorded "waiting" (with the report's text) in the
    same write as EXECUTED (PolicyMiddleware.execute_confirmed), and "posted"
    once it is read back. A post still waiting when the gateway stops is
    written at the next startup (drain_waiting_posts). Never "waiting" forever:
    a deleted chat drops it, and transient failures stop at a cap.
    """
    stored = store.get(action.id)
    if stored is None or stored.post_state != "waiting":
        store.set_post_state(action.id, "waiting", str(message.content))
    seen: dict[str, str] = {}

    async def write() -> bool:
        # ONE classification for every path: the direct write, a write queued
        # behind a run (drained when it ends) and the startup drain. A
        # transient failure in the drain used to be logged and left "waiting"
        # with no retry (review of PR #58).
        outcome = await _append_to_checkpoint(checkpointer, action.thread_id, message)
        if outcome == WRITTEN:
            store.set_post_state(action.id, "posted")
            seen["state"] = "written"
        elif outcome == GONE:
            store.set_post_state(action.id, "dropped")
            seen["state"] = "dropped"
        else:
            seen["state"] = _schedule_retry(checkpointer=checkpointer, run_manager=run_manager, store=store, action=action, message=message)
        return True

    state = await run_manager.write_when_idle(action.thread_id, write)
    if state == "queued":
        return "queued"
    if state == "elsewhere":
        # Another worker's run holds the chat: wait and try again. Not a
        # failure, so it does not count toward the retry cap; durable all the
        # same (the record says "waiting"; the startup drain also posts it).
        _schedule(ELSEWHERE_RETRY_DELAY, checkpointer=checkpointer, run_manager=run_manager, store=store, action=action, message=message)
        return "queued"
    return seen.get("state", "failed")


def _schedule_retry(*, checkpointer: Any, run_manager: Any, store: Any, action: Any, message: Any) -> str:
    """Count a transient failure; retry with backoff, or give up at the cap."""
    current = store.get(action.id)
    attempts = (current.post_attempts if current else 0) + 1
    if attempts > len(POST_RETRY_DELAYS):
        store.set_post_state(action.id, "failed", attempts=attempts)
        logger.warning("gave up posting the confirmed result %s after %d attempts", action.id, attempts - 1)
        return "failed"
    store.set_post_state(action.id, "waiting", attempts=attempts)
    _schedule(POST_RETRY_DELAYS[attempts - 1], checkpointer=checkpointer, run_manager=run_manager, store=store, action=action, message=message)
    return "retrying"


#: How long to wait before trying again when another worker's run holds the chat.
ELSEWHERE_RETRY_DELAY = 5.0


def _schedule(delay: float, **post: Any) -> None:
    async def again() -> None:
        await asyncio.sleep(delay)
        await post_result(**post)

    task = asyncio.get_running_loop().create_task(again())
    _RETRIES.add(task)
    task.add_done_callback(_RETRIES.discard)


#: Retry tasks in flight (held so they are not garbage collected).
_RETRIES: set[asyncio.Task] = set()


def install_continue_listener() -> None:
    """Wire the harness's Continue outcome to the pending store, and release
    any Continue left held by a stopped process (lifespan)."""
    from app.policy.registration import build
    from omniharness.agents.called_agents import set_resume_listener
    from omniharness.config import get_app_config

    def finished(action_id: str, succeeded: bool) -> None:
        middleware = build(get_app_config())
        if middleware is not None:
            middleware.pending.finish_continue(action_id, succeeded)

    set_resume_listener(finished)
    middleware = build(get_app_config())
    if middleware is not None:
        released = middleware.pending.recover_continues()
        if released:
            logger.info("Released %d Continue(s) left unfinished by a stopped process", len(released))


async def drain_waiting_posts(app: Any) -> int:
    """At gateway startup: post every confirmed result still waiting.

    Called from the lifespan. No run is in flight at startup, so each is
    written now (through the run manager all the same); one already in its
    thread (the gateway stopped after the write, before recording it) is only
    marked posted, never added twice. Returns how many were posted.
    """
    from app.gateway.ownership import owner_user_id
    from app.policy.registration import build
    from app.policy.surface_run import report_message
    from omniharness.config import get_app_config

    middleware = build(get_app_config())
    checkpointer = getattr(app.state, "checkpointer", None)
    run_manager = getattr(app.state, "run_manager", None)
    thread_store = getattr(app.state, "thread_store", None)
    if middleware is None or checkpointer is None or run_manager is None:
        return 0
    posted = 0
    for action in middleware.pending.awaiting_post():
        if not action.thread_id:
            continue
        # OWNERSHIP: a result is only ever written into a thread its action's
        # owner owns (the record could have been edited on disk). A record
        # with no owner predates owners: it is the owner account's, and is
        # posted only into a thread that account owns.
        if thread_store is not None and await thread_store.get(action.thread_id, user_id=None) is None:
            # The chat was deleted: permanent. The result stays on the card.
            middleware.pending.set_post_state(action.id, "dropped")
            continue
        owner = str(action.owner_id) if action.owner_id else await owner_user_id()
        if thread_store is not None and (owner is None or not await thread_store.check_access(action.thread_id, owner, require_existing=True)):
            logger.warning("a waiting result %s names a thread its owner does not own; not posted", action.id)
            continue
        message = report_message(action, None, content=action.post_content)
        outcome = await post_result(checkpointer=checkpointer, run_manager=run_manager, store=middleware.pending, action=action, message=message)
        if outcome == "written":
            posted += 1
        else:
            logger.warning("a confirmed result for thread %s was not posted at startup (%s)", action.thread_id, outcome)
    return posted


def _arguments_for_display(arguments: dict[str, Any]) -> dict[str, str]:
    shown: dict[str, str] = {}
    for key, value in (arguments or {}).items():
        text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
        safe, withheld = for_display(text)
        # The NAME is text the model wrote too; it passes the redactor as well.
        name, name_withheld = for_display(str(key))
        shown["Withheld" if name_withheld else name] = "Withheld" if withheld else safe
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


#: How long a result that could not be posted stays listed (after its card's expiry).
_KEEP_UNPOSTED = timedelta(days=1)


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
        waiting = [a for a in middleware.pending.awaiting_post(states=("waiting", "failed", "dropped")) if a.post_state == "waiting" or now < a.expires_at + _KEEP_UNPOSTED]
    except Exception as exc:  # noqa: BLE001 — FR-008: say we cannot tell
        logger.exception("the pending set could not be read")
        return PendingListResponse(actions=[], readable=False, error=str(exc))

    return PendingListResponse(
        actions=[_view(a, rules.threshold_targets) for a in actions],
        awaiting_post=[
            AwaitingPost(
                id=a.id,
                thread_id=a.thread_id,
                tool_name=a.tool_name,
                requester=a.requester,
                owner_id=a.owner_id,
                post_state=a.post_state,
                result="" if a.post_state == "waiting" else a.post_content,
            )
            for a in waiting
        ],
        readable=True,
    )


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
    result.awaiting_post = await filter_accessible(request, result.awaiting_post, lambda view: view.owner_id)
    return result


def _declines_run_nothing(tool_name: str, arguments: dict) -> Any:
    raise RuntimeError("a decline runs nothing")


async def _chat_gone(request: Request, action: Any) -> str | None:
    """Why this card's chat can no longer receive it, or None.

    RE-CHECKED AT CONFIRMATION (condition 3). A card whose chat was deleted
    still ran its call and then sat "waiting to post" into nothing (review of
    PR #58). The chat must exist (its row or its checkpoint) and be the
    caller's.
    """
    from app.gateway.deps import get_checkpointer, get_thread_store
    from app.gateway.ownership import require_thread_access

    if not action.thread_id:
        return None
    row = await get_thread_store(request).get(action.thread_id, user_id=None)
    if row is None:
        checkpoint = await get_checkpointer(request).aget_tuple({"configurable": {"thread_id": action.thread_id, "checkpoint_ns": ""}})
        if checkpoint is None:
            return "The chat this was proposed in has been deleted, so it was not run. Nothing has run."
    await require_thread_access(request, action.thread_id)
    return None


async def _resolve(request: Request, action_id: str, *, confirm: bool, body: ResolveRequest, via: str = "button") -> ResolveResponse:
    from app.gateway.authz import get_auth_context
    from app.gateway.ownership import require_access, require_person

    require_person(request)
    _, middleware, flow = _policy(request)
    action = middleware.pending.get(action_id)
    if action is not None:
        await require_access(request, action.owner_id, what="Confirmation", ident=action_id)

    if not confirm:
        # DECLINES NEVER WAIT: no tool surface is built and no pool is used.
        # A decline is a claim and a file write; it takes the claim like a
        # confirmation, so one that arrives while the call runs says so.
        result = flow.explicit(action_id, confirm=False, run_tool=_declines_run_nothing, answered={"via": via, "thread_id": None, "user_id": _user_id(get_auth_context(request)), "message_id": None})
        return ResolveResponse(outcome=result.outcome, action_id=result.action_id, message=for_display(result.message)[0], detail=_response_detail(result.detail))

    ctx = get_auth_context(request)
    user_id = _user_id(ctx)

    if action is not None and action.outcome is None:
        gone = await _chat_gone(request, action)
        if gone:
            from app.policy.confirm_flow import take_claim
            from app.policy.models import Outcome

            claimed = take_claim(middleware.pending, action_id, "chat-deleted")
            if claimed is not None:
                middleware.pending.resolve(claimed, Outcome.DECLINED, gone)
            return ResolveResponse(outcome=CHAT_DELETED, action_id=action_id, message=gone)

    posts = action is not None and bool(action.thread_id) and bool(action.surface)
    if posts and action is not None and action.outcome is None and await _thread_running(request, action.thread_id or ""):
        # Its result is written into the chat, and the chat is mid-reply: the
        # run would overwrite it. Refused before the claim, so the card stays
        # and nothing has run.
        return ResolveResponse(
            outcome=THREAD_BUSY,
            action_id=action_id,
            message="This chat is still replying. Nothing has run. Confirm again when the reply has finished.",
        )

    if not _SLOTS.take(user_id):
        return ResolveResponse(
            outcome=CONFIRM_BUSY,
            action_id=action_id,
            message=f"{CONFIRMS_PER_USER} confirmed actions are already running, so this one has not started. Nothing has run. Confirm again when one finishes.",
        )
    from app.gateway.deps import get_checkpointer, get_run_manager

    # Only a result that is posted into a chat needs the thread's stores.
    checkpointer, run_manager = (get_checkpointer(request), get_run_manager(request)) if posts else (None, None)
    try:
        run_tool = await _runner(request, action.thread_id if action else None, user_id)
    except BaseException:
        _SLOTS.give_back(user_id)
        raise
    # SHIELDED: the confirmation, its slot and its post are one detached task.
    # A client that disconnects cancels only its wait: the confirmed call keeps
    # its slot until the pool thread finishes, and its result is still posted.
    work = asyncio.get_running_loop().create_task(
        _confirm_and_post(middleware, flow, action, action_id, run_tool, body.typed_count, user_id, checkpointer, run_manager, via),
    )
    _CONFIRMING.add(work)
    work.add_done_callback(_CONFIRMING.discard)
    return await asyncio.shield(work)


#: Confirmations in flight (held so a disconnected request's task finishes).
_CONFIRMING: set[asyncio.Task] = set()


async def _confirm_and_post(middleware: Any, flow: Any, action: Any, action_id: str, run_tool: Any, typed_count: int | None, user_id: str, checkpointer: Any, run_manager: Any, via: str = "button") -> ResolveResponse:
    try:
        # No targets passed: the flow re-checks them itself (FR-029).
        # OFF THE EVENT LOOP AND OFF THE DEFAULT POOL: a confirmed delegation
        # runs its subagent to the end before the flow returns. A slot was
        # taken, so the pool always has a free worker: this never queues.
        answered = {"via": via, "thread_id": None, "user_id": user_id, "message_id": None}
        result = await _off_the_request_pool(flow.explicit, action_id, confirm=True, run_tool=run_tool, supplied_count=typed_count, answered=answered)
    finally:
        _SLOTS.give_back(user_id)

    detail = _response_detail(result.detail)
    message = for_display(result.message)[0]
    if result.outcome == "executed" and action is not None and action.thread_id and action.surface:
        from app.policy.surface_run import report_message

        # The report as recorded with EXECUTED (already redacted).
        stored = middleware.pending.get(action_id)
        report = report_message(action, result.detail.get("result"), content=stored.post_content if stored and stored.post_content else None)
        message = str(report.content)
        detail["continue_agent"] = report.additional_kwargs["confirmation"]["continue_agent"]
        # FAILING SOURCES ARE VISIBLE: "posted" only when the thread was
        # written and read back; every other state says what happened.
        posted = await post_result(checkpointer=checkpointer, run_manager=run_manager, store=middleware.pending, action=action, message=report)
        detail["posted_to_thread"] = posted == "written"
        detail["post_queued"] = posted == "queued"
        detail["post_state"] = posted
        message += _POST_NOTES.get(posted, "")
    return ResolveResponse(outcome=result.outcome, action_id=result.action_id, message=message, detail=detail)


_POST_NOTES = {
    "queued": "\n\nThe chat was replying, so this will appear in it when that reply finishes.",
    "retrying": "\n\nThis could not be added to the chat yet; it will be tried again.",
    "failed": "\n\nThis could not be added to the chat; it is shown here only.",
    "dropped": "\n\nThe chat has been deleted, so this is shown here only.",
}


@router.post("/{action_id}/edit", response_model=ResolveResponse)
@require_permission("threads", "write")
async def edit_and_confirm(action_id: str, body: EditRequest, request: Request) -> ResolveResponse:
    """The user edits a stated plan and confirms the edited one (Feature 005 FR-010).

    The original is claimed and resolved SUPERSEDED, never run. The edit
    becomes a NEW pending action whose plan and targets are stated from the
    edited arguments by the same functions chat uses, and it is confirmed in
    the same step, THROUGH THE SAME PATH AS CONFIRM (_resolve): busy and
    deleted-chat refusals, the slot, and posting the result into the chat.
    Only tools in EDITABLE_TOOLS.
    """
    from app.gateway.ownership import require_access, require_person
    from app.policy.confirm_flow import take_claim
    from app.policy.models import Outcome, PendingAction, Tier, default_expiry

    require_person(request)
    _, middleware, _flow = _policy(request)
    now = datetime.now(UTC)
    action = middleware.pending.get(action_id)
    if action is not None:
        await require_access(request, action.owner_id, what="Confirmation", ident=action_id)
    if action is None or action.outcome is not None or action.is_expired(now):
        return ResolveResponse(outcome="already_resolved", action_id=action_id, message="That plan is no longer open, so it cannot be edited.")
    if action.tool_name not in EDITABLE_TOOLS:
        raise HTTPException(status_code=422, detail=f"{action.tool_name} plans cannot be edited here")
    if action.thread_id and action.surface and await _thread_running(request, action.thread_id):
        # Checked BEFORE the original is superseded, so a refused edit leaves it as it was.
        return ResolveResponse(outcome=THREAD_BUSY, action_id=action_id, message="This chat is still replying. Nothing has run and the plan is unchanged. Try again when the reply has finished.")
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
        # The SERVER's record of who proposed it, with what tools and in which
        # delegation, carried over; the edit changes the arguments only.
        surface=dict(action.surface),
        delegation_key=action.delegation_key,
    )
    edited.plan_text = middleware._plan_text_for(edited)
    middleware.pending.save(edited)
    middleware.pending.resolve(claimed, Outcome.SUPERSEDED, f"replaced by your edit ({edited.id}); the original was NOT run")

    response = await _resolve(request, edited.id, confirm=True, body=ResolveRequest(typed_count=body.typed_count), via="edit")
    response.detail = {**response.detail, "replaced": action_id}
    return response


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
