"""The few things a coding job does to its thread's sandbox, behind one seam.

`AioJobSandbox` is the production implementation over the AIO sandbox API
(the keyed :8080 front door of the thread's own container). Tests swap in a
fake that plays OpenCode's events, so the job manager, verification, the
store, Stop and the routes run unchanged.
"""

from __future__ import annotations

import logging
import shlex
import uuid
from typing import Protocol

logger = logging.getLogger(__name__)


class SandboxOps(Protocol):
    container: str

    def sh(self, command: str, *, timeout: int = 30) -> tuple[int | None, str]:
        """Run a short command in the job's control session: (exit code, output)."""
        ...

    def write(self, path: str, content: str) -> None: ...

    def read_text(self, path: str) -> str | None:
        """The file's text, or None when it does not exist."""
        ...

    def read_lines(self, path: str, start: int, count: int) -> list[str] | None:
        """Lines [start, start+count) (0-based), or None when the file does not exist."""
        ...

    def start(self, session_id: str, command: str) -> None:
        """Start a long command in its own session and return at once."""
        ...

    def end_session(self, session_id: str) -> None: ...

    def touch(self) -> None:
        """Mark the sandbox active so the idle reaper keeps it."""
        ...


class AioJobSandbox:
    def __init__(self, *, sandbox, container: str, touch=None) -> None:
        self._sandbox = sandbox
        self._client = sandbox._client  # the keyed agent_sandbox client
        self.container = container
        self._touch = touch
        self._ctl = f"ohjob-ctl-{uuid.uuid4().hex[:8]}"
        self._ctl_ready = False

    def _ensure_ctl(self) -> None:
        if not self._ctl_ready:
            self._client.shell.create_session(id=self._ctl, exec_dir="/tmp", no_change_timeout=120)
            self._ctl_ready = True

    def _fresh_ctl(self) -> None:
        # A new id: a session id that was cleaned up is not reusable.
        self._ctl = f"ohjob-ctl-{uuid.uuid4().hex[:8]}"
        self._ctl_ready = False
        self._ensure_ctl()

    def sh(self, command: str, *, timeout: int = 30) -> tuple[int | None, str]:
        self._ensure_ctl()

        def run():
            return self._client.shell.exec_command(id=self._ctl, command=command, no_change_timeout=timeout, hard_timeout=float(timeout) + 5, truncate=False)

        try:
            result = run()
        except Exception as exc:  # noqa: BLE001 - the session was cleaned up under us: once more, fresh
            if "Session not found" not in str(exc):
                raise
            self._fresh_ctl()
            result = run()
        data = result.data
        if data is not None and data.status == "terminated" and data.exit_code == -1 and not (data.output or "").strip():
            # The session's shell is gone (it was cleaned up or killed): once more, fresh.
            self._fresh_ctl()
            result = run()
        data = result.data
        if data is None:
            return None, ""
        return data.exit_code, data.output or ""

    def write(self, path: str, content: str) -> None:
        self._client.file.write_file(file=path, content=content)

    def read_text(self, path: str) -> str | None:
        code, out = self.sh(f"test -f {shlex.quote(path)} && echo __y__ || echo __n__", timeout=15)
        if "__y__" not in out:
            return None
        result = self._client.file.read_file(file=path)
        return result.data.content if result.data else ""

    def read_lines(self, path: str, start: int, count: int) -> list[str] | None:
        try:
            result = self._client.file.read_file(file=path, start_line=start, end_line=start + count)
        except Exception as exc:  # noqa: BLE001 - a missing file is an API error
            if "not" in str(exc).lower() and ("found" in str(exc).lower() or "exist" in str(exc).lower()):
                return None
            raise
        content = result.data.content if result.data else ""
        if not content:
            return []
        lines = content.split("\n")
        if content.endswith("\n"):
            lines = lines[:-1]
        return lines

    def start(self, session_id: str, command: str) -> None:
        self._client.shell.create_session(id=session_id, exec_dir="/tmp", no_change_timeout=24 * 3600)
        self._client.shell.exec_command(id=session_id, command=command, async_mode=True, no_change_timeout=24 * 3600, truncate=False)

    def end_session(self, session_id: str) -> None:
        for call in (self._client.shell.kill_process, self._client.shell.cleanup_session):
            try:
                call(id=session_id) if call is self._client.shell.kill_process else call(session_id)
            except Exception:  # noqa: BLE001 - best effort
                pass

    def close(self) -> None:
        if self._ctl_ready:
            self.end_session(self._ctl)
        self._ctl = f"ohjob-ctl-{uuid.uuid4().hex[:8]}"
        self._ctl_ready = False

    def touch(self) -> None:
        if self._touch is not None:
            try:
                self._touch()
            except Exception:  # noqa: BLE001
                pass
