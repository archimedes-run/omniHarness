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

import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .confirm import Verdict, recognise
from .models import Outcome, PendingAction
from .pending import PendingStore

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

#: Internal, and deliberately NOT one of the seven. It means "this turn said
#: nothing about any pending action", which is what almost every turn is. It
#: exists so the flow can still report actions that expired while it looked,
#: without inventing a verdict about an ordinary sentence.
NO_VERDICT = "no_verdict"

#: A standalone run of digits, used as the scope proof above the threshold.
#: Deliberately NOT matched inside the 12-hex action id, which is stripped by
#: `recognise` and is not a count.
_COUNT = re.compile(r"(?<![0-9a-f])([0-9]{1,4})(?![0-9a-f])")


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

    def from_message(self, message: Any, *, run_tool: Callable[[str, dict], Any], runtime_context: dict | None = None, current_targets: list[str] | None = None) -> FlowResult:
        """The chat route. Always returns a result; NO_VERDICT is the usual one.

        A turn that says nothing about a pending action must not produce a
        verdict about an ordinary sentence — but it may still have found actions
        that expired, and those are reported either way (FR-038).
        """
        now = self.now()
        expired = self._expire(now)
        pending = self.store.open_actions(now)
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
            return FlowResult(UNRECOGNISED, verdict.action_id, verdict.reason, expired_meanwhile=expired)

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
        return self._apply(action, verdict.verdict, supplied, run_tool, current_targets, expired)

    def explicit(self, action_id: str, *, confirm: bool, run_tool: Callable[[str, dict], Any], supplied_count: int | None = None, current_targets: list[str] | None = None) -> FlowResult:
        """The UI route (Phase 3). Same claim, same execution, same outcomes."""
        now = self.now()
        expired = self._expire(now)
        action = self.store.get(action_id)
        if action is None:
            return FlowResult(UNRECOGNISED, action_id, "no such action", expired_meanwhile=expired)
        if action.outcome is not None:
            return FlowResult(ALREADY_RESOLVED, action_id, f"already resolved ({action.outcome})", expired_meanwhile=expired)
        if action.is_expired(now):
            return FlowResult(EXPIRED, action_id, "that action expired before it was confirmed", expired_meanwhile=expired)
        verdict = Verdict.CONFIRM if confirm else Verdict.DECLINE
        return self._apply(action, verdict, supplied_count, run_tool, current_targets, expired)

    # ---- the shared middle ----------------------------------------------

    def _apply(self, action: PendingAction, verdict: Verdict, supplied_count: int | None, run_tool: Callable[[str, dict], Any], current_targets: list[str] | None, expired: tuple[PendingAction, ...]) -> FlowResult:
        if verdict is Verdict.DECLINE:
            self.store.resolve(action, Outcome.DECLINED, "declined by the user")
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

        claimed = self.store.claim(action.id, self._claimant())
        if claimed is None:
            return FlowResult(ALREADY_RESOLVED, action.id, "another route confirmed that first", expired_meanwhile=expired)

        before = list(claimed.targets)
        try:
            result = self.middleware.execute_confirmed(claimed, run_tool=run_tool, current_targets=current_targets)
        except Exception as exc:  # noqa: BLE001 — see below
            # A CLAIMED ACTION MUST NEVER BE LEFT UNRESOLVED. The claim is a
            # one-shot file link, so an action that is claimed and still open
            # can never be confirmed again and never reports why — recoverable
            # only by expiry, and silent until then. Found by running a real
            # gateway: a tool raised on a missing injected argument and the
            # action sat claimed with outcome None.
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
                detail={"confirmed": before, "current": list(current_targets or [])},
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
