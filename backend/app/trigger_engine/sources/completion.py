"""Long-running task completion triggers (FR-002)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from ..models import Rule, TriggerEvent, TriggerType
from .base import SourceUnavailable, TriggerSource


@dataclass
class CompletionSource(TriggerSource):
    fetch_completions: Callable[[], list[dict]]

    def poll(self, rule: Rule, now: datetime) -> list[TriggerEvent]:
        try:
            tasks = self.fetch_completions()
        except Exception as exc:  # noqa: BLE001
            raise SourceUnavailable(f"{type(exc).__name__}: {exc}") from exc
        wanted = rule.match.get("status")
        return [
            TriggerEvent(
                type=TriggerType.COMPLETION,
                event_id=str(t.get("task_id", "")),
                at=now,
                fields={"task_id": t.get("task_id", ""), "status": t.get("status", ""), "summary": t.get("summary", "")},
                # duration and finish time are excluded on purpose — both drift.
                fingerprint_inputs={"task_id": t.get("task_id", ""), "status": t.get("status", "")},
            )
            for t in tasks
            if not wanted or t.get("status") == wanted
        ]
