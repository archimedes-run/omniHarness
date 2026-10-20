"""THE only file that knows Codex's record format (Feature 005, US3).

Grounded in the user's real ~/.codex (2026-10-19, structure only: 10 files,
7,508 rows) and in sodiumsun/agenttrail (MIT; see THIRD-PARTY-NOTICES.md),
whose ideas are ported here and corrected where the real files disagreed:

  * Sessions live in sessions/YYYY/MM/DD/rollout-*.jsonl. A RESUMED session
    keeps appending to its ORIGINAL file, in its original date folder, with a
    repeated session_meta (one real file has 37). So files are selected by
    modification time, never by folder date, and a repeated session_meta is a
    resume, not a new session and not drift.
  * A subagent rollout names its parent in a top-level `parent_thread_id`
    on this machine; agenttrail reads only the nested
    `source.subagent.thread_spawn.parent_thread_id` and would miss both real
    links. All known shapes are read; a subagent naming no parent is drift.
  * There is no uniform success flag. update_plan is acknowledged with
    "Plan updated"; apply_patch reports "Exit code: N" and a patch_apply_end
    with `success`. A todo or file change applies only on a confirmed result
    (agenttrail applied update_plan at call time; FR-031).
  * archived_sessions/ is a sibling of sessions/, never under it, so it is
    never read.

Every record shape is treated as provisional. Types seen and meaningless are
listed in CODEX_INERT_TYPES; anything else is counted as drift.
"""

from __future__ import annotations

import json
import logging
import re
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path

from ..models import EventKind
from ..record_source import RecordSource, SkipReason
from ..todos import ConfirmedActivity
from .base import ParsedRecord, SessionAdapter, SessionRef, ToolCall, ToolResult
from .claude_code import TAIL_RECORDS, _leaf, _parse_ts

logger = logging.getLogger(__name__)

#: "<type>" or "<type>:<payload.type>" keys seen on a real corpus that carry no
#: status meaning. Listed explicitly so a NEW type surfaces as drift.
CODEX_INERT_TYPES = frozenset(
    {
        "turn_context",
        "world_state",
        "compacted",
        "session_meta:resume",
        "event_msg:token_count",
        "event_msg:agent_reasoning",
        "event_msg:thread_settings_applied",
        "event_msg:web_search_end",
        "event_msg:context_compacted",
        "event_msg:item_completed",
        # Duplicates of event_msg user_message / agent_message, plus developer
        # and system instructions, which are not session activity.
        "response_item:message",
        "response_item:reasoning",
        "response_item:tool_search_call",
        "response_item:tool_search_output",
        "response_item:web_search_call",
    }
)

_PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+?)\s*$", re.M)
# Code mode (codex-cli 0.146, seen live 2026-10-19): tools are called from a
# JavaScript `exec` cell, e.g. `await tools.update_plan({plan:[{step:"x",
# status:"pending"}]})`, keys quoted or not, and the cell's output starts
# "Script completed" (or reports a failure).
_CODE_PLAN = re.compile(r"tools\.update_plan\s*\((.*?)\)\s*;", re.S)
_CODE_ITEM = re.compile(r"\{([^{}]*)\}")
_CODE_STEP = re.compile(r"""["']?step["']?\s*:\s*(["'`])(.*?)(?<!\\)\1""", re.S)
_CODE_STATUS = re.compile(r"""["']?status["']?\s*:\s*["'`](\w+)["'`]""")
_EXIT = re.compile(r"(?:Exit code:|Process exited with code)\s*(-?\d+)")


def _output_text(payload: dict) -> str:
    out = payload.get("output")
    if isinstance(out, list):
        return " ".join(x.get("text", "") for x in out if isinstance(x, dict))
    return out if isinstance(out, str) else ""


def _parent_of(meta: dict) -> str | None:
    """The parent thread of a subagent rollout, in any known shape."""
    parent = meta.get("parent_thread_id")
    if isinstance(parent, str) and parent:
        return parent
    sid, own = meta.get("session_id"), meta.get("id")
    if isinstance(sid, str) and sid and sid != own:
        return sid
    source = meta.get("source")
    if isinstance(source, dict):
        spawn = (source.get("subagent") or {}).get("thread_spawn") if isinstance(source.get("subagent"), dict) else None
        if isinstance(spawn, dict) and isinstance(spawn.get("parent_thread_id"), str):
            return spawn["parent_thread_id"]
    return None


def _is_subagent(meta: dict) -> bool:
    source = meta.get("source")
    return meta.get("thread_source") == "subagent" or (isinstance(source, dict) and "subagent" in source)


@dataclass
class _CodexFile:
    ident: tuple[int, int]
    offset: int = 0
    lineno: int = 0
    session_id: str | None = None
    project: str = ""
    parent: str | None = None
    subagent: bool = False
    first: ParsedRecord | None = None
    tail: deque[ParsedRecord] = field(default_factory=lambda: deque(maxlen=TAIL_RECORDS))
    unclassified: dict[str, int] = field(default_factory=dict)
    activity: ConfirmedActivity = field(default_factory=ConfirmedActivity)
    #: call_id -> tool name, so an output can be judged by its tool's rule.
    tools: dict[str, str] = field(default_factory=dict)
    #: Code-mode plans whose items were not literals (counted as drift).
    unparsed_plans: int = 0

    def records(self) -> list[ParsedRecord]:
        return ([self.first] if self.first is not None else []) + list(self.tail)


class CodexAdapter(SessionAdapter):
    name = "codex"
    agent = "codex"

    def __init__(self, source: RecordSource) -> None:
        self._source = source
        self._files: dict[Path, _CodexFile] = {}

    # ---- interpreting one record -----------------------------------------

    def parse(self, record: dict, path: Path, lineno: int) -> ParsedRecord | None:
        state = self._files.get(path)
        if state is None or not isinstance(record, dict):
            return None
        rtype = record.get("type")
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        at = _parse_ts(record.get("timestamp"))
        if not isinstance(rtype, str) or at is None:
            return None

        if rtype == "session_meta":
            return self._session_meta(state, payload, at, path, lineno)
        if state.session_id is None:
            return None  # nothing before the header can be attributed

        ptype = payload.get("type") if isinstance(payload.get("type"), str) else ""
        key = f"{rtype}:{ptype}" if ptype else rtype
        base = {"session_id": state.session_id, "at": at, "project": state.project}

        if key == "event_msg:user_message":
            return ParsedRecord(**base, kind=EventKind.PROGRESS, raw_type="user", text=str(payload.get("message") or ""))
        if key == "event_msg:agent_message":
            return ParsedRecord(**base, kind=EventKind.PROGRESS, raw_type="assistant", text=str(payload.get("message") or ""))
        if key == "event_msg:task_started":
            return ParsedRecord(**base, kind=EventKind.PROGRESS, raw_type=key)
        if key == "event_msg:task_complete":
            # An OBSERVED end of turn, as Claude's end_turn is.
            return ParsedRecord(**base, kind=EventKind.COMPLETED, raw_type="assistant", stop_reason="end_turn", text=str(payload.get("last_agent_message") or ""))
        if key == "event_msg:turn_aborted":
            return ParsedRecord(**base, kind=EventKind.COMPLETED, raw_type="assistant", stop_reason="aborted", text="(turn interrupted)")
        if key == "event_msg:patch_apply_end":
            ok = payload.get("success") is True
            changes = payload.get("changes")
            files = tuple(str(p) for p in changes) if ok and isinstance(changes, dict) else ()
            call_id = payload.get("call_id")
            results = (ToolResult(call_id=call_id, ok=ok),) if isinstance(call_id, str) else ()
            return ParsedRecord(**base, kind=EventKind.PROGRESS, raw_type=key, results=results, confirmed_files=files)
        if key == "event_msg:mcp_tool_call_end":
            return ParsedRecord(**base, kind=EventKind.PROGRESS, raw_type=key)
        if key in ("response_item:function_call", "response_item:custom_tool_call"):
            return ParsedRecord(**base, kind=EventKind.PROGRESS, raw_type="assistant", stop_reason="tool_use", calls=self._call(state, payload))
        if key in ("response_item:function_call_output", "response_item:custom_tool_call_output"):
            return ParsedRecord(**base, kind=EventKind.PROGRESS, raw_type="user", results=self._result(state, payload))
        # Inert or unknown: no event either way. The caller tells them apart,
        # counting an unknown key as drift (FR-024).
        return ParsedRecord(**base, kind=None, raw_type=key)

    def _session_meta(self, state: _CodexFile, meta: dict, at: datetime, path: Path, lineno: int) -> ParsedRecord | None:
        sid = meta.get("id")
        if not isinstance(sid, str) or not sid:
            return None
        if state.session_id is not None:
            # A resume appends a new header to the same file (FR-022).
            return ParsedRecord(session_id=state.session_id, at=at, kind=None, project=state.project, raw_type="session_meta:resume")
        state.session_id = sid
        cwd = meta.get("cwd")
        project = _leaf(cwd) if isinstance(cwd, str) and cwd else ""
        git = meta.get("git")
        branch = git.get("branch") if isinstance(git, dict) else None
        state.project = f"{project}@{branch}" if project and isinstance(branch, str) and branch else project
        state.subagent = _is_subagent(meta)
        state.parent = _parent_of(meta) if state.subagent else None
        if state.subagent and state.parent is None:
            # A subagent that names no parent: the link shape moved (FR-023).
            self._source.note_diagnostic("session_meta:subagent-without-parent", path, lineno)
        return ParsedRecord(session_id=sid, at=at, kind=EventKind.STARTED, project=state.project, raw_type="session_meta")

    @staticmethod
    def _call(state: _CodexFile, payload: dict) -> tuple[ToolCall, ...]:
        call_id, name = payload.get("call_id"), str(payload.get("name") or "")
        if not isinstance(call_id, str):
            return ()
        state.tools[call_id] = name
        todo, files = None, ()
        if name == "update_plan":
            try:
                args = json.loads(payload.get("arguments") or "{}")
            except (TypeError, ValueError):
                args = {}
            plan = args.get("plan") if isinstance(args, dict) else None
            if isinstance(plan, list):
                # Steps and statuses only; `explanation` is dropped (FR-030).
                todo = ("replace", [(i.get("step") or "", i.get("status")) for i in plan if isinstance(i, dict)])
        elif name == "exec" and isinstance(payload.get("input"), str):
            todo, files = CodexAdapter._code_mode(state, payload["input"])
        elif name == "apply_patch":
            text = payload.get("input")
            if not isinstance(text, str):
                try:
                    text = (json.loads(payload.get("arguments") or "{}") or {}).get("input")
                except (TypeError, ValueError, AttributeError):
                    text = None
            files = tuple(_PATCH_FILE.findall(text)) if isinstance(text, str) else ()
        if todo is None and not files:
            return ()
        return (ToolCall(call_id=call_id, tool=name, todo=todo, files=files),)

    @staticmethod
    def _code_mode(state: _CodexFile, code: str) -> tuple[tuple | None, tuple[str, ...]]:
        """A plan and patched files from a code-mode `exec` cell.

        The last update_plan in the cell wins. A plan whose items cannot be
        read as literals (built from variables, say) is counted as drift
        rather than guessed at.
        """
        todo = None
        calls = _CODE_PLAN.findall(code)
        if calls:
            items = []
            for body in _CODE_ITEM.findall(calls[-1]):
                step, status = _CODE_STEP.search(body), _CODE_STATUS.search(body)
                if step and status:
                    items.append((step.group(2), status.group(1)))
            if items:
                todo = ("replace", items)
            else:
                state.unparsed_plans += 1
        files = tuple(_PATCH_FILE.findall(code)) if "*** Begin Patch" in code else ()
        return todo, files

    @staticmethod
    def _result(state: _CodexFile, payload: dict) -> tuple[ToolResult, ...]:
        call_id = payload.get("call_id")
        if not isinstance(call_id, str):
            return ()
        tool = state.tools.pop(call_id, "")
        text = _output_text(payload)
        if tool == "update_plan":
            ok: bool | None = text.strip().startswith("Plan updated")
        elif tool == "exec":
            head = text.strip()
            ok = True if head.startswith("Script completed") else False if head.startswith(("Script failed", "Script error", "Error")) else None
        else:
            m = _EXIT.search(text)
            ok = (int(m.group(1)) == 0) if m else None
        return (ToolResult(call_id=call_id, ok=ok),)

    # ---- discovery -------------------------------------------------------

    def discover(self, window: timedelta, *, now: datetime | None = None) -> list[SessionRef]:
        """Sessions whose file changed in the window, reading only what was appended."""
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
                state = _CodexFile(ident=ident)
                self._files[path] = state
            if st.st_size > state.offset:
                self._consume(path, state)
        for gone in set(self._files) - live:
            del self._files[gone]

        refs: dict[str, SessionRef] = {}
        children: list[tuple[_CodexFile, SessionRef]] = []
        for path in candidates:
            state = self._files.get(path)
            if state is None or state.session_id is None:
                continue
            ref = SessionRef(
                session_id=state.session_id,
                project=state.project or path.parent.name,
                path=path,
                records=state.records(),
                unclassified_types=dict(state.unclassified),
                agent=self.agent,
                todos=state.activity.visible_todos(),
                files_changed=list(state.activity.files),
            )
            if state.subagent:
                children.append((state, ref))
            else:
                refs[ref.session_id] = ref
        for state, child in children:
            parent = refs.get(state.parent or "")
            if parent is None:
                refs[child.session_id] = child  # its parent is outside the window
                continue
            # A subagent is not a session the user started: its work advances
            # the parent's clock and adds its files, but its turn ending is not
            # the parent's, and its plan is its own (as with Claude sidechains).
            parent.records.extend(replace(r, kind=EventKind.PROGRESS, raw_type="sidechain", stop_reason=None, is_sidechain=True, text="") for r in child.records)
            for changed in child.files_changed:
                if changed not in parent.files_changed:
                    parent.files_changed.append(changed)
        return list(refs.values())

    def _consume(self, path: Path, state: _CodexFile) -> None:
        data = self._source.read_from(path, state.offset)
        end = data.rfind(b"\n")
        if end < 0:
            return  # a partial line: leave it until its newline arrives
        state.offset += end + 1
        for raw_line in data[: end + 1].split(b"\n")[:-1]:
            state.lineno += 1
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                self._source.note_skip(SkipReason.MALFORMED, path, state.lineno)
                continue
            if not isinstance(raw, dict):
                self._source.note_skip(SkipReason.MALFORMED, path, state.lineno)
                continue
            unparsed = state.unparsed_plans
            parsed = self.parse(raw, path, state.lineno)
            if state.unparsed_plans > unparsed:
                # A code-mode plan we could not read: the shape moved.
                # Not a skip: the record itself still parses.
                self._source.note_diagnostic("exec:update_plan-unreadable", path, state.lineno)
            if parsed is None:
                reason = SkipReason.NO_SESSION_ID if state.session_id is None else SkipReason.NO_TIMESTAMP
                self._source.note_skip(reason, path, state.lineno, raw_type=raw.get("type") if isinstance(raw.get("type"), str) else None)
                continue
            if parsed.kind is None:
                state.unclassified[parsed.raw_type] = state.unclassified.get(parsed.raw_type, 0) + 1
                reason = SkipReason.INERT_TYPE if parsed.raw_type in CODEX_INERT_TYPES else SkipReason.UNKNOWN_TYPE
                # note_skip counts an UNKNOWN_TYPE as drift and logs it.
                self._source.note_skip(reason, path, state.lineno, raw_type=parsed.raw_type)
                continue
            if state.first is None:
                state.first = parsed
            else:
                state.tail.append(parsed)
            for call in parsed.calls:
                state.activity.call(call)
            for result in parsed.results:
                state.activity.result(result)
            state.activity.add_files(parsed.confirmed_files)
