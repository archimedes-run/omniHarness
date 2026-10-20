"""What the trigger engine hands the run history for each automation run."""

from __future__ import annotations

from collections.abc import Callable

from app.run_history.store import RunHistory

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
            body=run.get("body") or {},
        )

    return _record
