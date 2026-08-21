"""The SessionAdapter boundary (FR-023).

All knowledge of any observed agent's record format lives behind this interface.
Adding a second coding agent must be a new implementation here and nothing else —
in particular it must not change the registry, the event model, or the MCP tool
surface. A second agent shows up as more sessions in the same replies, not as new
tools (FR-018b).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from ..models import EventKind

# stop_reason values that mean the model finished its turn. `tool_use` and a null
# stop_reason are explicitly NOT here: both mean work was still in flight.
END_OF_TURN_REASONS = frozenset({"end_turn", "stop_sequence", "max_tokens"})


@dataclass
class ParsedRecord:
    """One interpreted record, normalized away from any agent's field names."""

    session_id: str
    at: datetime
    kind: EventKind | None
    project: str
    text: str = ""
    is_sidechain: bool = False
    raw_type: str = ""
    stop_reason: str | None = None

    @property
    def is_end_of_turn(self) -> bool:
        """True when this record is an OBSERVED end-of-turn marker (FR-006a).

        Verified against a real corpus: stop_reason is present on 100% of
        assistant message payloads. `tool_use` means the agent paused to call a
        tool and is still mid-work — emphatically NOT an end of turn.
        """
        return self.stop_reason in END_OF_TURN_REASONS


@dataclass
class SessionRef:
    """A discovered session, before its records are interpreted."""

    session_id: str
    project: str
    path: Path
    records: list[ParsedRecord] = field(default_factory=list)
    unclassified_types: dict[str, int] = field(default_factory=dict)


class SessionAdapter(ABC):
    """One observed agent's record format. The only format-aware surface."""

    name: str = "abstract"

    @abstractmethod
    def discover(self, window: timedelta, *, now: datetime | None = None) -> list[SessionRef]:
        """Find sessions with activity inside the window."""

    @abstractmethod
    def parse(self, record: dict, path: Path, lineno: int) -> ParsedRecord | None:
        """Interpret one record. None means skip it (FR-009).

        Returning None must never be an error path — unknown shapes are expected,
        because the observed format is explicitly not a public API.
        """
