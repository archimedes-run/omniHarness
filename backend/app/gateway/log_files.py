"""The gateway's log file: appended, rotated daily, kept 30 days, never truncated.

WHY NOT ``> gateway.log`` OR ``TimedRotatingFileHandler``. A shell redirect
truncates the file at every start, so a crash's evidence was wiped by the
restart that followed it. ``TimedRotatingFileHandler`` renames the file at
rollover, and under ``uvicorn --workers N`` every worker renames it, racing.

So each day has its own file, ``<name>-YYYY-MM-DD.log``, opened in append mode
by every worker (small appends with O_APPEND do not interleave mid-line), and
NOTHING is ever renamed. ``<name>.log`` is a symlink to today's file, replaced
atomically, so ``tail -F logs/gateway.log`` keeps working. Files older than
``retention_days`` are deleted when a new day starts.

Enabled by ``GATEWAY_LOG_FILE`` (e.g. ``/app/logs/gateway.log``). Unset, the
gateway logs to the console only, as before.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

LOG_FILE_ENV = "GATEWAY_LOG_FILE"
RETENTION_DAYS = 30
_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


class DailyAppendFileHandler(logging.Handler):
    """One append-only file per day; a stable symlink; pruning by age."""

    def __init__(self, path: str | Path, *, retention_days: int = RETENTION_DAYS, today: Callable[[], date] | None = None) -> None:
        super().__init__()
        self.path = Path(path)
        self.retention_days = retention_days
        self._today = today or (lambda: datetime.now().date())
        self._day: date | None = None
        self._stream = None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._pattern = re.compile(re.escape(self.path.stem) + r"-(\d{4}-\d{2}-\d{2})" + re.escape(self.path.suffix or ".log") + r"$")

    def file_for(self, day: date) -> Path:
        return self.path.with_name(f"{self.path.stem}-{day.isoformat()}{self.path.suffix or '.log'}")

    def _open_for(self, day: date) -> None:
        if self._stream is not None:
            self._stream.close()
        target = self.file_for(day)
        self._stream = target.open("a", encoding="utf-8")  # append: never truncated
        self._day = day
        self._point_symlink(target)
        self.prune(day)

    def _point_symlink(self, target: Path) -> None:
        # A name of this call's own (issue #93). It was the pid alone, shared
        # by every handler of one process: one unlinked another's temporary
        # link or failed on it (FileExistsError), its cleanup then deleted the
        # other's, the other's replace failed, and the plain file from before
        # was never replaced by the symlink.
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            # A plain file from the old shell redirect: keep its lines by
            # HARD-LINKING it under a dated name, then atomically replace the
            # path with the symlink. Nothing is renamed, so several workers
            # starting at once cannot move each other's symlink or lose lines;
            # a late worker that links today's file instead only adds a
            # harmless second name for it.
            st = os.lstat(self.path) if os.path.lexists(self.path) else None
            if st is not None and not os.path.islink(self.path):
                keep = self.path.with_name(f"{self.path.stem}-pre-rotation-{st.st_ino}{self.path.suffix or '.log'}")
                try:
                    os.link(self.path, keep, follow_symlinks=False)
                except FileExistsError:
                    pass
            tmp.symlink_to(target.name)
            os.replace(tmp, self.path)
        except OSError:
            tmp.unlink(missing_ok=True)

    def prune(self, today: date) -> list[Path]:
        """Delete dated files older than the retention window; return them."""
        cutoff = today - timedelta(days=self.retention_days)
        removed = []
        # Copies kept from the old shell redirect follow the same retention.
        pre_rotation = f"{self.path.stem}-pre-rotation-"
        now = datetime.now().timestamp()
        for candidate in self.path.parent.glob(f"{pre_rotation}*"):
            try:
                if now - candidate.stat().st_mtime > self.retention_days * 86400:
                    candidate.unlink()
                    removed.append(candidate)
            except OSError:
                pass
        for candidate in self.path.parent.iterdir():
            match = self._pattern.match(candidate.name)
            if not match:
                continue
            try:
                day = date.fromisoformat(match.group(1))
            except ValueError:
                continue
            if day < cutoff:
                try:
                    candidate.unlink()
                    removed.append(candidate)
                except OSError:
                    pass
        return removed

    def emit(self, record: logging.LogRecord) -> None:
        try:
            day = self._today()
            if day != self._day or self._stream is None:
                self._open_for(day)
            self._stream.write(self.format(record) + "\n")
            self._stream.flush()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        try:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
        finally:
            super().close()


def install_log_file(path: str | None = None) -> DailyAppendFileHandler | None:
    """Send the root and uvicorn loggers to the daily file (if configured).

    Console handlers on those loggers are removed so the file is the record,
    and a supervisor's stdout capture holds only what happens before this runs
    (and hard crashes), rather than a second, unrotated copy of everything.
    """
    path = path or os.environ.get(LOG_FILE_ENV, "").strip() or None
    if not path:
        return None
    from app.gateway.logging_filters import add_preview_token_filter

    handler = DailyAppendFileHandler(path)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
    # Every record this file receives, from any logger, is redacted.
    add_preview_token_filter(handler)
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        target = logging.getLogger(name)
        for existing in list(target.handlers):
            if isinstance(existing, logging.StreamHandler) and not isinstance(existing, logging.FileHandler):
                target.removeHandler(existing)
        target.addHandler(handler)
        if name:
            target.propagate = False
    return handler
