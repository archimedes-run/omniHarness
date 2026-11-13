"""The relay the session watcher reads for coding jobs (spec 009 FR-010).

The watcher is host-resident and cannot reach the sandbox network, so the
gateway relays each job's progress as a small JSON-lines file per job under
`<data dir>/code_jobs/watch/`, in the gateway's own record shape (never the
worker's raw events). The watcher's OpenCode adapter
(session_watcher.adapters.opencode) reads that folder, read-only.

It carries NO content: no request text, no commands, no file names, no
reasons. The watcher's feed is read by surfaces that are not per user, so a
job appears there only as "a coding job, running / ended with status X, N
files changed"; its details are in the owner's own chat card. The gateway's
/api/sessions further keeps only the caller's own jobs (by job id).

Record shapes (one JSON object per line, `timestamp` ISO-8601 UTC):
  {"type": "session", "id", "project"}         project: "coding job <id>"
  {"type": "progress", "text"}                 "ran a command (exit N)"
  {"type": "files", "count"}                   how many files changed
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

    def session(self) -> None:
        self._write({"type": "session", "id": f"opencode-{self.job_id}", "project": f"coding job {self.job_id[:8]}"})

    def command(self, exit_code: int | None) -> None:
        self._write({"type": "progress", "text": f"ran a command (exit {exit_code if exit_code is not None else '?'})"})

    def files(self, count: int) -> None:
        self._write({"type": "files", "count": int(count)})

    def end(self, *, status: str) -> None:
        self._write({"type": "end", "status": status, "text": status})
