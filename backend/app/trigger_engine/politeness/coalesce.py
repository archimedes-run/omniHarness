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
    """Accumulates firings; a firing arriving while open joins it."""

    window: timedelta = DEFAULT_WINDOW
    opened_at: datetime | None = None
    pending: list[Firing] = field(default_factory=list)

    def add(self, firing: Firing, now: datetime) -> None:
        if self.opened_at is None:
            self.opened_at = now
        self.pending.append(firing)

    def is_due(self, now: datetime) -> bool:
        return self.opened_at is not None and now - self.opened_at >= self.window

    def drain(self) -> list[Firing]:
        out, self.pending, self.opened_at = self.pending, [], None
        return out
