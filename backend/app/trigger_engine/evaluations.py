"""When each rule was last EVALUATED — not when it last fired (FR-020).

THE DISTINCTION THIS EXISTS FOR. Before this, a rule that had been evaluated
five hundred times and never fired was the same row as one that had never been
evaluated at all: both showed no firings and nothing else. That is the shape the
calendar lead-time bug hid in — alerts fired approximately never, and there was
nothing in any record to look at.

WHY IT IS PERSISTED RATHER THAN HELD IN MEMORY. `RuleHealth` already tracks
failures per rule and is lost on restart, which is fine for backoff state. It is
not fine here: a gateway restart would make every running rule read as "never
evaluated", which is exactly the false impression the field exists to remove.

EVALUATED MEANS THE RULE'S FUNCTION WAS CALLED. A rule that ran and raised WAS
evaluated — we asked and it failed. A rule muted by backoff was NOT: it was
skipped before anything ran. Collapsing those would report the engine as having
looked at something it deliberately did not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ._store import JsonStore


@dataclass
class EvaluationLog:
    """Durable `rule_id -> last evaluated at`, in the shape FingerprintStore uses."""

    path: Path
    _store: JsonStore = field(init=False)

    def __post_init__(self) -> None:
        self._store = JsonStore(path=self.path)

    def record(self, rule_id: str, now: datetime) -> None:
        self._store.set(rule_id, now.isoformat())

    def last_evaluated_at(self, rule_id: str) -> datetime | None:
        """None means NEVER EVALUATED, and callers must render it as that
        rather than as a blank — the whole point is that the two differ."""
        raw = self._store.get(rule_id)
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            # A corrupt entry is not evidence of an evaluation.
            return None

    def known_rules(self) -> list[str]:
        return self._store.keys()

    # NO `forget` HERE YET. One was written for retention and deleted before
    # commit: nothing calls it, the sweep does not need it until the rules panel
    # exists, and the honest way to defer that is not to ship the method. A
    # whitelist entry would have made an unused method look wired.
