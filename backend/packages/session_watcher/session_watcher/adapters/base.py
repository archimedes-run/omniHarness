"""The SessionAdapter boundary (FR-023).

All knowledge of any observed agent's record format lives behind this interface.
A second agent shows up as more sessions in the same replies, not as new tools
(FR-018b): the tool surface does not change.

Adding the second agent (Codex, Feature 005) was NOT "a new adapter and nothing
else", as this docstring used to claim: the service wired exactly one adapter
and the record shape had no tool-call ids, todo lists or parent links. Both are
now general: Discovery takes several adapters, and the optional fields below
carry what todo tracking and file evidence need.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from ..models import EventKind

# stop_reason values that mean the model finished its turn. `tool_use` and a null
# stop_reason are explicitly NOT here: both mean work was still in flight.
# "aborted" is Codex's interrupted turn (turn_aborted): the turn observably
# ended, it just did not finish its work. Claude never records it.
END_OF_TURN_REASONS = frozenset({"end_turn", "stop_sequence", "max_tokens", "aborted"})


@dataclass(frozen=True)
class ToolCall:
    """A tool call whose effect is applied only once its result confirms it.

    `todo` is a todo-list change: ("replace", [(title, status), ...]) for
    TodoWrite and Codex update_plan, ("create", title) for TaskCreate,
    ("update", task_id, status) for TaskUpdate. `files` are the paths the call
    would change. Neither is applied at call time (FR-031).
    """

    call_id: str
    tool: str
    todo: tuple | None = None
    files: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolResult:
    """The outcome of a ToolCall. `ok` None means the outcome is unknown.

    `created_id` is the id a successful TaskCreate assigned, read from its
    receipt, so a later TaskUpdate can name it.
    """

    call_id: str
    ok: bool | None
    created_id: str | None = None


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
    #: Tool calls and results on this record (a record can carry several).
    calls: tuple[ToolCall, ...] = ()
    results: tuple[ToolResult, ...] = ()
    #: Files a tool changed, already confirmed by the agent's own success
    #: record (Codex patch_apply_end), so they need no pending call.
    confirmed_files: tuple[str, ...] = ()

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
    #: Which adapter found it ("claude" or "codex").
    agent: str = "claude"
    #: The agent's own todo list as of its last CONFIRMED update; None when it
    #: has never made one (FR-030, FR-031).
    todos: list[tuple[str, str]] | None = None
    #: Paths changed by successful tool results, newest last.
    files_changed: list[str] = field(default_factory=list)


class SessionAdapter(ABC):
    """One observed agent's record format. The only format-aware surface."""

    name: str = "abstract"
    #: The label replies use for this agent.
    agent: str = "abstract"

    @abstractmethod
    def discover(self, window: timedelta, *, now: datetime | None = None) -> list[SessionRef]:
        """Find sessions with activity inside the window."""

    @abstractmethod
    def parse(self, record: dict, path: Path, lineno: int) -> ParsedRecord | None:
        """Interpret one record. None means skip it (FR-009).

        Returning None must never be an error path — unknown shapes are expected,
        because the observed format is explicitly not a public API.
        """
