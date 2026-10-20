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
import re
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath

from ..events import classify
from ..record_source import RecordSource, SkipReason
from ..todos import ConfirmedActivity
from .base import ParsedRecord, SessionAdapter, SessionRef, ToolCall, ToolResult

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
        # Request bookkeeping and per-session ledgers, found on a real
        # ~/.claude in October 2026 (watcher /health counted them as drift).
        # Shapes, keys only: api-request {id, base, params, tail, shapeHash,
        # requestDigest, timestamp}; api-request-blob {hash, message} with no
        # timestamp; api-request-shape {shape, shapeHash, timestamp};
        # cost-state {totalCostUSD, modelUsage, total*Duration, no timestamp};
        # artifact-comment-monitor and artifact-autoreact-ledger {artifacts, v}.
        # None of them says what the session is doing.
        "api-request",
        "api-request-blob",
        "api-request-shape",
        "cost-state",
        "artifact-comment-monitor",
        "artifact-autoreact-ledger",
    }
)

#: The one record that links two sessions. Observed shape (a real corpus,
#: keys only): {"type": "continued-in", "sessionId": <earlier>,
#: "continuedInSessionId": <later>, "timestamp"}, written as the LAST line of
#: the earlier session's file. The later session's file, in the same project
#: folder, starts with a copy of the earlier history re-keyed to the new
#: sessionId. The pointer runs forward only: nothing in the later file names
#: the earlier one by a dedicated key. It carries no status meaning, so it is
#: not drift, and it is not an event; it is read for the link.
CONTINUED_IN = "continued-in"
KNOWN_TYPES = KNOWN_INERT_TYPES | {CONTINUED_IN}


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


#: Tools whose input names a file they change (Feature 005, research R5).
FILE_TOOLS = {"Edit": "file_path", "Write": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
#: TaskCreate's text receipt, when the structured result is absent (about half
#: the time on a real corpus).
_CREATED = re.compile(r"Task #(\w+) created successfully")


def _todo_of(name: str, args: dict) -> tuple | None:
    """The todo change a tool call asks for, titles and statuses only (FR-030).

    Descriptions and activeForm are dropped here, at the point of reading.
    """
    if name == "TodoWrite":
        items = args.get("todos")
        if isinstance(items, list):
            return ("replace", [(i.get("content") or i.get("subject") or "", i.get("status")) for i in items if isinstance(i, dict)])
    elif name == "TaskCreate":
        subject = args.get("subject")
        if isinstance(subject, str) and subject:
            return ("create", subject)
    elif name == "TaskUpdate":
        task_id, status = args.get("taskId"), args.get("status")
        if task_id is not None and isinstance(status, str):
            return ("update", str(task_id), status)
    return None


def _tools_of(record: dict, message: object) -> tuple[tuple[ToolCall, ...], tuple[ToolResult, ...]]:
    """Tool calls (assistant) and results (user) carried by one record."""
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return (), ()
    calls, results = [], []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use" and isinstance(block.get("id"), str):
            name = str(block.get("name") or "")
            args = block.get("input") if isinstance(block.get("input"), dict) else {}
            path = args.get(FILE_TOOLS[name]) if name in FILE_TOOLS else None
            calls.append(ToolCall(call_id=block["id"], tool=name, todo=_todo_of(name, args), files=(path,) if isinstance(path, str) and path else ()))
        elif block.get("type") == "tool_result" and isinstance(block.get("tool_use_id"), str):
            ok = not block.get("is_error")
            structured = record.get("toolUseResult")
            created = None
            if isinstance(structured, dict):
                if structured.get("success") is False:
                    ok = False
                task = structured.get("task")
                if isinstance(task, dict) and task.get("id") is not None:
                    created = str(task["id"])
            if created is None:
                text = block.get("content")
                if isinstance(text, list):
                    text = " ".join(b.get("text", "") for b in text if isinstance(b, dict))
                match = _CREATED.search(text) if isinstance(text, str) else None
                created = match.group(1) if match else None
            results.append(ToolResult(call_id=block["tool_use_id"], ok=ok, created_id=created))
    return tuple(calls), tuple(results)


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
    activity: ConfirmedActivity = field(default_factory=ConfirmedActivity)

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
    #: earlier session id -> the session it was continued in, as recorded.
    continued_in: dict[str, str] = field(default_factory=dict)


class ClaudeCodeAdapter(SessionAdapter):
    name = "claude-code"
    agent = "claude"

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
        calls, results = _tools_of(record, message)
        return ParsedRecord(
            session_id=sid,
            at=at,
            kind=classify(raw_type, stop_reason=stop_reason if isinstance(stop_reason, str) else None),
            project=project,
            text=_text_of(message),
            is_sidechain=bool(record.get("isSidechain")),
            raw_type=raw_type,
            stop_reason=stop_reason if isinstance(stop_reason, str) else None,
            calls=calls,
            results=results,
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
                    ref = SessionRef(session_id=sid, project=acc.project or path.parent.name, path=path, agent=self.agent)
                    refs[sid] = ref
                elif records and records[0] is acc.first:
                    # STARTED belongs to the session's first record across all
                    # its files, not to its first record in each file (FR-007).
                    records[0] = replace(acc.first, kind=classify(acc.first.raw_type, stop_reason=acc.first.stop_reason))
                ref.records.extend(records)
                # The session's own list comes from its main file, never from a
                # subagent's (subagents/*.jsonl shares the session id).
                todos = acc.activity.visible_todos()
                if todos is not None and "subagents" not in path.parts:
                    ref.todos = todos
                for changed in acc.activity.files:
                    if changed not in ref.files_changed:
                        ref.files_changed.append(changed)
                for raw_type, n in acc.unclassified.items():
                    ref.unclassified_types[raw_type] = ref.unclassified_types.get(raw_type, 0) + n
        links = {pred: cont for state in self._files.values() for pred, cont in state.continued_in.items()}
        return fold_continuations(refs, links)

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

            if raw.get("type") == CONTINUED_IN:
                pred, cont = _sid_of(raw), raw.get("continuedInSessionId")
                if pred and isinstance(cont, str) and cont and cont != pred:
                    state.continued_in[pred] = cont

            parsed = self.parse(raw, path, lineno)
            if parsed is None:
                reason, rt = self._why_skipped(raw)
                self._source.note_skip(reason, path, lineno, raw_type=rt)
                continue

            acc = state.sessions.get(parsed.session_id)
            if acc is not None and not acc.project and parsed.project:
                # The first record may carry no cwd (a headless `claude -p`
                # run starts with one); name the session from the first that
                # does, not from the directory slug.
                acc.project = parsed.project
            if acc is None:
                acc = _SessionAccum(project=parsed.project)
                state.sessions[parsed.session_id] = acc
                # STARTED needs first-record context, which only the caller
                # has — classify() cannot know it in isolation (FR-007).
                parsed.kind = classify(parsed.raw_type, is_first=True, stop_reason=parsed.stop_reason)
            if parsed.kind is None and parsed.raw_type:
                acc.unclassified[parsed.raw_type] = acc.unclassified.get(parsed.raw_type, 0) + 1
                if parsed.raw_type not in KNOWN_TYPES:
                    # Parsed (it had a timestamp) but never seen: drift, the
                    # same as an unknown type that was skipped.
                    self._source.note_unknown(parsed.raw_type, path, lineno)
            # Sidechain records advance the parent's activity clock but do
            # not become sessions of their own — a subagent is not a
            # session the user started (research R2).
            acc.add(parsed)
            # Todo and file changes, applied only on a confirmed result
            # (Feature 005 FR-031). A subagent's todo list is its own, not
            # the session's, so sidechain calls contribute files only.
            for call in parsed.calls:
                acc.activity.call(replace(call, todo=None) if parsed.is_sidechain else call)
            for result in parsed.results:
                acc.activity.result(result)

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
            if raw_type in KNOWN_TYPES:
                return SkipReason.INERT_TYPE, raw_type
            return SkipReason.UNKNOWN_TYPE, raw_type
        return (SkipReason.INERT_TYPE if raw_type in KNOWN_TYPES else SkipReason.UNKNOWN_TYPE), raw_type


def _sid_of(raw: object) -> str:
    if isinstance(raw, dict):
        sid = raw.get("sessionId") or raw.get("session_id")
        if isinstance(sid, str):
            return sid
    return ""


def fold_continuations(refs: dict[str, SessionRef], links: dict[str, str]) -> list[SessionRef]:
    """Show a continued session and its continuation as ONE session.

    `links` maps an earlier session to the one it was continued in, as the
    earlier session's own `continued-in` record says. When both are in view the
    earlier one is folded into the later: its records join (the later file
    usually repeats them, so repeats are dropped), and the later one carries
    `continued_from`. When only the earlier one is in view it stays listed with
    `continued_in`: the link is recorded, the continuation is not seen.

    Chains (A continued in B, B in C) fold to the newest. A cycle is not
    followed past its first repeat.
    """
    for pred in list(links):
        ref = refs.get(pred)
        if ref is None:
            continue
        head, seen = links[pred], {pred}
        while head in links and head not in seen and links[head] in refs:
            seen.add(head)
            head = links[head]
        target = refs.get(head)
        if target is None or target is ref:
            ref.continued_in = head
            continue
        have = {(r.at, r.raw_type, r.text) for r in target.records}
        target.records[:0] = [r for r in ref.records if (r.at, r.raw_type, r.text) not in have]
        target.files_changed[:0] = [f for f in ref.files_changed if f not in target.files_changed]
        if target.todos is None:
            target.todos = ref.todos
        # The NEAREST recorded predecessor: a direct link always wins, a link
        # further up a chain only fills a gap.
        if links[pred] == head or target.continued_from is None:
            target.continued_from = pred
        del refs[pred]
    return list(refs.values())
