"""THE only file that knows Claude Code's record format (FR-023).

Grounded in a live sample rather than assumption (research.md R2), but every
field is treated as optional and every shape as provisional — the format is not
a public API and will drift. Unknown entries are skipped and COUNTED, never
silently absorbed: a parser that quietly ignores a third of the file still
passes every fixture test.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath

from ..events import classify
from ..record_source import RecordSource, SkipReason
from .base import ParsedRecord, SessionAdapter, SessionRef

logger = logging.getLogger(__name__)

# Record types seen in the wild that carry no status meaning. Listed explicitly so
# that a genuinely NEW type shows up in unclassified_types rather than hiding in a
# catch-all. See research.md R2.
# Types observed in a real corpus that carry no status meaning. Listed explicitly
# so a genuinely NEW type surfaces as UNKNOWN_TYPE rather than hiding in a
# catch-all. The last five were absent from the original research sample and were
# found only by running against a real ~/.claude — evidence that the one-file
# sample was too narrow, exactly as research.md R2 cautioned.
KNOWN_INERT_TYPES = frozenset(
    {
        "attachment",
        "mode",
        "permission-mode",
        "atis-latch",
        "bridge-session",
        "last-prompt",
        "ai-title",
        "file-history-snapshot",
        "summary",
        "system",
        "pr-link",
        "queue-operation",
        "agent-name",
        "frame-link",
        "agent-setting",
        "file-history-delta",
    }
)


def _text_of(message: object) -> str:
    """Pull display text out of a message payload, tolerating several shapes."""
    if isinstance(message, str):
        return message
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"]
        return "\n".join(p for p in parts if p)
    return ""


def _leaf(cwd: str) -> str:
    """Last path segment of a cwd recorded on EITHER platform (FR-020).

    Not `Path(cwd).name`: on macOS/Linux that returns the whole string for a
    backslash path, so a session recorded on Windows would be named
    "C:\\Users\\dev\\projects\\repo" instead of "repo". The watcher normally reads
    its own host's records, but the adapter is the wrong place to assume that —
    and a mangled name is worse than a missing one, because it looks deliberate.
    """
    if "\\" in cwd and "/" not in cwd:
        return PureWindowsPath(cwd).name or cwd
    return PurePosixPath(cwd).name or cwd


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


#: Records kept per session per file, besides its first. resolve() reads the
#: first record, the newest ones (last assistant turn, last text, whether the
#: last turn asked a question) and the newest MAX_EVENTS; nothing in between.
#: Bounded so a long transcript costs bounded memory once it is cached.
TAIL_RECORDS = 500


@dataclass
class _SessionAccum:
    project: str
    first: ParsedRecord | None = None
    tail: deque[ParsedRecord] = field(default_factory=lambda: deque(maxlen=TAIL_RECORDS))
    unclassified: dict[str, int] = field(default_factory=dict)

    def add(self, record: ParsedRecord) -> None:
        if self.first is None:
            self.first = record
        else:
            self.tail.append(record)

    def records(self) -> list[ParsedRecord]:
        return ([self.first] if self.first is not None else []) + list(self.tail)


@dataclass
class _FileState:
    ident: tuple[int, int]  # (st_dev, st_ino): a replaced file is a new file
    offset: int = 0  # bytes consumed, always at a line boundary
    lineno: int = 0
    sessions: dict[str, _SessionAccum] = field(default_factory=dict)


class ClaudeCodeAdapter(SessionAdapter):
    name = "claude-code"

    def __init__(self, source: RecordSource) -> None:
        self._source = source
        self._files: dict[Path, _FileState] = {}

    def parse(self, record: dict, path: Path, lineno: int) -> ParsedRecord | None:
        if not isinstance(record, dict):
            return None
        # sessionId is the observed agent's own identifier. We adopt it verbatim
        # and never mint our own (research R2 finding 1). session_id is an alias
        # seen alongside it; one of the two is likely a compatibility shim.
        sid = record.get("sessionId") or record.get("session_id")
        if not isinstance(sid, str) or not sid:
            return None
        raw_type = record.get("type")
        if not isinstance(raw_type, str):
            return None
        at = _parse_ts(record.get("timestamp"))
        if at is None:
            return None
        message = record.get("message")
        stop_reason = message.get("stop_reason") if isinstance(message, dict) else None
        cwd = record.get("cwd")
        branch = record.get("gitBranch")
        project = ""
        if isinstance(cwd, str) and cwd:
            project = _leaf(cwd)
            if isinstance(branch, str) and branch:
                project = f"{project}@{branch}"
        return ParsedRecord(
            session_id=sid,
            at=at,
            kind=classify(raw_type, stop_reason=stop_reason if isinstance(stop_reason, str) else None),
            project=project,
            text=_text_of(message),
            is_sidechain=bool(record.get("isSidechain")),
            raw_type=raw_type,
            stop_reason=stop_reason if isinstance(stop_reason, str) else None,
        )

    def discover(self, window: timedelta, *, now: datetime | None = None) -> list[SessionRef]:
        """Sessions with activity in the window, reading only what was appended.

        Each file is read from where the last sweep stopped (its byte offset),
        so an append costs the appended bytes. It used to re-read every file in
        the window from the start on every sweep; with an 85 MB transcript being
        appended constantly, that held a core at 100% and the gateway's request
        to the watcher timed out.

        A file read from 0 again when it is new, replaced (different inode) or
        shorter than our offset (truncated or rewritten). A partial last line is
        left on disk until its newline arrives. The reconciliation sweep is
        unchanged: it calls this, and this re-checks every candidate's size.
        """
        candidates = self._source.select_candidates(window, now=now)
        live: set[Path] = set()
        for path in candidates:
            try:
                st = path.stat()
            except OSError:
                self._files.pop(path, None)
                continue
            live.add(path)
            ident = (st.st_dev, st.st_ino)
            state = self._files.get(path)
            if state is None or state.ident != ident or st.st_size < state.offset:
                state = _FileState(ident=ident)
                self._files[path] = state
            if st.st_size > state.offset:
                self._consume(path, state)
        for gone in set(self._files) - live:
            del self._files[gone]  # out of the window, or deleted; re-read from 0 if it returns

        refs: dict[str, SessionRef] = {}
        for path in candidates:
            state = self._files.get(path)
            if state is None:
                continue
            for sid, acc in state.sessions.items():
                ref = refs.get(sid)
                records = acc.records()
                if ref is None:
                    ref = SessionRef(session_id=sid, project=acc.project or path.parent.name, path=path)
                    refs[sid] = ref
                elif records and records[0] is acc.first:
                    # STARTED belongs to the session's first record across all
                    # its files, not to its first record in each file (FR-007).
                    records[0] = replace(acc.first, kind=classify(acc.first.raw_type, stop_reason=acc.first.stop_reason))
                ref.records.extend(records)
                for raw_type, n in acc.unclassified.items():
                    ref.unclassified_types[raw_type] = ref.unclassified_types.get(raw_type, 0) + n
        return list(refs.values())

    def _consume(self, path: Path, state: _FileState) -> None:
        data = self._source.read_from(path, state.offset)
        end = data.rfind(b"\n")
        if end < 0:
            return  # only a partial line so far: leave it until its newline arrives
        state.offset += end + 1
        for raw_line in data[: end + 1].split(b"\n")[:-1]:
            state.lineno += 1
            lineno = state.lineno
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                # Genuine damage: truncation or corruption. Skip the line,
                # keep reading the file — one bad line must not cost a session.
                self._source.note_skip(SkipReason.MALFORMED, path, lineno)
                continue
            if not isinstance(raw, dict):
                self._source.note_skip(SkipReason.MALFORMED, path, lineno)
                continue

            parsed = self.parse(raw, path, lineno)
            if parsed is None:
                reason, rt = self._why_skipped(raw)
                self._source.note_skip(reason, path, lineno, raw_type=rt)
                continue

            acc = state.sessions.get(parsed.session_id)
            if acc is None:
                acc = _SessionAccum(project=parsed.project)
                state.sessions[parsed.session_id] = acc
                # STARTED needs first-record context, which only the caller
                # has — classify() cannot know it in isolation (FR-007).
                parsed.kind = classify(parsed.raw_type, is_first=True, stop_reason=parsed.stop_reason)
            if parsed.kind is None and parsed.raw_type:
                acc.unclassified[parsed.raw_type] = acc.unclassified.get(parsed.raw_type, 0) + 1
                if parsed.raw_type not in KNOWN_INERT_TYPES:
                    self._source.stats.unknown_types[parsed.raw_type] += 1
            # Sidechain records advance the parent's activity clock but do
            # not become sessions of their own — a subagent is not a
            # session the user started (research R2).
            acc.add(parsed)

    @staticmethod
    def _why_skipped(raw: dict) -> tuple[SkipReason, str | None]:
        """Attribute a skip to a specific cause.

        The distinction that matters is INERT_TYPE (recognised, meaningless) vs
        UNKNOWN_TYPE (never seen — the format moved). Collapsing them is what makes
        real drift invisible.
        """
        raw_type = raw.get("type") if isinstance(raw.get("type"), str) else None
        sid = raw.get("sessionId") or raw.get("session_id")
        if not isinstance(sid, str) or not sid:
            return SkipReason.NO_SESSION_ID, raw_type
        if raw_type is None:
            return SkipReason.UNKNOWN_TYPE, None
        if not isinstance(raw.get("timestamp"), str) or not raw.get("timestamp"):
            if raw_type in KNOWN_INERT_TYPES:
                return SkipReason.INERT_TYPE, raw_type
            return SkipReason.UNKNOWN_TYPE, raw_type
        return (SkipReason.INERT_TYPE if raw_type in KNOWN_INERT_TYPES else SkipReason.UNKNOWN_TYPE), raw_type


def _sid_of(raw: object) -> str:
    if isinstance(raw, dict):
        sid = raw.get("sessionId") or raw.get("session_id")
        if isinstance(sid, str):
            return sid
    return ""
