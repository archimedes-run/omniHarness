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
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..events import classify
from ..record_source import RecordSource
from .base import ParsedRecord, SessionAdapter, SessionRef

logger = logging.getLogger(__name__)

# Record types seen in the wild that carry no status meaning. Listed explicitly so
# that a genuinely NEW type shows up in unclassified_types rather than hiding in a
# catch-all. See research.md R2.
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


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class ClaudeCodeAdapter(SessionAdapter):
    name = "claude-code"

    def __init__(self, source: RecordSource) -> None:
        self._source = source

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
        cwd = record.get("cwd")
        branch = record.get("gitBranch")
        project = ""
        if isinstance(cwd, str) and cwd:
            project = Path(cwd).name
            if isinstance(branch, str) and branch:
                project = f"{project}@{branch}"
        return ParsedRecord(
            session_id=sid,
            at=at,
            kind=classify(raw_type),
            project=project,
            text=_text_of(record.get("message")),
            is_sidechain=bool(record.get("isSidechain")),
            raw_type=raw_type,
        )

    def discover(self, window: timedelta, *, now: datetime | None = None) -> list[SessionRef]:
        refs: dict[str, SessionRef] = {}
        for path in self._source.select_candidates(window, now=now):
            with self._source.open(path) as fh:
                for lineno, line in enumerate(fh, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError as exc:
                        # Malformed or truncated. Skip it, keep reading the file.
                        self._source.note_skip(f"unparseable json: {exc.msg}", path, lineno)
                        continue
                    parsed = self.parse(raw, path, lineno)
                    if parsed is None:
                        rt = raw.get("type") if isinstance(raw, dict) else None
                        self._source.note_skip(f"uninterpretable record (type={rt})", path, lineno)
                        if isinstance(rt, str):
                            ref = refs.get(_sid_of(raw))
                            if ref is not None:
                                ref.unclassified_types[rt] = ref.unclassified_types.get(rt, 0) + 1
                        continue
                    ref = refs.get(parsed.session_id)
                    if ref is None:
                        ref = SessionRef(
                            session_id=parsed.session_id,
                            project=parsed.project or path.parent.name,
                            path=path,
                        )
                        refs[parsed.session_id] = ref
                    if parsed.kind is None and parsed.raw_type:
                        ref.unclassified_types[parsed.raw_type] = ref.unclassified_types.get(parsed.raw_type, 0) + 1
                    # Sidechain records advance the parent's activity clock but do
                    # not become sessions of their own — a subagent is not a
                    # session the user started (research R2).
                    ref.records.append(parsed)
        return list(refs.values())


def _sid_of(raw: object) -> str:
    if isinstance(raw, dict):
        sid = raw.get("sessionId") or raw.get("session_id")
        if isinstance(sid, str):
            return sid
    return ""
