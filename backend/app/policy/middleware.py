"""The policy layer, at the single tool-dispatch chokepoint (FR-001, FR-002).

An AgentMiddleware occupying `wrap_tool_call`. Four of five agent-construction
sites reach the shared middleware base, and the fifth is closed rather than
accommodated (FR-003) — a gate covering only the convergent four would have its
scope boundary exactly where the bypass lives.

Refusal is expressed by NOT calling the handler and returning a result in its
place. That is what makes this a gate rather than a notification.

ARTICLE I, DELIBERATELY. Unlike Features 001 and 002 this component runs
in-process in the dispatch path rather than behind the gateway API. An
out-of-process check would have to decide what happens when it is unreachable,
and every answer is either "the gateway stops working when a sidecar is down" —
worse than the risk — or "proceed unchecked", which is not a gate. The coupling
IS the guarantee, and it is recorded in plan.md's Complexity Tracking rather
than hidden.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from langchain.agents.middleware import AgentMiddleware

from .classify import classify
from .config import ConfigLoader
from .disclose import DisclosureLedger
from .grants import GrantedCall
from .limits import describe_expiry
from .lineage import initiation_origin
from .models import Outcome, PendingAction, Tier, default_expiry
from .pending import PendingStore, targets_still_match
from .private_reads import TurnPrivacy, is_outbound, private_reads_in_turn
from .provenance import DISCLOSED, GRANTED, executed_as, new_write_id
from .targets import source_argument

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


#: A probe's answer (`_complete_confirmation(execute=False)`): this turn would
#: claim and run a confirmation. Never returned when executing.
_WOULD_RUN: Any = object()

#: One lock per (owner, thread), held while a Tier 3 call is checked against
#: that thread's open proposals and saved (PolicyMiddleware.
#: _require_confirmation). Per thread: other chats never wait on it.
_PROPOSING: dict[tuple[str, str], threading.Lock] = {}
_PROPOSING_GUARD = threading.Lock()


def _proposing(owner_id: Any, thread_id: Any) -> threading.Lock:
    key = (str(owner_id or ""), str(thread_id or ""))
    with _PROPOSING_GUARD:
        lock = _PROPOSING.get(key)
        if lock is None:
            lock = _PROPOSING[key] = threading.Lock()
        return lock


#: Tools of which one turn has at most ONE open card per agent: delegating
#: (eval E-2). Any other tool is held only on an exact repeat.
ONE_OPEN_CARD_PER_TURN = frozenset({"task"})


#: Per tool call: what the policy decided, for the per-run trace (spec 009
#: FR-080): {"tier", "outcome", "card_id"}. Stamped on the call's tool result
#: as display data (STEP_KEY); no decision ever reads it back.
_STEP: ContextVar[dict | None] = ContextVar("policy_step", default=None)


def _step() -> dict:
    """This call's step record, or a throwaway outside a tool call."""
    step = _STEP.get()
    return step if step is not None else {}


from omniharness.agents.turns import POLICY_STEP_MARKER as STEP_KEY  # noqa: E402


def _stamp_step(result: Any, step: dict) -> Any:
    if not step:
        return result
    messages = [result] if hasattr(result, "additional_kwargs") else list(((getattr(result, "update", None) or {}).get("messages") or []) if isinstance(getattr(result, "update", None), dict) else [])
    for message in messages:
        if getattr(message, "type", None) == "tool" and isinstance(getattr(message, "additional_kwargs", None), dict):
            message.additional_kwargs[STEP_KEY] = {"tier": step.get("tier"), "outcome": step.get("outcome") or "ran", **({"card_id": step["card_id"]} if step.get("card_id") else {})}
    return result


async def _off_loop(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a card's statement off the event loop, in this context.

    Stating a card checks a ledger plan with a DRY-RUN write transaction
    (LedgerService.validate), synchronously. On the run's event loop that
    waited for SQLite's write lock while the lock's holder (the run journal's
    async writer on the same database) needed that very loop to commit: the
    check timed out with "database is locked", fell back to proposing the plan
    unchecked, and an invalid plan reached a card and failed after the person
    confirmed it (eval T11, 2026-10-24 and 2026-10-26)."""
    import asyncio
    import contextvars
    import functools

    context = contextvars.copy_context()
    return await asyncio.get_running_loop().run_in_executor(None, functools.partial(context.run, fn, *args, **kwargs))


def _is_registered_write_todos(tool: Any) -> bool:
    """The checklist tool the harness's TodoMiddleware registers, by the
    identity of its function (never by name): its result echoes the call's own
    arguments (lineage.TRUSTED_TOOL_RESULTS)."""
    try:
        from langchain.agents.middleware import todo as todo_module
    except ImportError:  # pragma: no cover
        return False
    func = getattr(tool, "func", None)
    coroutine = getattr(tool, "coroutine", None)
    return bool(getattr(tool, "name", None) == "write_todos" and (func is getattr(todo_module, "_write_todos", object()) or coroutine is getattr(todo_module, "_awrite_todos", object())))


def canonical_arguments(arguments: Any) -> str:
    """A call's arguments as compared for "the same proposal": key order and
    spacing ignored, values exact."""
    import json

    return json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)


def duplicate_proposal_text(earlier: PendingAction) -> str:
    """What the model is told when its card for this call is already open."""
    return (
        f"Not proposed: a card for {earlier.tool_name} ({earlier.id}) is already waiting for the person to answer. "
        "Nothing new was proposed and nothing has run. "
        f"Do not propose {earlier.tool_name} again in this turn; end your turn now and let the person answer the card."
    )


@dataclass
class PolicyMiddleware(AgentMiddleware):
    """Classify, then act according to the tier.

    Tier 1  execute silently
    Tier 2  execute, and guarantee the reply discloses it
    Tier 3  do not execute; state the plan and wait
    """

    loader: ConfigLoader
    pending: PendingStore
    ledger: DisclosureLedger
    #: Resolves the specific items a call will affect, so a plan can name them
    #: rather than describing a category (FR-021, FR-029). Injected because
    #: target resolution is worker-specific.
    resolve_targets: Any = None
    #: Re-reads, AT CONFIRMATION, the items an action would act on now (FR-029).
    #: None re-resolves from the stored arguments with the same resolver the
    #: plan was stated with — which catches a changed resolver or a tampered
    #: record, and CANNOT see the world move: today's resolver reads arguments,
    #: not calendars. A live, per-tool resolver plugs in here; none exists yet,
    #: and that limit is stated rather than simulated.
    recheck_targets: Any = None
    audit: Any = None
    actor: str = "default"
    now: Any = _now
    #: Granted actions per scheduled run, durable and reserved atomically
    #: (grants.GrantRunCounts). None: no grant can be used (fails closed).
    grant_runs: Any = None

    def __post_init__(self) -> None:
        super().__init__()

    # -- the chokepoint ----------------------------------------------------

    def wrap_tool_call(self, request, handler):
        token = _STEP.set({})
        try:
            return _stamp_step(self._wrap_tool_call(request, handler), _step())
        finally:
            _STEP.reset(token)

    async def awrap_tool_call(self, request, handler):
        token = _STEP.set({})
        try:
            return _stamp_step(await self._awrap_tool_call(request, handler), _step())
        finally:
            _STEP.reset(token)

    def _wrap_tool_call(self, request, handler):
        from omniharness.agents.invitation import inviting_turn

        # Whatever tier it gets, a call runs without any pin its model wrote
        # (a pin is the server's: _check_ledger_plan).
        request = self._without_model_pins(request)
        decision = self._classify(request)
        _step()["tier"] = int(decision.tier) if not decision.refused else None
        if decision.refused:
            _step()["outcome"] = "refused"
            return self._refuse_unruled(request, decision)
        declined = self._declined_this_turn(request)
        if declined is not None:
            _step()["outcome"] = "refused"
            return declined

        if decision.tier is Tier.TIER_1:
            with inviting_turn(self._inviting_for(request)):
                return self._mark_trusted_ack(request, handler(request))

        if decision.tier is Tier.TIER_2:
            grant = self._scheduled_hold(request, decision)
            if grant is None:
                grant = self._chat_suggestion(request, decision)
            if isinstance(grant, str):
                return self._require_confirmation(request, decision, extra_note=grant)
            with inviting_turn(self._inviting_for(request)), executed_as(GRANTED if grant else DISCLOSED, new_write_id()) as call, self._reserved(grant, call):
                result = handler(request)
            self._mark_trusted_ack(request, result)
            if grant:
                self._record_grant_use(request, decision, grant, call.get("write_id"))
            else:
                self.ledger.record(
                    tool_name=decision.tool_name,
                    arguments=self._arguments(request),
                    result=result,
                )
            return result

        # Tier 3 always asks: a standing grant never skips a confirmation.
        return self._require_confirmation(request, decision)

    async def _awrap_tool_call(self, request, handler):
        # Any agent this call invites (the `task` tool) starts from this
        # call's provenance, not as the user (omniharness.agents.invitation).
        from omniharness.agents.invitation import inviting_turn

        request = self._without_model_pins(request)
        decision = self._classify(request)
        _step()["tier"] = int(decision.tier) if not decision.refused else None
        if decision.refused:
            _step()["outcome"] = "refused"
            return self._refuse_unruled(request, decision)
        declined = self._declined_this_turn(request)
        if declined is not None:
            _step()["outcome"] = "refused"
            return declined

        if decision.tier is Tier.TIER_1:
            with inviting_turn(self._inviting_for(request)):
                return self._mark_trusted_ack(request, await handler(request))

        if decision.tier is Tier.TIER_2:
            grant = self._scheduled_hold(request, decision)
            if grant is None:
                grant = self._chat_suggestion(request, decision)
            if isinstance(grant, str):
                return await _off_loop(self._require_confirmation, request, decision, extra_note=grant)
            with inviting_turn(self._inviting_for(request)), executed_as(GRANTED if grant else DISCLOSED, new_write_id()) as call, self._reserved(grant, call):
                result = await handler(request)
            self._mark_trusted_ack(request, result)
            if grant:
                self._record_grant_use(request, decision, grant, call.get("write_id"))
                return result
            # PASS THE TARGETS WHEN THEY WERE GENUINELY RESOLVED, and not
            # otherwise. `covered()` requires the reply to name every target,
            # so handing it the fallback — a repr of the whole call — makes
            # coverage unreachable and guarantees an append on every Tier 2
            # action forever. An unresolved scope is better represented as no
            # targets: the tool name alone then satisfies coverage, which is
            # what that branch was written for.
            arguments = self._arguments(request)
            resolved = tuple(self.resolve_targets(decision.tool_name, arguments)) if (self.resolve_targets and source_argument(arguments)) else ()
            self.ledger.record(tool_name=decision.tool_name, arguments=arguments, result=result, targets=resolved)
            return result

        # Tier 3 always asks: a standing grant never skips a confirmation.
        return await _off_loop(self._require_confirmation, request, decision)

    # -- standing grants (Feature 006, app/policy/grants.py) ----------------
    #
    # Checked HERE, on the Tier 2 path, so no caller can skip it. Tier 3 never
    # reaches it: it always asks. In a scheduled run nobody reads the reply as
    # it happens, so a grant-governed Tier 2 call (the routine ledger ops)
    # runs only under the agent's standing grant and within the run's cap;
    # otherwise it waits like a proposal. In chat a grant changes nothing.

    def _scheduled_hold(self, request, decision) -> GrantedCall | str | None:
        """None: run as an ordinary Tier 2 call. A GrantedCall: run under a
        grant, its actions already reserved against the run's cap. A str: do
        not run; wait, with this note."""
        from .grants import GRANT_CAP_PER_RUN, GrantedCall, action_count, covering_classes, governed_by_grants, granted_classes, has_tool_allowlist
        from .provenance import FIRING_KEY, is_synthetic_turn

        context = self._runtime_context(request) or {}
        if not is_synthetic_turn(context):
            return None
        agent = self._requester(request)
        grants_user = self._grants_user_id(context)
        if not governed_by_grants(decision.tool_name, allowlist_agent=has_tool_allowlist(grants_user, agent)):
            return None
        granted = granted_classes(grants_user, agent)
        arguments = self._arguments(request)
        used = covering_classes(decision, arguments, granted, self.loader.load()) if granted else None
        if used is None:
            return f"Nobody is there to ask in a scheduled run, and none of {agent}'s standing grants covers this, so it waits for you."
        run_key = str(context.get(FIRING_KEY) or "")
        if not run_key or self.grant_runs is None:
            logger.warning("policy: %s's standing grant covers %s, but the run's granted actions cannot be counted (firing id %r); it waits", agent, decision.tool_name, run_key)
            return "This scheduled run's granted actions can't be counted, so nothing runs on its own under a standing grant; this waits for you."
        actions = action_count(arguments)
        # Reserved HERE, before the call runs, in one atomic write: parallel
        # calls in the same step cannot take the run past the cap.
        total = self.grant_runs.reserve(run_key, actions, GRANT_CAP_PER_RUN)
        if total is None:
            done = self.grant_runs.used(run_key)
            logger.warning("policy: %s's standing grant covers %s (%d actions), but this run already took %d of %d; it waits", agent, decision.tool_name, actions, done, GRANT_CAP_PER_RUN)
            return f"This run already did {done} of the {GRANT_CAP_PER_RUN} things one run may do on its own under {agent}'s standing grants, and this call would do {actions} more, so it waits for you."
        return GrantedCall(classes=used, actions=actions, total=total, run_key=run_key)

    def _chat_suggestion(self, request, decision) -> str | None:
        """In chat, a routine ledger write (grant-governed Tier 2) runs on its
        own ONLY when it follows from the user's own message in this turn
        (005 FR-009 amendment, user decision 2026-10-20). One that content the
        agent read caused (a tool result, an email, a page, a subagent's
        output; feature 003's lineage, FR-006) is a SUGGESTION: it is stated
        on a card and runs only if the user confirms it there. None: run it."""
        from .grants import change_summaries, chat_governed, repeats_declined

        if not chat_governed(decision.tool_name):
            return None
        context = self._runtime_context(request) or {}
        if context.get("workflow_run_id"):
            # A workflow run is unattended like a scheduled one, but has no
            # grants or cap of its own: a routine write waits for the user.
            return "This workflow runs without you watching, so I did not make this change; it runs only if you confirm it here."
        origin, source, via = self._origin(request)
        if origin != "user":
            logger.info("policy: %s was suggested by %s (%s); it waits on its card", decision.tool_name, origin, source or via or "-")
            return "This is a suggestion: it came from something I read, not from your message, so I did not do it. It runs only if you confirm it here."
        # Per turn (user decision 2026-10-20): content an EARLIER turn read does
        # not taint this one. But a write the user declined in this chat stays
        # declined: the same write (same op, target and text, normalised) can
        # never run later as if the user had asked for it.
        resolve = self._project_resolver(request)
        resolve_task = self._task_resolver(request)
        wanted = change_summaries(self._arguments(request), resolve, resolve_task)
        for declined in self.pending.declined_in_thread(self._thread_id(request), self._owner_id(request)):
            if declined.tool_name == decision.tool_name and repeats_declined(wanted, change_summaries(declined.arguments, resolve, resolve_task, trust_pins=True)):
                logger.info("policy: %s matches a write declined earlier (%s); it waits on its card", decision.tool_name, declined.id)
                return "This is a suggestion: you declined this earlier in this chat, so I did not do it. It runs only if you confirm it here."
        return None

    def _project_resolver(self, request):
        """Names a project by its id, through the ledger's own lookup, so a
        project named by name and by id is one project. None outside the
        gateway (no ledger)."""
        from omniharness.runtime.ledger.controller import get_ledger_controller

        controller = get_ledger_controller()
        lookup = getattr(controller, "project_id", None)
        if lookup is None:
            return None
        user_id = self._user_id(self._runtime_context(request) or {})
        return lambda ref: lookup(user_id=user_id, project=str(ref))

    def _task_resolver(self, request):
        """A task as the ledger's own lookup resolves it (as ledger_apply
        would): its id and current values, so one task named by short id,
        title or part of its title is one task. None outside the gateway."""
        from omniharness.runtime.ledger.controller import get_ledger_controller

        lookup = getattr(get_ledger_controller(), "task", None)
        if lookup is None:
            return None
        user_id = self._user_id(self._runtime_context(request) or {})
        return lambda project, task: lookup(user_id=user_id, project=str(project) if project not in (None, "") else None, task=str(task))

    @contextmanager
    def _reserved(self, grant, call: dict):
        """Give a granted call's reservation back ONLY when the call
        demonstrably did not write: its write never committed (the ledger
        tool marks the commit, provenance.mark_committed), and it returned or
        raised an ordinary exception. A cancellation (or anything else not an
        Exception) may land after the commit, so it keeps the reservation:
        the count may run high, never low."""
        try:
            yield
        except Exception:
            if grant and not call.get("committed"):
                self.grant_runs.release(grant.run_key, grant.actions)
            raise
        if grant and not call.get("committed"):
            self.grant_runs.release(grant.run_key, grant.actions)

    def _record_grant_use(self, request, decision, grant: GrantedCall, write_id: str | None = None) -> None:
        from .lineage import initiation_origin, source_label

        context = self._runtime_context(request) or {}
        arguments = self._arguments(request)
        targets = list(self.resolve_targets(decision.tool_name, arguments)) if self.resolve_targets else [f"{decision.tool_name}({arguments})"]
        # What caused it, for the run's history: the schedule's own turn, or
        # content the agent read on the way (which still uses the grant).
        state = getattr(request, "state", None) or {}
        cause, source = initiation_origin(state.get("messages") if isinstance(state, dict) else None, synthetic=False)
        origin = "automation" if cause == "user" else cause
        if self.audit is not None:
            self.audit.record_grant_use(
                agent=self._requester(request),
                user_id=self._grants_user_id(context),
                tool=decision.tool_name,
                classes=grant.classes,
                targets=targets,
                thread_id=context.get("thread_id"),
                rule_id=context.get("trigger_rule_id"),
                origin=origin,
                origin_source=source,
                count_in_run=grant.total,
                firing_id=grant.run_key,
                write_id=write_id,
                source_label=source_label(state.get("messages") if isinstance(state, dict) else None),
                now=self.now(),
            )
        # Disclosed in the run's reply like a Tier 2 write: the person reading
        # it later sees what was done without them.
        self.ledger.record(tool_name=decision.tool_name, arguments=arguments, result=None, targets=tuple(targets))
        logger.info("policy: %s ran %s on its own under a standing grant (%s; %d actions, %d in this run; origin %s)", self._requester(request), decision.tool_name, ", ".join(grant.classes), grant.actions, grant.total, origin)

    @classmethod
    def _grants_user_id(cls, context: dict) -> str:
        """Whose standing grants this scheduled run reads: the install owner's
        (services.start_run sets the key on the engine's granted request only;
        a request can never supply it). Without it, the run's own user."""
        from .provenance import GRANTS_OWNER_KEY

        return str(context.get(GRANTS_OWNER_KEY) or cls._user_id(context))

    @staticmethod
    def _user_id(context: dict) -> str:
        from omniharness.runtime.user_context import get_effective_user_id

        return str(context.get("user_id") or get_effective_user_id())

    # -- internals ---------------------------------------------------------

    # ---- completing a confirmation --------------------------------------
    #
    # THE SEAM IS wrap_model_call, NOT before_model.
    #
    # Research R1 verified before_model can read the latest human turn and drive
    # recognise -> claim -> execute, and it can. Implementation found the thing
    # the probe did not need: executing a confirmed action requires the TOOL,
    # and before_model cannot reach one. Its signature is (state, runtime), and
    # Runtime carries context, store, stream_writer, previous, execution_info
    # and server_info — no tools. AgentMiddleware.tools is for CONTRIBUTING
    # tools to the agent, which is the opposite direction.
    #
    # ModelRequest carries `tools`. So the confirmation completes here, where
    # the registry is available on every model call rather than assembled from
    # whichever tools this worker happens to have dispatched before.
    #
    # It SHORT-CIRCUITS rather than letting the model narrate. The outcome of a
    # Tier 3 confirmation is a deterministic statement about what did or did not
    # happen; handing it to a model to phrase invites a fluent sentence that
    # does not match the audit log.

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        verdict, note = self._complete_confirmation(request)
        if verdict is not None:
            return verdict
        return self._guard_self_verdict(self._disclose(handler(self._offered(request, note))))

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        # OFF THE EVENT LOOP, AND ONLY WHAT RUNS. A typed "yes" runs the
        # confirmed call right here, and a confirmed `task` runs its whole
        # subagent; run inline, it froze the gateway's loop (every request)
        # until it finished (review of PR #58). So the flow is first PROBED
        # inline (execute=False: same gate, same recognition, nothing claimed
        # or run), which settles every turn that runs nothing: an ordinary
        # message, a decline, an unrecognised or card-only answer. Only a turn
        # that would claim and run a confirmation goes to the card path's pool,
        # in a per-user slot taken exactly as the card takes one, and there
        # runs the same flow again: same claim, same result. Sending every
        # person's turn to the pool made new chats wait while it was full
        # (#118).
        verdict, note = self._complete_confirmation(request, execute=False)
        if verdict is _WOULD_RUN:
            from langchain_core.messages import AIMessage

            from app.gateway.routers.confirmations import CONFIRM_BUSY, CONFIRM_BUSY_MESSAGE, run_in_a_slot

            user = str((self._runtime_context(request) or {}).get("user_id") or "default")
            started, outcome = await run_in_a_slot(user, self._complete_confirmation, request)
            if not started:
                logger.info("policy: confirmation resolved as %s (typed reply, no free slot)", CONFIRM_BUSY)
                return AIMessage(content=CONFIRM_BUSY_MESSAGE)
            verdict, note = outcome
        if verdict is not None:
            return verdict
        return self._guard_self_verdict(self._disclose(await handler(self._offered(request, note))))

    # ---- tools with no rule are not offered (007) -------------------------
    #
    # A tool no rule names is refused at dispatch (`_refuse_unruled`); it is
    # also kept OUT of the tool list the model sees, so the model does not plan
    # around a tool it cannot use. Connector tools load per user and per turn,
    # so this is also where their coverage is checked and logged.

    def _offered(self, request: Any, note: Any) -> Any:
        from .coverage import check

        changes: dict[str, Any] = {}
        if note:
            changes["messages"] = note
        tools = list(getattr(request, "tools", None) or [])
        named = [getattr(t, "name", None) for t in tools]
        if any(named):
            report = check([n for n in named if n], self.loader.load(notify=False), where="offered to the model")
            if report.unruled:
                unruled = set(report.unruled)
                changes["tools"] = [t for t in tools if getattr(t, "name", None) not in unruled]
        return request.override(**changes) if changes else request

    #: What the model is told when it repeats a call the person declined in
    #: this turn (spec 009 FR-058a). Nothing ran.
    DECLINED_REPEAT_TEXT = "Not run: the person declined this exact call earlier in this task. Do not try it again. Finish what you can without it, and say in your reply what was not done because of the decline."

    def _declined_this_turn(self, request: Any) -> Any:
        """A call identical (tool + canonical arguments) to one the person
        DECLINED in this same turn is refused, whatever its tier (FR-058a): a
        resume after a decline never makes the declined call again. Only a
        refusal, never a run: this check can only stop calls.

        Checked in a run resumed after a confirmation (the only way a decline
        and a later call share a turn: the card ends the run that raised it),
        so an ordinary call does not read the pending store."""
        from omniharness.agents.called_agents import RESUME_ACTION_KEY

        context = self._runtime_context(request) or {}
        if not isinstance(context.get(RESUME_ACTION_KEY), dict):
            return None
        thread_id = self._thread_id(request)
        if not thread_id:
            return None
        name = self._tool_name(request)
        declined = [a for a in self.pending.declined_in_thread(thread_id, self._owner_id(request)) if a.tool_name == name]
        if not declined:
            return None
        turn_key = self._private_read(request).turn_key
        if not turn_key:
            return None
        wanted = canonical_arguments(self._arguments(request))
        for action in declined:
            if action.group_key == turn_key and canonical_arguments(action.arguments) == wanted:
                logger.info("policy: %s repeats declined action %s in the same turn; refused", name, action.id)
                return self._as_tool_result(request, self.DECLINED_REPEAT_TEXT)
        return None

    def _refuse_unruled(self, request: Any, decision: Any) -> Any:
        from .coverage import refusal_text

        logger.warning("policy: refused %s — no policy rule covers it", decision.tool_name)
        return self._as_tool_result(request, refusal_text(decision.tool_name))

    # ---- the assistant never answers for the user -------------------------
    #
    # A model shown a pending action repeats "yes 7bf9d7ecb3b1" as its own
    # message (seen live). It confirms nothing (only a user turn can), but to
    # the person reading it looks as if the assistant approved on their behalf.
    # So a line of the reply a user reads that IS a verdict on a known action
    # is replaced, deterministically, with what is actually true.

    def _guard_self_verdict(self, response: Any) -> Any:
        message = self._final_message(response)
        if message is None:
            return response
        content = message.content
        if isinstance(content, str):
            message.content = self._without_self_verdicts(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    block["text"] = self._without_self_verdicts(block["text"])
        return response

    def _without_self_verdicts(self, text: str) -> str:
        from .confirm import self_verdict_id

        lines = text.split("\n")
        changed = False
        for index, line in enumerate(lines):
            action_id = self_verdict_id(line)
            action = self.pending.get(action_id) if action_id else None
            if action is None:
                continue
            changed = True
            if action.confirmable_by_typing:
                lines[index] = f"Waiting for you: confirm action `{action.id}` on the card, or reply yes."
            else:
                lines[index] = f"Waiting for you: confirm action `{action.id}` with the button on its card."
            logger.warning("policy: the model wrote a verdict on %s as its own reply; replaced", action.id)
        return "\n".join(lines) if changed else text

    # ---- Tier 2 disclosure ------------------------------------------------
    #
    # `DisclosureLedger.apply()` had NO PRODUCTION CALLER. The middleware
    # recorded every Tier 2 execution into the ledger and nothing ever read it
    # back, so Tier 2 was execute-and-say-nothing — Tier 1 with bookkeeping —
    # while this class's own docstring promised "execute, and guarantee the
    # reply discloses it". Found by a user running a write and seeing no
    # mention of it.
    #
    # APPLIED TO THE MESSAGE WITH NO TOOL CALLS, and only that one. That is the
    # reply a person actually reads; an intermediate step in the tool loop is
    # not. `apply` does not consume records, so disclosing on every call would
    # repeat each line once per model round trip.

    def _disclose(self, response: Any) -> Any:
        if not self.ledger.records:
            return response
        message = self._final_message(response)
        if message is None:
            return response  # still mid-loop; the user has not been spoken to yet

        disclosed = self.ledger.apply(str(message.content or ""))
        if disclosed != message.content:
            message.content = disclosed
        self.ledger.clear()
        return response

    @staticmethod
    def _final_message(response: Any) -> Any:
        """The assistant turn a user reads, or None while tools are still running."""
        from langchain_core.messages import AIMessage

        candidates = getattr(response, "result", None)
        if isinstance(response, AIMessage):
            candidates = [response]
        for message in reversed(list(candidates or [])):
            if isinstance(message, AIMessage):
                return None if getattr(message, "tool_calls", None) else message
        return None

    def _may_answer(self, request: Any) -> bool:
        from . import confirm_flow

        messages = list(getattr(request, "messages", None) or [])
        # ONE GATE (confirm_flow.turn_may_answer): only the person's own,
        # just-arrived, server-tagged turn is ever read as a yes/no. Not a
        # subagent's, not a turn handed to an agent ("@member", Continue), not
        # a scheduled one, not a tool result or an agent's reply.
        return bool(messages) and confirm_flow.turn_may_answer(messages[-1], self._runtime_context(request))

    def _complete_confirmation(self, request: Any, *, execute: bool = True) -> tuple[Any, Any]:
        from langchain_core.messages import AIMessage

        from . import confirm_flow
        from .confirm_flow import ConfirmationFlow

        messages = list(getattr(request, "messages", None) or [])
        if not self._may_answer(request):
            return None, None

        flow = ConfirmationFlow(store=self.pending, middleware=self, now=self.now)
        result = flow.from_message(
            messages[-1],
            run_tool=self._runner(request),
            runtime_context=self._runtime_context(request),
            execute=execute,
        )
        if result.outcome == confirm_flow.WOULD_EXECUTE:
            # Only from a probe: nothing was claimed or run (awrap_model_call).
            return _WOULD_RUN, None
        note = None
        if result.expired_meanwhile:
            # FR-038: expiry TELLS the user rather than producing silence. It is
            # appended rather than short-circuited, because swallowing the turn
            # to deliver it would lose whatever the user actually asked.
            # The wording is limits.describe_expiry (FR-023): which tool, when,
            # and that nothing changed.
            said = " ".join(describe_expiry(a) for a in result.expired_meanwhile)
            note = [*messages, AIMessage(content=f"({said})")]

        if result.outcome == confirm_flow.NO_VERDICT:
            return None, note

        logger.info("policy: confirmation resolved as %s (%s)", result.outcome, result.action_id)
        if result.outcome == confirm_flow.EXECUTED and result.action_id:
            action = self.pending.get(result.action_id)
            if action is not None and action.surface:
                # Posted in the thread, attributed to the agent that proposed
                # it, with the result; an invited agent's says it stopped.
                from .surface_run import report_message

                return report_message(action, result.detail.get("result")), None
        return AIMessage(content=result.message), None

    @staticmethod
    def _runner(request: Any) -> Callable[[str, dict], Any]:
        registry = {}
        for tool in getattr(request, "tools", None) or []:
            name = getattr(tool, "name", None)
            if name:
                registry[name] = tool

        runtime = getattr(request, "runtime", None)
        state = getattr(request, "state", None)

        def run(tool_name: str, arguments: dict) -> Any:
            from omniharness.agents.tool_surface import LEAD

            from .surface_run import confirming_action, invoke, run_on_surface

            action = confirming_action()
            if action is not None and action.surface:
                # A call a SUBAGENT proposed runs with the subagent's tools,
                # rebuilt, never with the lead's live list: the subagent's own
                # tool is not on it (LookupError, AUDIT-2026-10 addendum). A
                # lead call takes its tool from the live list when it is on it,
                # which is the same surface, still assembled. Either way the
                # call runs with the PROPOSER's runtime (the live one has no run
                # config, which `task` reads).
                live = registry.get(tool_name) if action.surface.get("kind") == LEAD else None
                return run_on_surface(action, tool_name, arguments, state=state, live_tool=live, selection=selection, snapshot=snapshot)
            tool = registry.get(tool_name)
            if tool is None:
                # Loud, not silent. A confirmation that cannot execute must say
                # so; the failure this whole phase closes was a quiet one.
                raise LookupError(f"tool {tool_name!r} is not available on this worker, so the confirmation cannot be completed")
            return invoke(tool, arguments, runtime=runtime, state=state, call_id=f"confirmed-{action.id if action else tool_name}")

        # The chat's CURRENT selection, loaded by the gateway at this run's start.
        context = getattr(runtime, "context", None) or {}
        raw = context.get("selected_sources") if isinstance(context, dict) else None
        selection = list(raw) if isinstance(raw, (list, tuple, set)) else None
        from .surface_run import SurfaceSnapshot

        # The proposer's tools, built once: checked and run from the same list.
        snapshot = SurfaceSnapshot(selection)

        def unavailable(action: Any) -> str | None:
            from omniharness.agents.tool_surface import LEAD

            from .surface_run import unavailable_reason

            if (not action.surface or action.surface.get("kind") == LEAD) and action.tool_name in registry:
                return None  # on the lead's live list, assembled from the chat's selection now
            return unavailable_reason(action, selection, snapshot=snapshot)

        run.unavailable = unavailable  # type: ignore[attr-defined]
        return run

    @staticmethod
    def _runtime_context(request: Any) -> dict | None:
        runtime = getattr(request, "runtime", None)
        return dict(getattr(runtime, "context", None) or {}) if runtime is not None else None

    def _classify(self, request):
        # The same origin a Tier 3 card states (`_origin`, lineage +
        # provenance + invitation): anything but the user's own message means
        # content, an automation, or an unknown cause led to this call.
        after_content = self._origin(request)[0] != "user"
        ruleset = self.loader.load()
        name = self._tool_name(request)
        # Outbound tools (an `after_private_read` exception) escalate only once
        # a private read happened in this turn (private_reads.py). Walked only
        # for them: no other rule reads it.
        private_read = is_outbound(name, ruleset) and self._private_read(request, ruleset).private
        return classify(name, self._arguments(request), ruleset, after_content=after_content, private_read=private_read)

    def _private_read(self, request, ruleset=None) -> TurnPrivacy:
        """Did a tool that reads the person's private data return data in
        this turn? From the run's own messages (private_reads.py), ORed with
        what the walk cannot see, each server-owned and each "private" when
        absent: an automation's turn; for an invited agent, its inviting
        turn; for a run resumed after a confirmation, the confirmed calls'
        turn. Nothing a request carries can clear it."""
        from omniharness.agents.called_agents import RESUME_ACTION_KEY
        from omniharness.agents.invitation import INVITED_PRIVATE_KEY

        from .provenance import is_synthetic_turn

        ruleset = ruleset if ruleset is not None else self.loader.load()
        context = self._runtime_context(request) or {}
        state = getattr(request, "state", None) or {}
        messages = state.get("messages") if isinstance(state, dict) else None
        walked = private_reads_in_turn(messages, ruleset)
        inherited: list[str] = []
        if is_synthetic_turn(context):
            inherited.append("an automation's turn")
        if self._is_invited(request) and context.get(INVITED_PRIVATE_KEY, True) is not False:
            inherited.append("the turn that invited this agent")
        resume = context.get(RESUME_ACTION_KEY)
        if isinstance(resume, dict) and resume.get("private_read", True) is not False:
            inherited.append("the turn the confirmed calls came from")
        if not inherited:
            return walked
        return TurnPrivacy(private=True, sources=(*inherited, *walked.sources), turn_key=walked.turn_key)

    @staticmethod
    def _tool_name(request) -> str:
        call = getattr(request, "tool_call", None) or {}
        return call.get("name") or getattr(getattr(request, "tool", None), "name", "") or ""

    @staticmethod
    def _arguments(request) -> dict:
        call = getattr(request, "tool_call", None) or {}
        return call.get("args") or {}

    def _require_confirmation(self, request, decision, extra_note: str = ""):
        """Tier 3: state the plan, record it durably, and do not execute.

        FR-006, GLOBALLY: content the agent READ may SUGGEST an action but can
        never confirm it or originate it silently. The proposal is still made
        (refusing outright hid from the user what the content asked for), but
        it is marked with what caused it, and an action not caused by the
        user's own latest message can only be confirmed with the card's button.
        """
        origin, origin_source, origin_via = self._origin(request)
        arguments = self._arguments(request)
        checked = self._check_ledger_plan(request)
        if checked is not None:
            invalid, arguments = checked
            if invalid is not None:
                # A plan that could not be applied is never put on a card: the
                # user would approve it and then see it fail. It goes back to
                # the model as the tool's own result (nothing was proposed,
                # nothing written), so it can correct the plan or ask the user.
                logger.info("policy: %s plan refused before its card: %s", decision.tool_name, invalid)
                if origin != "user":
                    # Not the user's own request (content, an automation):
                    # nobody is watching the model's reply, so the attempt is
                    # recorded where Tier 3 history is read (FR-006).
                    self._record_refused_plan(request, decision, arguments, invalid, origin, origin_source)
                return self._mark_trusted_ack(request, self._as_tool_result(request, f"Nothing was proposed or changed: {invalid}."))

        if origin != "user":
            logger.warning("policy: %s was suggested by %s %s (via %s); it can only be confirmed on its card (FR-006)", decision.tool_name, origin, origin_source, origin_via or "-")

        tool_name = decision.tool_name
        targets = list(self.resolve_targets(tool_name, arguments)) if self.resolve_targets else [f"{tool_name}({arguments})"]
        ruleset = self.loader.load()
        now = self.now()
        # Recorded with the action (server-side), so a resume after it is
        # confirmed, or a rules reload judging it again, sees the turn it was
        # stated in, not whatever the thread holds later.
        privacy = self._private_read(request, ruleset)

        # NO CARD FLOOD (_open_duplicate). A model told "please confirm"
        # re-issued its delegation again and again in one turn, rephrased
        # (eval E-2: eight open cards). While this agent's delegation card is
        # open in this turn (or, for any tool, the same call's card), no card
        # is made and the model is told to end its turn. The check and the save
        # are one step, so calls dispatched together (one model step, parallel
        # tool calls) make one.
        with _proposing(self._owner_id(request), self._thread_id(request)):
            earlier = self._open_duplicate(request, tool_name, arguments, privacy.turn_key, now)
            if earlier is None:
                action = PendingAction(
                    plan_text="",
                    tool_name=tool_name,
                    arguments=arguments,
                    targets=targets,
                    tier_at_statement=decision.tier,
                    expires_at=default_expiry(now, ruleset.expires_after_seconds),
                    thread_id=self._thread_id(request),
                    requester=self._requester(request),
                    delegation_chain=self._delegation_chain(request),
                    origin=origin,
                    origin_source=origin_source,
                    origin_via=origin_via,
                    owner_id=self._owner_id(request),
                    surface=self._surface(request),
                    delegation_key=self._delegation_key(request),
                    run_markers=self._run_markers(request),
                    private_read=privacy.private,
                    outbound=is_outbound(tool_name, ruleset),
                    group_key=privacy.turn_key,
                )
                action.plan_text = self._plan_text_for(action)
                if extra_note:
                    action.plan_text = f"{action.plan_text}\n\n{extra_note}"
                self.pending.save(action)
        if earlier is not None:
            logger.info("policy: %s repeats open proposal %s; no new card", tool_name, earlier.id)
            return self._mark_trusted_ack(request, self._as_tool_result(request, duplicate_proposal_text(earlier)))
        logger.info("policy: %s requires confirmation (%s)", tool_name, action.id)
        _step().update({"outcome": "needs_confirmation", "card_id": action.id, "tier": int(action.tier_at_statement)})
        if self._is_invited(request):
            from omniharness.agents.invitation import STOPPED_AT_KEY

            context = getattr(getattr(request, "runtime", None), "context", None)
            if isinstance(context, dict):
                context.setdefault(STOPPED_AT_KEY, []).append({"id": action.id, "tool": tool_name})
        return self._mark_trusted_ack(request, self._as_tool_result(request, self._model_plan_text(action)))

    def _open_duplicate(self, request, tool_name: str, arguments: dict, turn_key: str, now: datetime) -> PendingAction | None:
        """The open card this call must not add to, or None.

        Only a card that is still open (unresolved, unclaimed, unexpired),
        proposed by the same agent (requester, delegation) for the same person
        in the same thread and the same turn, counts. Among those:

        - a DELEGATION (`ONE_OPEN_CARD_PER_TURN`): any open card for the tool
          holds it. Told "please confirm", the lead rephrased its delegation
          and re-issued it, and split it into others (eval E-2: eight cards in
          one turn, one an exact repeat). Delegating is one decision per turn
          for the person; the model is told to end its turn.
        - any other tool: only an exact repeat (same canonical arguments). A
          turn may rightly propose several different calls of one tool, each
          its own card: two emails, a group of ledger suggestions answered
          with "Apply all", a turn's outbound lookups (Feature 007).

        A later turn, or the same call once its card is answered or expired,
        makes a card as usual. A turn that cannot be identified never matches.
        """
        if not turn_key:
            return None
        wanted = canonical_arguments(arguments)
        any_call = tool_name in ONE_OPEN_CARD_PER_TURN
        thread_id, owner_id = self._thread_id(request), self._owner_id(request)
        requester, delegation_key = self._requester(request), self._delegation_key(request)
        for action in self.pending.open_in_thread(thread_id, now):
            if (
                action.tool_name == tool_name
                and action.group_key == turn_key
                and action.owner_id == owner_id
                and action.requester == requester
                and action.delegation_key == delegation_key
                and (any_call or canonical_arguments(action.arguments) == wanted)
            ):
                return action
        return None

    def _model_plan_text(self, action: PendingAction) -> str:
        """The plan as the MODEL is told it: for ledger_apply, the card's plan
        with each line rendered without stored text (confirm.model_safe_plan),
        since the result is a trusted acknowledgement
        (lineage.TRUSTED_TOOL_RESULTS). The card the person reads keeps them
        (action.plan_text, which already carries `extra_note`)."""
        from .confirm import model_safe_plan

        return model_safe_plan(action)[0]

    #: The outer turn a call belongs to, carried into every agent the turn
    #: invites (_inviting_for), so a refusal by a delegate and one by the lead
    #: in the same turn are one turn.
    TURN_KEY = "policy_turn_key"

    def _turn_key(self, request) -> str:
        """This call's OUTER turn: inherited from the inviting turn, else the
        run (one run is one turn), else the latest human message."""
        context = self._runtime_context(request) or {}
        if context.get(self.TURN_KEY):
            return str(context[self.TURN_KEY])
        if context.get("run_id"):
            return f"run:{context['run_id']}"
        state = getattr(request, "state", None) or {}
        messages = state.get("messages") if isinstance(state, dict) else None
        for index in range(len(messages or []) - 1, -1, -1):
            message = messages[index]
            if getattr(message, "type", None) == "human" or (isinstance(message, dict) and message.get("type") == "human"):
                ident = message.get("id") if isinstance(message, dict) else getattr(message, "id", None)
                return str(ident or f"#{index}")
        return ""

    def _record_refused_plan(self, request, decision, arguments: dict, reason: str, origin: str, origin_source: str) -> None:
        if self.audit is None:
            return
        from app.ledger.service import render

        try:
            self.audit.record_refused(
                tool=decision.tool_name,
                targets=render((arguments or {}).get("changes")) if isinstance((arguments or {}).get("changes"), list) else [],
                reason=reason,
                owner_id=self._owner_id(request),
                thread_id=self._thread_id(request),
                requester=self._requester(request),
                origin=origin,
                origin_source=origin_source,
                turn_key=self._turn_key(request),
                now=self.now(),
            )
        except Exception:  # noqa: BLE001 — the refusal stands whether or not it was recorded
            logger.warning("policy: a refused %s plan could not be recorded", decision.tool_name, exc_info=True)

    @staticmethod
    def _is_ledger_apply(request) -> bool:
        from omniharness.tools.builtins.ledger_tool import ledger_apply_tool

        return getattr(request, "tool", None) is ledger_apply_tool

    def _without_model_pins(self, request):
        """The call with any pin (service.PIN_KEY) the MODEL wrote removed: a
        pin is the server's record of what a confirmed plan resolved to, and a
        call that runs now resolves its own names."""
        if not self._is_ledger_apply(request):
            return request
        from app.ledger.service import strip_pins

        call = getattr(request, "tool_call", None) or {}
        args = dict(call.get("args") or {})
        if "changes" not in args:
            return request
        args["changes"] = strip_pins(args["changes"])
        return request.override(tool_call={**call, "args": args})

    def _check_ledger_plan(self, request) -> tuple[str | None, dict] | None:
        """For the registered built-in ledger_apply (by object identity, as
        _mark_trusted_ack: an outside tool of that name is never resolved
        through the ledger), check the plan this request would put on a card,
        WITHOUT writing (LedgerService.validate).

        None: not ledger_apply. Else (why it could not be applied or None, the
        arguments to state): any pin the model wrote is removed, and when the
        plan is valid each change is pinned (service.PIN_KEY) to what it
        resolved to, so the card names the exact task and project and the
        confirmed call acts on exactly those. A check that cannot run (no
        ledger, an unexpected error) states the unpinned plan as before: apply
        resolves and validates again.
        """
        if not self._is_ledger_apply(request):
            return None
        from app.ledger.service import PIN_KEY, strip_pins

        arguments = dict(self._arguments(request))
        changes = strip_pins(arguments.get("changes"))
        arguments["changes"] = changes
        from omniharness.runtime.ledger.controller import get_ledger_controller

        check = getattr(get_ledger_controller(), "check_plan", None)
        if check is None:
            return None, arguments
        context = self._runtime_context(request) or {}
        try:
            invalid, resolutions = check(user_id=self._user_id(context), changes=changes, thread_id=context.get("thread_id"))
        except Exception:  # noqa: BLE001 — advisory: the card is proposed as before
            logger.warning("policy: ledger_apply plan could not be checked before its card", exc_info=True)
            return None, arguments
        if invalid is None and isinstance(changes, list) and len(resolutions) == len(changes):
            arguments["changes"] = [{**c, PIN_KEY: r} if isinstance(c, dict) and r else c for c, r in zip(changes, resolutions, strict=True)]
        return invalid, arguments

    @staticmethod
    def _mark_trusted_ack(request, result: Any) -> Any:
        """Mark a tool result as the harness's own acknowledgement when, and
        only when, the tool dispatched IS a registered built-in whose results
        are trusted (lineage.TRUSTED_TOOL_RESULTS), by object identity: an
        outside tool with the same name is never marked."""
        from omniharness.tools.builtins.ledger_tool import ledger_apply_tool

        from .lineage import TRUSTED_ACK_MARKER

        tool = getattr(request, "tool", None)
        if tool is not ledger_apply_tool and not _is_registered_write_todos(tool):
            return result
        messages = [result] if hasattr(result, "additional_kwargs") else list(((getattr(result, "update", None) or {}).get("messages") or []) if isinstance(getattr(result, "update", None), dict) else [])
        for message in messages:
            if getattr(message, "type", None) == "tool" and isinstance(getattr(message, "additional_kwargs", None), dict):
                message.additional_kwargs[TRUSTED_ACK_MARKER] = True
        return result

    @staticmethod
    def _as_tool_result(request, text: str) -> Any:
        """The plan, as the TOOL RESULT of the call it answers.

        A bare string returned from wrap_tool_call is not normalised by the
        tool node: it reaches state as-is and `add_messages` coerces it to a
        HumanMessage. So the policy's own plan text sat in the thread as a
        USER TURN, and the next Tier 3 call after a page-caused proposal walked
        back to it and read as the user's request (found 2026-10-19 while
        applying FR-006 globally). A ToolMessage is what it is.
        """
        from langchain_core.messages import ToolMessage

        call = getattr(request, "tool_call", None) or {}
        call_id = call.get("id")
        if not call_id:
            return text  # no call to answer (a hand-built request); nothing to pair with
        return ToolMessage(content=text, tool_call_id=call_id, name=call.get("name") or None)

    def _plan_text_for(self, action: PendingAction) -> str:
        return self._plan_text(action.tool_name, action.targets, action.requester, action.delegation_chain, action.id, action.arguments, origin_note=action.origin_note())

    @staticmethod
    def _plan_text(tool_name: str, targets: list[str], requester: str = "lead_agent", delegation_chain: tuple[str, ...] = (), action_id: str | None = None, arguments: dict | None = None, origin_note: str = "") -> str:
        """FR-021: name the SPECIFIC items, not the category.

        "Delete some meetings" cannot be confirmed meaningfully — the user would
        be authorising a description, and confirming a description authorises
        whatever it later turns out to mean.
        """
        lines = []
        if requester and requester != "lead_agent":
            # FR-033: name the asker and how the request reached the user.
            via = " -> ".join(delegation_chain) if delegation_chain else requester
            lines.append(f"**{requester}**, a subagent I delegated to ({via}), is asking for permission.")
            lines.append("")
        # NAME THE ARGUMENT THE TARGETS CAME FROM. Which argument holds "the
        # things this acts on" is a GUESS — no schema marks it — so the plan
        # states what it guessed instead of presenting a scope as fact. When
        # nothing could be resolved it says that too, rather than implying a
        # specific list.
        source = source_argument(arguments) if arguments is not None else None
        provenance = f" (from `{source}`)" if source else ""
        lines.append(f"Before I do this, please confirm. I intend to use **{tool_name}** on exactly these {len(targets)} item(s){provenance}:")
        lines.append("")
        lines += [f"  - {target}" for target in targets]
        if origin_note:
            lines.append("")
            lines.append(origin_note)
        if action_id:
            # THE ID IS NOT DECORATION: with several pending, a reply has to
            # name one (`recognise` refuses to guess). But the instruction is
            # addressed to the USER and never spelled as "yes <id>": this text
            # is the tool result the MODEL reads, and a model shown that phrase
            # repeats it as its own message, which reads as the assistant
            # confirming (seen live, 2026-10-19). `_guard_self_verdict` is the
            # deterministic backstop.
            lines.append("")
            lines.append(f"Action `{action_id}`.")
            if origin_note:
                lines.append("Waiting for you: confirm with the button on its card. A typed reply cannot confirm this one.")
            else:
                lines.append("Waiting for you: confirm on the card, or reply yes.")
        return "\n".join(lines)

    def _origin(self, request) -> tuple[str, str, str]:
        """What caused this call: (origin, source, via).

        An INVITED agent (a subagent, an @-invited agent) has no user of its
        own: its first message is the instructions its inviter wrote. So where
        lineage finds "the user", an invited agent gets its inviter's origin
        instead (omniharness.agents.invitation). Content it read itself stays
        content. Either way provenance only degrades; an invited context with
        no origin recorded is "unknown", never "user".
        """
        from omniharness.agents.invitation import DELEGATION_CHAIN_KEY, INVITED_ORIGIN_KEY, INVITED_SOURCE_KEY, INVITED_VIA_KEY

        from .provenance import is_synthetic_turn

        context = self._runtime_context(request) or {}
        state = getattr(request, "state", None) or {}
        messages = state.get("messages") if isinstance(state, dict) else None
        own, source = initiation_origin(messages, synthetic=is_synthetic_turn(context))
        invited = INVITED_ORIGIN_KEY in context or bool(context.get(DELEGATION_CHAIN_KEY))
        if own == "invitation" and not invited:
            # An invitation message outside an invited context: can't tell.
            return "unknown", "", ""
        if not invited or own not in ("user", "invitation"):
            return own, source, ""
        inherited = context.get(INVITED_ORIGIN_KEY) or "unknown"
        if inherited == "user":
            return "user", "", ""
        return inherited, context.get(INVITED_SOURCE_KEY) or "", context.get(INVITED_VIA_KEY) or ""

    def _inviting(self, origin: str, source: str, via: str, requester: str, chain: tuple[str, ...], run_markers: tuple[tuple[str, str], ...] = (), private_read: bool = True) -> Any:
        """The mark an agent invited during this call starts from."""
        from omniharness.agents.invitation import TurnOrigin

        return TurnOrigin(origin=origin, source=source, chain=tuple(chain) or (requester,), via=via, run_markers=run_markers, private_read=private_read)

    def _inviting_for(self, request) -> Any:
        origin, source, via = self._origin(request)
        # An agent invited during a scheduled run is in that run: it gets the
        # run's markers, so its grant-governed Tier 2 calls need a grant and
        # count against the same cap (never treated as a chat with you).
        # It also starts from this turn's private reads: a delegate of a turn
        # that read the person's mail is in a turn that read their mail.
        markers = (*self._run_markers(request), (self.TURN_KEY, self._turn_key(request)))
        return self._inviting(origin, source, via, self._requester(request), self._delegation_chain(request), markers, private_read=self._private_read(request).private)

    def _run_markers(self, request) -> tuple[tuple[str, str], ...]:
        """The scheduled run's markers in this call's context, if any."""
        from .provenance import FIRING_KEY, GRANTS_OWNER_KEY, PROVENANCE_KEY, RULE_KEY

        context = self._runtime_context(request) or {}
        return tuple((k, str(context[k])) for k in (PROVENANCE_KEY, RULE_KEY, FIRING_KEY, GRANTS_OWNER_KEY) if context.get(k))

    def _is_invited(self, request) -> bool:
        from omniharness.agents.invitation import DELEGATION_CHAIN_KEY, INVITED_ORIGIN_KEY

        context = self._runtime_context(request) or {}
        return INVITED_ORIGIN_KEY in context or bool(context.get(DELEGATION_CHAIN_KEY))

    def _delegation_key(self, request) -> str:
        """The proposing delegation's own checkpoint key; empty for the lead."""
        from omniharness.agents.invitation import DELEGATION_KEY

        if not self._is_invited(request):
            return ""
        context = self._runtime_context(request) or {}
        key = context.get(DELEGATION_KEY)
        return key if isinstance(key, str) else ""

    @staticmethod
    def _surface(request) -> dict:
        """How the proposing run's tool list was built (plan.md §2.0)."""
        from omniharness.agents.tool_surface import surface_of

        context = getattr(getattr(request, "runtime", None), "context", None) or {}
        return surface_of(context)

    @staticmethod
    def _thread_id(request) -> str | None:
        context = getattr(getattr(request, "runtime", None), "context", None) or {}
        return context.get("thread_id")

    @staticmethod
    def _owner_id(request) -> str | None:
        """Whose run this is. ``user_id`` in run context is set by the server
        (services.apply_server_owned_context), never by a request body."""
        context = getattr(getattr(request, "runtime", None), "context", None) or {}
        owner = context.get("user_id")
        return str(owner) if owner else None

    @staticmethod
    def _requester(request) -> str:
        """Who asked. FR-031: a subagent's call is classified identically, so
        the requester is not always the lead agent."""
        context = getattr(getattr(request, "runtime", None), "context", None) or {}
        return context.get("invited_agent") or context.get("agent_name") or "lead_agent"

    @staticmethod
    def _delegation_chain(request) -> tuple[str, ...]:
        """How the request got here (FR-033).

        "Should I delete these four events?" means something different when a
        subagent the user never instructed by name is asking. The user is
        authorising an action by something they did not directly ask for, and
        should be able to see that.
        """
        context = getattr(getattr(request, "runtime", None), "context", None) or {}
        chain = context.get("delegation_chain") or ()
        return tuple(chain)

    # -- execution after confirmation --------------------------------------

    def targets_now(self, action: PendingAction) -> list[str]:
        """The items this action would act on if run now. See `recheck_targets`."""
        if self.recheck_targets is not None:
            return list(self.recheck_targets(action))
        if self.resolve_targets is not None:
            return list(self.resolve_targets(action.tool_name, action.arguments))
        return [f"{action.tool_name}({action.arguments})"]

    def execute_confirmed(self, action: PendingAction, run_tool) -> Any:
        """Run a confirmed action, re-checking its targets first (FR-029).

        The claim is taken by the caller; this is what happens after it wins.

        The re-check happens HERE, for every route, and a caller cannot supply
        it. It used to be a parameter: the web route passed the action's own
        recorded targets (comparing the record with itself), and chat passed
        None (skipping the check), so drift was detectable only in tests that
        injected a list (audit P-3).
        """
        current_targets = self.targets_now(action)
        if not targets_still_match(action, current_targets):
            self.pending.resolve(
                action,
                Outcome.TARGETS_DRIFTED,
                f"the {len(action.targets)} item(s) confirmed are no longer the {len(current_targets)} present",
            )
            return None

        # A confirmed `task` invites a subagent: it starts from what caused the
        # ACTION, not from the turn that confirmed it. Pressing Confirm on
        # "delegate this" approves the delegation, not whatever the delegate
        # is later asked to do, so the origin does not upgrade here.
        from omniharness.agents.invitation import inviting_turn

        from .surface_run import confirming

        # A confirmed `task` from a scheduled run invites its agent INTO that
        # run: the markers stated with the action travel on (review round 2).
        with inviting_turn(self._inviting(action.origin, action.origin_source, action.origin_via, action.requester, action.delegation_chain, tuple(action.run_markers), private_read=action.private_read)), confirming(action):
            result = run_tool(action.tool_name, action.arguments)
        from omniharness.tools.search_results import compact_tool_output

        from .surface_run import RESUME_EXCERPT, observed_result, result_report

        # A search's result, compact, as any agent reads one (Feature 007).
        result = compact_tool_output(action.tool_name, result)
        # What "Continue <agent>", or the lead resuming after a group of
        # outbound calls, hands the agent as observed context.
        action.result_excerpt = observed_result(result, limit=RESUME_EXCERPT)
        if getattr(run_tool, "posts_result", False) and action.thread_id and action.surface:
            # THE SAME WRITE AS EXECUTED. A card's result is posted into its
            # chat afterwards; recording "waiting" only then left a crash
            # window in which the call had run and nothing said its result
            # was still owed to the chat (review of PR #58).
            action.post_state = "waiting"
            action.post_content = result_report(action, result)
        self.pending.resolve(action, Outcome.EXECUTED)
        if self.audit is not None:
            self.audit.record_tier3(action=action, actor=self.actor, now=self.now())
        return result


def _with_injected(tool: Any, arguments: dict, runtime: Any, state: Any) -> dict:
    """Fill framework-injected parameters a stored argument dict cannot carry.

    A PendingAction records what the MODEL chose — path, content, and so on. It
    cannot record `runtime`, which the agent's own tool node injects and which is
    not JSON. Invoking with the stored arguments alone raised

        1 validation error for write_file
        runtime  Field required

    on a real gateway, AFTER the confirmation had been recognised and the claim
    taken. The gate worked; the execution did not.
    """
    from langchain.tools import ToolRuntime

    schema = getattr(tool, "args_schema", None)
    fields = set(getattr(schema, "model_fields", {}) or {})
    if "runtime" not in fields or runtime is None:
        return dict(arguments)
    # `tools`, `execution_info` and `server_info` carry defaults and are left
    # to them. The six without defaults are passed through from the live
    # runtime; mypy types three of them as non-optional while the runtime hands
    # back None for them in ordinary operation, so the values are widened here
    # rather than asserted — a cast would claim something that is not true.
    built = ToolRuntime(
        state=state,
        context=getattr(runtime, "context", None),
        config=cast("Any", getattr(runtime, "config", None)),
        stream_writer=cast("Any", getattr(runtime, "stream_writer", None)),
        tool_call_id=None,
        store=cast("Any", getattr(runtime, "store", None)),
    )
    return {**arguments, "runtime": built}
