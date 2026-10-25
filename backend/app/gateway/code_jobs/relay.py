"""The relay the session watcher reads for coding jobs (spec 009 FR-010).

The watcher is host-resident and cannot reach the sandbox network, so the
gateway relays each job's progress as a small JSON-lines file per job under
`<data dir>/code_jobs/watch/`, in the gateway's own record shape (never the
worker's raw events). The watcher's OpenCode adapter
(session_watcher.adapters.opencode) reads that folder, read-only.

Record shapes (one JSON object per line, `timestamp` ISO-8601 UTC):
  {"type": "session", "id", "project", "title"}
  {"type": "progress", "text"}
  {"type": "files", "files": [...]}            files the worker changed
  {"type": "end", "status", "text"}            status: verified | unverified |
                                               failed | stopped | blocked
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class Relay:
    def __init__(self, folder: Path, job_id: str) -> None:
        self.path = folder / f"{job_id}.jsonl"
        self.job_id = job_id
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("code jobs: the watcher relay folder %s cannot be created", folder)

    def _write(self, record: dict) -> None:
        record = {"timestamp": datetime.now(UTC).isoformat(), **record}
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            logger.debug("code jobs: relay write failed for %s", self.job_id)

    def session(self, *, project: str, title: str) -> None:
        self._write({"type": "session", "id": f"opencode-{self.job_id}", "project": project, "title": title[:200]})

    def progress(self, text: str) -> None:
        self._write({"type": "progress", "text": text[:300]})

    def files(self, files: list[str]) -> None:
        if files:
            self._write({"type": "files", "files": files[:200]})

    def end(self, *, status: str, text: str) -> None:
        self._write({"type": "end", "status": status, "text": text[:500]})
