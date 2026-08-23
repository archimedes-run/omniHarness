"""Coalescing (FR-015).

Firings within a window become one delivered message. The window must not delay
unrelated items indefinitely — two firings far apart are two messages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..models import Firing

DEFAULT_WINDOW = timedelta(seconds=60)


def merge(firings: list[Firing]) -> str:
    """One message from several firings.

    A single firing delivers its reply verbatim — wrapping one item in list
    formatting makes the common case read like a digest.
    """
    texts = [f.reply.strip() for f in firings if f.reply and f.reply.strip()]
    if not texts:
        return ""
    if len(texts) == 1:
        return texts[0]
    return "\n\n".join(f"• {t}" for t in texts)


@dataclass
class CoalesceWindow:
    """Accumulates firings; a firing arriving while open joins it.

    Durable when a store is supplied — see DeferralQueue for why. A partially
    filled window is the more damaging of the two to lose, because the firings
    in it have already been fingerprinted as delivered-or-suppressed.
    """

    window: timedelta = DEFAULT_WINDOW
    opened_at: datetime | None = None
    pending: list[Firing] = field(default_factory=list)
    store: object | None = None
    queue_name: str = "coalesce"

    def __post_init__(self) -> None:
        self.restore()

    def restore(self) -> int:
        if self.store is None:
            return 0
        recovered = self.store.load(self.queue_name)
        if recovered:
            self.pending = recovered + self.pending
            if self.opened_at is None:
                # Treat a recovered window as already open, so it flushes on the
                # next cycle rather than waiting a full window from now.
                self.opened_at = recovered[0].event.at
        return len(recovered)

    def _persist(self) -> None:
        if self.store is not None:
            self.store.save(self.queue_name, self.pending)

    def add(self, firing: Firing, now: datetime) -> None:
        if self.opened_at is None:
            self.opened_at = now
        self.pending.append(firing)
        self._persist()

    def is_due(self, now: datetime) -> bool:
        return self.opened_at is not None and now - self.opened_at >= self.window

    def drain(self) -> list[Firing]:
        out, self.pending, self.opened_at = self.pending, [], None
        self._persist()
        return out
