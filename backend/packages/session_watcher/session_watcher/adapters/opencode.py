"""THE only file that knows the OpenCode coding-job relay format (spec 009 FR-010).

OpenCode runs inside a thread's container sandbox, on a network the watcher
cannot reach. The gateway relays each job as a small JSON-lines file under
its data dir (`code_jobs/watch/<job>.jsonl`, written by
app.gateway.code_jobs.relay) and this adapter reads that folder, read-only,
like the other agents' session folders. Observe-only (D6): nothing here can
act on a job.

Record shapes (`timestamp` ISO-8601 on every record):
  session   {"id", "project"}              the job started
  progress  {"text"}                        a command ran (with its exit code)
  files     {"count"}                       how many files the worker changed
  end       {"status", "text"}              the job ended: verified, unverified,
                                            failed, stopped or blocked
The relay carries no request text, commands or file names (they stay in the
owner's chat), so nothing here can show one user's work to another.
An unknown type is drift, counted like any adapter's.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from ..models import EventKind
from ..record_source import RecordSource, SkipReason
from .base import ParsedRecord, SessionAdapter, SessionRef
from .claude_code import _parse_ts

logger = logging.getLogger(__name__)

_TAIL = 200


@dataclass
class _JobFile:
    ident: tuple[int, int]
    offset: int = 0
    lineno: int = 0
    session_id: str | None = None
    project: str = ""
    records: list[ParsedRecord] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    unclassified: dict[str, int] = field(default_factory=dict)


class OpenCodeAdapter(SessionAdapter):
    name = "opencode"
    agent = "opencode"

    def __init__(self, source: RecordSource) -> None:
        self._source = source
        self._files: dict[Path, _JobFile] = {}

    def parse(self, record: dict, path: Path, lineno: int) -> ParsedRecord | None:
        state = self._files.get(path)
        if state is None or not isinstance(record, dict):
            return None
        rtype = record.get("type")
        at = _parse_ts(record.get("timestamp"))
        if not isinstance(rtype, str) or at is None:
            return None
        if rtype == "session":
            sid = record.get("id")
            if not isinstance(sid, str) or not sid:
                return None
            state.session_id = sid
            state.project = str(record.get("project") or "")[:200]
            return ParsedRecord(session_id=sid, at=at, kind=EventKind.STARTED, project=state.project, raw_type="user", text="coding job started")
        if state.session_id is None:
            return None
        base = {"session_id": state.session_id, "at": at, "project": state.project}
        if rtype == "progress":
            return ParsedRecord(**base, kind=EventKind.PROGRESS, raw_type="assistant", stop_reason="tool_use", text=str(record.get("text") or "")[:300])
        if rtype == "files":
            count = record.get("count") if isinstance(record.get("count"), int) else 0
            # Placeholders: the watcher counts files changed; names stay private.
            files = tuple(f"file {i + 1}" for i in range(max(0, min(count, 200))))
            return ParsedRecord(**base, kind=EventKind.PROGRESS, raw_type="files", confirmed_files=files)
        if rtype == "end":
            status = str(record.get("status") or "")
            # An OBSERVED end of the job. A stop is an interrupted turn.
            reason = "aborted" if status == "stopped" else "end_turn"
            text = f"Coding job {status}"
            return ParsedRecord(**base, kind=EventKind.COMPLETED, raw_type="assistant", stop_reason=reason, text=text)
        return ParsedRecord(**base, kind=None, raw_type=rtype)

    def discover(self, window: timedelta, *, now: datetime | None = None) -> list[SessionRef]:
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
                state = _JobFile(ident=ident)
                self._files[path] = state
            if st.st_size > state.offset:
                self._consume(path, state)
        for gone in set(self._files) - live:
            del self._files[gone]
        refs = []
        for path in candidates:
            state = self._files.get(path)
            if state is None or state.session_id is None:
                continue
            refs.append(
                SessionRef(
                    session_id=state.session_id,
                    project=state.project or "coding job",
                    path=path,
                    records=list(state.records),
                    unclassified_types=dict(state.unclassified),
                    agent=self.agent,
                    files_changed=list(state.files),
                )
            )
        return refs

    def _consume(self, path: Path, state: _JobFile) -> None:
        data = self._source.read_from(path, state.offset)
        end = data.rfind(b"\n")
        if end < 0:
            return
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
            parsed = self.parse(raw, path, state.lineno)
            if parsed is None:
                reason = SkipReason.NO_SESSION_ID if state.session_id is None else SkipReason.NO_TIMESTAMP
                self._source.note_skip(reason, path, state.lineno, raw_type=raw.get("type") if isinstance(raw.get("type"), str) else None)
                continue
            if parsed.kind is None:
                state.unclassified[parsed.raw_type] = state.unclassified.get(parsed.raw_type, 0) + 1
                self._source.note_skip(SkipReason.UNKNOWN_TYPE, path, state.lineno, raw_type=parsed.raw_type)
                continue
            for changed in parsed.confirmed_files:
                if changed not in state.files:
                    state.files.append(changed)
            state.records.append(parsed)
            if len(state.records) > _TAIL:
                # Keep the start record and the latest tail.
                state.records = [state.records[0], *state.records[-(_TAIL - 1) :]]
