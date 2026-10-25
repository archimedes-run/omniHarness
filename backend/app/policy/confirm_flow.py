"""T003 — the ONE place a confirmation is recognised, claimed and executed.

WHY THERE IS EXACTLY ONE. Before this module, `recognise`, `open_actions`,
`claim` and `execute_confirmed` had no production caller at all: the middleware
stated a Tier 3 plan, recorded a PendingAction, and nothing could ever grant it.
Tier 3 was deny-with-explanation. A user approved, nothing happened, approved
again, nothing happened — and the reasonable next step is to stop asking and do
the thing by hand, which is the failure the gate exists to prevent.

So this feature builds the first completion path, and it builds ONE. Chat
(`PolicyMiddleware.before_model`) and the UI route added in Phase 3 both call in
here. A second implementation is what would let one confirmation execute twice,
because the atomic claim is the only thing standing between them —
`tests/gates/test_single_confirmation_path.py` asserts a single `claim` call site.

THE SCOPE THRESHOLD LIVES HERE, NOT IN THE UI. FR-009 originally sat under the
Surface 1 heading, which scoped it to the browser by placement rather than by
intent — and would have shipped this phase as a route where "yes" grants sixty
targets while a UI two phases later demanded proof of reading. A defence that
depends on which route the user happens to take is not a defence.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .confirm import Verdict, recognise, restate
from .models import Outcome, PendingAction
from .pending import PendingStore

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - import cycle: middleware imports this module
    from .middleware import PolicyMiddleware

#: The seven outcomes. Every one is distinct on purpose: collapsing any pair
#: into a generic failure is what makes a user retry something that will never
#: work, or believe something happened that did not.
EXECUTED = "executed"
DECLINED = "declined"
ALREADY_RESOLVED = "already_resolved"
EXPIRED = "expired"
TARGETS_DRIFTED = "targets_drifted"
UNRECOGNISED = "unrecognised"
THRESHOLD_NOT_MET = "threshold_not_met"
FAILED = "failed"
#: A typed "yes" for an action the user did not cause (FR-006, global): content
#: the agent read, or a trigger, suggested it, so only the card's button counts.
#: Not claimed, not resolved: the action stays open for the button.
CARD_ONLY = "card_only"
#: The proposing run's tool is not available in this chat NOW: its source was
#: removed from the chat, or is disconnected (plan.md §2.0). Not claimed, not
#: resolved: the action stays open, so restoring the source and confirming
#: again works.
TOOL_UNAVAILABLE = "tool_unavailable"
#: A decline that arrived while the confirmed call was already running: it
#: lost the claim, so it cannot stop the call, and it says so (review of PR #58:
#: it used to answer "I have not done it" and record DECLINED, then the run
#: recorded EXECUTED over it).
ALREADY_RUNNING = "already_running"

#: Internal, and deliberately NOT one of the seven. It means "this turn said
#: nothing about any pending action", which is what almost every turn is. It
#: exists so the flow can still report actions that expired while it looked,
#: without inventing a verdict about an ordinary sentence.
NO_VERDICT = "no_verdict"

#: Internal too: a probe (`from_message(..., execute=False)`) reached the point
#: where a confirmation would be claimed and run, and stopped there. Nothing
#: was claimed or run. The chat path uses it to run only such a turn in the
#: confirmation pool, in a slot (#118).
WOULD_EXECUTE = "would_execute"

#: A standalone run of digits, used as the scope proof above the threshold.
#: Deliberately NOT matched inside the 12-hex action id, which is stripped by
#: `recognise` and is not a count.
_COUNT = re.compile(r"(?<![0-9a-f])([0-9]{1,4})(?![0-9a-f])")


def take_claim(store: PendingStore, action_id: str, claimant: str) -> PendingAction | None:
    """THE one place a pending action is claimed (Gate T023, FR-004/FR-030).

    Confirmation claims to EXECUTE; the FR-042 supersede sweep
    (app/policy/supersede.py) claims to resolve WITHOUT executing, so that it
    cannot race a confirmation on another worker. Both come through here, so
    there is still exactly one claim site and one claim semantics.
    """
    return store.claim(action_id, claimant)


@dataclass(frozen=True)
class FlowResult:
    outcome: str
    action_id: str | None = None
    message: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    expired_meanwhile: tuple[PendingAction, ...] = ()


@dataclass
class ConfirmationFlow:
    """Holds the collaborators; carries no state of its own."""

    store: PendingStore
    middleware: PolicyMiddleware
    now: Callable[[], datetime]

    # ---- entry points ---------------------------------------------------

    def from_message(self, message: Any, *, run_tool: Callable[[str, dict], Any], runtime_context: dict | None = None, execute: bool = True) -> FlowResult:
        """The chat route. Always returns a result; NO_VERDICT is the usual one.

        A turn that says nothing about a pending action must not produce a
        verdict about an ordinary sentence — but it may still have found actions
        that expired, and those are reported either way (FR-038).

        `execute=False` is a probe: every outcome is the same, except that a
        confirmation which would now be claimed and run returns WOULD_EXECUTE
        instead, before the claim. Nothing runs.
        """
        now = self.now()
        expired = self._expire(now)
        # Ownership: a typed reply only ever answers the speaker's OWN plans.
        # The run's user_id is server-set; a plan from another account's run is
        # invisible here, exactly as it is on the card (confirmations router).
        # A typed reply answers only plans stated in THIS conversation, by THIS
        # speaker's own run, and only on a person's turn: never a scheduled
        # (synthetic) turn, whose "human" message is a rule's prompt. Without
        # the thread scope, "yes" typed in any chat (or any Telegram message)
        # answered whichever plan was pending anywhere.
        pending = answerable_by_typed_reply(self.store.open_actions(now), runtime_context, message)
        if not pending:
            return FlowResult(NO_VERDICT, expired_meanwhile=expired)

        text = self._text(message)
        supplied, stripped = self._extract_count(text)
        verdict = recognise(_Restated(message, stripped), pending, runtime_context)

        if verdict.verdict is Verdict.UNRECOGNISED:
            # Silence unless the reply was ABOUT a pending action. An
            # unrecognised chat turn is usually just conversation.
            if not self._looks_like_an_answer(stripped):
                return FlowResult(NO_VERDICT, expired_meanwhile=expired)
            # FR-035: an unrecognised answer restates the plan IN FULL, so the
            # user is never asked to approve something they can no longer see.
            # Several pending and none named: each is restated, with its id.
            addressed = [a for a in pending if a.id == verdict.action_id] or pending
            plans = "\n\n".join(restate(a) for a in addressed)
            message = f"{verdict.reason[:1].upper()}{verdict.reason[1:]}.\n\n{plans}" if len(addressed) > 1 and verdict.reason else plans
            return FlowResult(UNRECOGNISED, verdict.action_id, message, detail={"reason": verdict.reason}, expired_meanwhile=expired)

        if verdict.action_id is None:
            # A CONFIRM or DECLINE with no action attached should be
            # unreachable — `recognise` only returns one alongside an id. Guarded
            # rather than cast, because "unreachable" was the word used about the
            # redaction guard that turned out to fail open.
            return FlowResult(UNRECOGNISED, None, "recognised a verdict but no action was addressed", expired_meanwhile=expired)

        action = self.store.get(verdict.action_id)
        if action is None or action.outcome is not None:
            return FlowResult(
                ALREADY_RESOLVED,
                verdict.action_id,
                f"that action was already resolved ({action.outcome if action else 'unknown'})",
                expired_meanwhile=expired,
            )
        if verdict.verdict is Verdict.CONFIRM and not action.confirmable_by_typing:
            return FlowResult(CARD_ONLY, action.id, action.card_only_refusal(), detail={"origin": action.origin, "origin_source": action.origin_source}, expired_meanwhile=expired)
        ctx = runtime_context or {}
        channel = ctx.get("channel")
        answered = {
            "via": f"channel:{channel}" if channel else "typed_reply",
            "thread_id": ctx.get("thread_id"),
            "user_id": ctx.get("user_id"),
            "message_id": getattr(message, "id", None) or (message.get("id") if isinstance(message, dict) else None),
        }
        return self._apply(action, verdict.verdict, supplied, run_tool, expired, answered, execute=execute)

    def explicit(self, action_id: str, *, confirm: bool, run_tool: Callable[[str, dict], Any], supplied_count: int | None = None, answered: dict | None = None) -> FlowResult:
        """The UI route (Phase 3). Same claim, same execution, same outcomes."""
        now = self.now()
        expired = self._expire(now)
        action = self.store.get(action_id)
        if action is None:
            return FlowResult(UNRECOGNISED, action_id, "no such action", expired_meanwhile=expired)
        if action.outcome is not None:
            why = f": {action.outcome_reason}" if action.outcome == Outcome.DECLINED and action.outcome_reason else ""
            return FlowResult(ALREADY_RESOLVED, action_id, f"already resolved ({action.outcome}){why}", expired_meanwhile=expired)
        if action.is_expired(now):
            return FlowResult(EXPIRED, action_id, "that action expired before it was confirmed", expired_meanwhile=expired)
        verdict = Verdict.CONFIRM if confirm else Verdict.DECLINE
        return self._apply(action, verdict, supplied_count, run_tool, expired, answered or {"via": "button"})

    # ---- the shared middle ----------------------------------------------

    def _apply(self, action: PendingAction, verdict: Verdict, supplied_count: int | None, run_tool: Callable[[str, dict], Any], expired: tuple[PendingAction, ...], answered: dict | None = None, *, execute: bool = True) -> FlowResult:
        answered = {"via": None, "thread_id": None, "user_id": None, "message_id": None, **(answered or {})}
        if verdict is Verdict.DECLINE:
            # A DECLINE TAKES THE CLAIM, exactly as a confirmation does: the
            # one that loses never resolves the record.
            claimed = take_claim(self.store, action.id, f"decline:{self._claimant()}")
            if claimed is None:
                current = self.store.get(action.id)
                if current is not None and current.outcome is None:
                    return FlowResult(ALREADY_RUNNING, action.id, "That was already confirmed and is running now, so it cannot be stopped. Its result will be shown when it finishes.", expired_meanwhile=expired)
                return FlowResult(ALREADY_RESOLVED, action.id, f"already resolved ({current.outcome if current else 'unknown'})", expired_meanwhile=expired)
            claimed.confirmation = answered
            self.store.resolve(claimed, Outcome.DECLINED, "declined by the user")
            return FlowResult(DECLINED, action.id, "Understood — I have not done it.", expired_meanwhile=expired)

        threshold = self._threshold()
        if len(action.targets) > threshold:
            if supplied_count != len(action.targets):
                # NOT consumed, NOT claimed, NOT resolved. A wrong count is a
                # failed attempt, not a decline — resolving here would destroy
                # the action the user is still trying to approve.
                return FlowResult(
                    THRESHOLD_NOT_MET,
                    action.id,
                    f'That affects {len(action.targets)} items, above the {threshold} I ask you to confirm by count. Reply with a confirmation and the number — for example "yes {len(action.targets)}".',
                    detail={"required_count": len(action.targets), "threshold": threshold, "supplied": supplied_count},
                    expired_meanwhile=expired,
                )

        if not execute:
            # The probe stops here: this confirmation would be claimed and run.
            return FlowResult(WOULD_EXECUTE, action.id, expired_meanwhile=expired)

        # RE-CHECKED AT CONFIRMATION, before the claim: never run a tool the
        # user has since removed from the chat. A runner that can tell says
        # so through `unavailable` (surface_run.unavailable_reason).
        check = getattr(run_tool, "unavailable", None)
        reason = check(action) if callable(check) else None
        if reason:
            return FlowResult(TOOL_UNAVAILABLE, action.id, reason, detail={"reason": reason}, expired_meanwhile=expired)

        claimed = take_claim(self.store, action.id, self._claimant())
        if claimed is None:
            return FlowResult(ALREADY_RESOLVED, action.id, "another route confirmed that first", expired_meanwhile=expired)
        # Recorded on the claim before anything runs, so the audit entry the
        # execution writes says who confirmed, where, and by what.
        claimed.confirmation = answered
        self.store.save(claimed)

        before = list(claimed.targets)
        try:
            result = self.middleware.execute_confirmed(claimed, run_tool=run_tool)
        except Exception as exc:  # noqa: BLE001 — see below
            # A CLAIMED ACTION MUST NEVER BE LEFT UNRESOLVED. The claim is a
            # one-shot file link, so an action that is claimed and still open
            # can never be confirmed again and never reports why — recoverable
            # only by expiry, and silent until then. Found by running a real
            # gateway: a tool raised on a missing injected argument and the
            # action sat claimed with outcome None.
            # The exception's TYPE only: its text (and a traceback's) can carry
            # the call's arguments, and a log is not a redacted surface. The
            # one exception is the ledger's own refusal (LedgerError, raised
            # as the cause of the controller's "Nothing was changed"): its
            # text is the harness's message about the plan, and without it a
            # failed confirmed plan cannot be diagnosed from the log.
            logger.error("policy: confirmed action %s (%s) did not complete: %s%s", claimed.id, claimed.tool_name, type(exc).__name__, _ledger_reason(exc))
            self.store.resolve(claimed, Outcome.FAILED, f"authorised, but the tool did not complete: {exc}")
            return FlowResult(
                FAILED,
                claimed.id,
                f"You approved it and I could not complete it: {exc}",
                detail={"error": str(exc)},
                expired_meanwhile=expired,
            )
        refreshed = self.store.get(claimed.id)
        if refreshed is not None and refreshed.outcome == Outcome.TARGETS_DRIFTED:
            return FlowResult(
                TARGETS_DRIFTED,
                claimed.id,
                "The items changed since I described them, so I have not acted. Here is the plan again.",
                detail={"confirmed": before, "current": self.middleware.targets_now(claimed)},
                expired_meanwhile=expired,
            )
        return FlowResult(EXECUTED, claimed.id, "Done.", detail={"result": result}, expired_meanwhile=expired)

    # ---- helpers --------------------------------------------------------

    def _expire(self, now: datetime) -> tuple[PendingAction, ...]:
        """LAZY EXPIRY ON READ (FR-038).

        NOT a lifespan hook. The gateway's only periodic work is the trigger
        engine's task, behind `config.trigger_engine.enabled`, which defaults to
        false — hanging expiry off it would make this requirement inert whenever
        that flag is off, which is the built-but-never-runs family this phase
        exists to close. Expiring as we read has no config dependency and no
        background task that can fail to start.
        """
        return tuple(self.store.expire_due(now))

    def _threshold(self) -> int:
        return self.middleware.loader.load().threshold_targets

    def _claimant(self) -> str:
        return f"worker-{os.getpid()}"

    @staticmethod
    def _text(message: Any) -> str:
        raw = getattr(message, "content", None)
        if raw is None and isinstance(message, dict):
            raw = message.get("content")
        return str(raw or "")

    @staticmethod
    def _extract_count(text: str) -> tuple[int | None, str]:
        """Pull the scope proof out so the affirmation itself stays EXACT.

        The closed set is not widened to admit numbers; the number is removed
        and what remains must still be an exact member. "yes 12" confirms twelve
        targets; "yes" alone above the threshold does not confirm anything.
        """
        found = _COUNT.findall(text)
        if not found:
            return None, text
        return int(found[-1]), _COUNT.sub(" ", text)

    @staticmethod
    def _looks_like_an_answer(text: str) -> bool:
        """Conservative: only treat a SHORT reply as an attempted verdict.

        A long turn that happens to contain "no" is a sentence, not a decline,
        and reporting UNRECOGNISED for it would train the user to distrust the
        prompt.
        """
        return 0 < len(text.strip().split()) <= 6


class _Restated:
    """Carries the original message's type and lineage with substituted text.

    The count is stripped before recognition, but `recognise` runs THREE
    structural checks before it reads any text — synthetic-turn, message
    lineage, and which action is addressed. Those must see the real message, so
    this wrapper preserves it and overrides only `content`.
    """

    def __init__(self, original: Any, text: str) -> None:
        self._original = original
        self.content = text

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)


def _same_owner(owner_id: str | None, speaker: str | None) -> bool:
    """May this speaker answer this plan by typing?

    Only the plan's own owner. A plan with no recorded owner (written before
    owners were stored) is NOT answerable from a chat whose speaker is known:
    it can still be answered on the card, where the owner check applies. The
    one remaining case, neither side identified, is a run with no user at all,
    which production never makes (services.apply_server_owned_context).
    """
    if owner_id is None or speaker is None:
        return owner_id is None and speaker is None
    return str(owner_id) == str(speaker)


def _same_key(recorded: str | None, current: str | None) -> bool:
    """Same thread. Both unknown matches only in a harness with no thread at
    all; production runs always carry thread_id (the worker sets it)."""
    if recorded is None or current is None:
        return recorded is None and current is None
    return str(recorded) == str(current)


#: Server-set markers of a turn that is not a person answering: a resumed or
#: called agent (Feature 006 #58 sets these). Such a turn is never a verdict.
_NOT_A_PERSONS_TURN_KEYS = ("continue_action", "called_agent", "resume_action")


def turn_may_answer(message: Any, runtime_context: dict | None) -> bool:
    """THE ONE TEST of whether this turn may be read as a yes/no at all.

    `answerable_by_typed_reply` applies it, and the policy middleware calls it
    before anything else (so a turn that cannot answer does not even sweep
    expiry). False for: a message that is not the person's own server-tagged
    turn (lineage.is_user_turn: never a tool result, an agent's reply, an
    injected message, a subagent's instruction or a resumed agent's observed
    output); a scheduled (synthetic) turn; a turn the server handed to an
    agent (called_agent, resume_action: "@member" or Continue); an invited
    agent's (subagent's) turn.
    """
    from omniharness.agents.invitation import DELEGATION_CHAIN_KEY, INVITED_ORIGIN_KEY

    from .lineage import USER_ORIGINS, _message_type, is_invitation, is_tool_result
    from .provenance import is_synthetic_turn

    # A message that is not a person's message at all (a tool result, an
    # agent's reply, a resumed agent's observed output, an invitation) is
    # never an answer. Whether a human message is the person's own TAGGED turn
    # is decided by recognise (lineage.eligible_to_confirm), which restates the
    # plan to an untagged one rather than ignoring it.
    if message is not None and (_message_type(message) not in USER_ORIGINS or is_tool_result(message) or is_invitation(message)):
        return False
    ctx = runtime_context or {}
    if is_synthetic_turn(ctx) or any(ctx.get(k) for k in _NOT_A_PERSONS_TURN_KEYS):
        return False
    # An invited agent (subagent) has no person of its own: its "user" message
    # is its inviter's instruction. Nothing typed there confirms anything.
    return not (INVITED_ORIGIN_KEY in ctx or ctx.get(DELEGATION_CHAIN_KEY))


def answerable_by_typed_reply(actions: list[PendingAction], runtime_context: dict | None, message: Any = None) -> list[PendingAction]:
    """THE gate for typed confirmations: which plans may this turn answer?

    - only a person's own turn: never a scheduled (synthetic) turn, never a
      turn carrying a server-set continue_action / called_agent, never an
      invited agent's (subagent's) turn;
    - only plans stated in THIS thread;
    - only plans owned by THIS speaker (an owner-less legacy plan is
      answerable on the owner-checked card only).
    Whether a plan's ORIGIN allows typing at all (content- or automation-
    caused plans are card-only) is decided after recognition, from the plan.
    Several plans left after this gate and no id named: nothing is approved and
    each is restated (recognise / FR-035).
    """
    if not turn_may_answer(message, runtime_context):
        return []
    ctx = runtime_context or {}
    speaker, thread = ctx.get("user_id"), ctx.get("thread_id")
    return [a for a in actions if _same_owner(a.owner_id, speaker) and _same_key(a.thread_id, thread)]


def _ledger_reason(exc: BaseException) -> str:
    """The ledger's reason, for the log, when `exc` is (or was raised from)
    the ledger's own LedgerError; empty for anything else, whose text may
    carry arguments a log must not hold."""
    from app.gateway.utils import sanitize_log_param
    from app.ledger.service import LedgerError

    for candidate in (exc, exc.__cause__):
        if isinstance(candidate, LedgerError):
            return f" (ledger: {sanitize_log_param(str(candidate))})"
    return ""
