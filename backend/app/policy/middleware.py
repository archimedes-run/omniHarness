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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from langchain.agents.middleware import AgentMiddleware

from .classify import classify
from .config import ConfigLoader
from .disclose import DisclosureLedger
from .limits import describe_expiry
from .lineage import initiation_origin
from .models import Outcome, PendingAction, Tier, default_expiry
from .pending import PendingStore, targets_still_match
from .targets import source_argument

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


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

    def __post_init__(self) -> None:
        super().__init__()

    # -- the chokepoint ----------------------------------------------------

    def wrap_tool_call(self, request, handler):
        from omniharness.agents.invitation import inviting_turn

        decision = self._classify(request)
        if decision.refused:
            return self._refuse_unruled(request, decision)

        if decision.tier is Tier.TIER_1:
            with inviting_turn(self._inviting_for(request)):
                return handler(request)

        if decision.tier is Tier.TIER_2:
            with inviting_turn(self._inviting_for(request)):
                result = handler(request)
            self.ledger.record(
                tool_name=decision.tool_name,
                arguments=self._arguments(request),
                result=result,
            )
            return result

        return self._require_confirmation(request, decision)

    async def awrap_tool_call(self, request, handler):
        # Any agent this call invites (the `task` tool) starts from this
        # call's provenance, not as the user (omniharness.agents.invitation).
        from omniharness.agents.invitation import inviting_turn

        decision = self._classify(request)
        if decision.refused:
            return self._refuse_unruled(request, decision)

        if decision.tier is Tier.TIER_1:
            with inviting_turn(self._inviting_for(request)):
                return await handler(request)

        if decision.tier is Tier.TIER_2:
            with inviting_turn(self._inviting_for(request)):
                result = await handler(request)
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

        return self._require_confirmation(request, decision)

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
        verdict, note = self._complete_confirmation(request)
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

    def _may_answer_a_card(self, request: Any, messages: list) -> bool:
        """THE ONE PLACE that decides whether this turn is read as a yes/no.

        Every exclusion lives here, so the next one (same thread, same owner,
        user turns only) is added in one function, not threaded through
        `_complete_confirmation`.
        """
        from langchain_core.messages import HumanMessage

        if not messages or not isinstance(messages[-1], HumanMessage):
            # ONLY a turn that has just arrived can be a verdict. Without this,
            # the same human turn that PROVOKED the proposal is re-read as an
            # answer to it on the next loop, and every Tier 3 proposal is
            # immediately met with "I did not recognise that".
            return False
        if self._is_invited(request):
            # AN INVITED AGENT HAS NO USER. Its first message is the
            # instructions its inviter wrote (omniharness.agents.invitation), so
            # reading it as a verdict let "Wipe the backup" answer whatever was
            # pending in the chat: a restated plan replaced the subagent's whole
            # run (found 2026-10-20, test_delegated_confirmation.py). Only the
            # user, in the lead's chat or on the card, answers a confirmation.
            return False
        context = self._runtime_context(request) or {}
        if context.get("called_agent") or context.get("resume_action"):
            # A TURN THE SERVER HANDED TO AN AGENT ("@member", or Continue on a
            # card) is that agent's turn, not an answer to some other card.
            # "Continue release-manager." read as a short reply was swallowed
            # as "unrecognised" while any card was pending, and could have
            # answered a different card (review of PR #58).
            return False
        return True

    def _complete_confirmation(self, request: Any) -> tuple[Any, Any]:
        from langchain_core.messages import AIMessage

        from . import confirm_flow
        from .confirm_flow import ConfirmationFlow

        messages = list(getattr(request, "messages", None) or [])
        if not self._may_answer_a_card(request, messages):
            return None, None

        flow = ConfirmationFlow(store=self.pending, middleware=self, now=self.now)
        result = flow.from_message(
            messages[-1],
            run_tool=self._runner(request),
            runtime_context=self._runtime_context(request),
        )
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
        return classify(self._tool_name(request), self._arguments(request), self.loader.load())

    @staticmethod
    def _tool_name(request) -> str:
        call = getattr(request, "tool_call", None) or {}
        return call.get("name") or getattr(getattr(request, "tool", None), "name", "") or ""

    @staticmethod
    def _arguments(request) -> dict:
        call = getattr(request, "tool_call", None) or {}
        return call.get("args") or {}

    def _require_confirmation(self, request, decision):
        """Tier 3: state the plan, record it durably, and do not execute.

        FR-006, GLOBALLY: content the agent READ may SUGGEST an action but can
        never confirm it or originate it silently. The proposal is still made
        (refusing outright hid from the user what the content asked for), but
        it is marked with what caused it, and an action not caused by the
        user's own latest message can only be confirmed with the card's button.
        """
        origin, origin_source, origin_via = self._origin(request)
        if origin != "user":
            logger.warning("policy: %s was suggested by %s %s (via %s); it can only be confirmed on its card (FR-006)", decision.tool_name, origin, origin_source, origin_via or "-")

        tool_name = decision.tool_name
        arguments = self._arguments(request)
        targets = list(self.resolve_targets(tool_name, arguments)) if self.resolve_targets else [f"{tool_name}({arguments})"]
        ruleset = self.loader.load()
        now = self.now()

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
        )
        action.plan_text = self._plan_text_for(action)
        self.pending.save(action)
        logger.info("policy: %s requires confirmation (%s)", tool_name, action.id)
        if self._is_invited(request):
            from omniharness.agents.invitation import STOPPED_AT_KEY

            context = getattr(getattr(request, "runtime", None), "context", None)
            if isinstance(context, dict):
                context.setdefault(STOPPED_AT_KEY, []).append({"id": action.id, "tool": tool_name})
        return self._as_tool_result(request, action.plan_text)

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

    def _inviting(self, origin: str, source: str, via: str, requester: str, chain: tuple[str, ...]) -> Any:
        """The mark an agent invited during this call starts from."""
        from omniharness.agents.invitation import TurnOrigin

        return TurnOrigin(origin=origin, source=source, chain=tuple(chain) or (requester,), via=via)

    def _inviting_for(self, request) -> Any:
        origin, source, via = self._origin(request)
        return self._inviting(origin, source, via, self._requester(request), self._delegation_chain(request))

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

        with inviting_turn(self._inviting(action.origin, action.origin_source, action.origin_via, action.requester, action.delegation_chain)), confirming(action):
            result = run_tool(action.tool_name, action.arguments)
        from .surface_run import observed_result, result_report

        # What "Continue <agent>" hands the agent as observed context.
        action.result_excerpt = observed_result(result)
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
