"""What the trigger engine hands the run history for each automation run."""

from __future__ import annotations

from collections.abc import Callable

from app.run_history.store import TRIGGER, RunHistory

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
        )

    return _record


def _with_body_provenance(body: dict) -> dict:
    """Where the run's top-level parts came from, alongside the messages'."""
    return {**body, "provenance": {"prompt": TRIGGER, "event": "untrusted_source_data", "reply": "assistant"}}
