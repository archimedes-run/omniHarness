"""One way to put a stored time on the wire.

SQLite drops the zone of a ``DateTime(timezone=True)`` column on read, so a
row comes back with a naive datetime. Every time OmniHarness stores is written
in UTC, so a naive one IS UTC. Without the offset, ``isoformat()`` emits a
zone-less string and a browser parses it as LOCAL time: in New York a chat
updated a moment ago read "in about 4 hours". Every repository serialises row
times through ``utc_iso``.
"""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = ["utc_iso"]


def utc_iso(value: datetime) -> str:
    """ISO 8601 with its UTC offset, for an aware or a naive-UTC datetime."""
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC).isoformat()
