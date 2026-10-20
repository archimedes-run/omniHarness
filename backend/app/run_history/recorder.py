"""What the trigger engine hands the run history for each automation run."""

from __future__ import annotations

from collections.abc import Callable

from app.run_history.store import TRIGGER, RunHistory
from omniharness.runtime.user_context import DEFAULT_USER_ID

#: The run kind for a trigger rule's run; source_id is the rule id.
AUTOMATION = "automation"


def automation_recorder(history: RunHistory) -> Callable[[dict], None]:
    def _record(run: dict) -> None:
        history.record(
            kind=AUTOMATION,
            source_id=run["rule_id"],
            event_id=run.get("event_id"),
            thread_id=run.get("thread_id"),
            started_at=run.get("started_at"),
            finished_at=run.get("finished_at"),
            status=run.get("status", "completed"),
            error=run.get("error"),
            body=_with_body_provenance(run.get("body") or {}),
            # The turn starts with the prompt the engine injected, not a person.
            first_human=TRIGGER,
            # WHO OWNS A SCHEDULED RUN: the system user. The engine injects
            # its turns as the internal principal, and the server sets that
            # run's context user_id to DEFAULT_USER_ID ("the system acting for
            # the owner"). ownership.can_access gives system-owned records to
            # the owner account (and the internal principal) and to no one else.
            owner_id=run.get("user_id") or DEFAULT_USER_ID,
        )

    return _record


def _with_body_provenance(body: dict) -> dict:
    """Where the run's top-level parts came from, alongside the messages'."""
    return {**body, "provenance": {"prompt": TRIGGER, "event": "untrusted_source_data", "reply": "assistant"}}
