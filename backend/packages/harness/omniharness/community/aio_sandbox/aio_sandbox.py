import base64
import json
import logging
import shlex
import threading
import uuid

from agent_sandbox import Sandbox as AioSandboxClient

from omniharness.sandbox.sandbox import Sandbox
from omniharness.sandbox.search import GrepMatch, path_matches, should_ignore_path, truncate_line

logger = logging.getLogger(__name__)

_ERROR_OBSERVATION_SIGNATURE = "'ErrorObservation' object has no attribute 'exit_code'"


class AioSandbox(Sandbox):
    """Sandbox implementation using the agent-infra/sandbox Docker container.

    This sandbox connects to a running AIO sandbox container via HTTP API.
    A threading lock serializes shell commands to prevent concurrent requests
    from corrupting the container's single persistent session (see #1433).
    """

    def __init__(self, id: str, base_url: str, home_dir: str | None = None):
        """Initialize the AIO sandbox.

        Args:
            id: Unique identifier for this sandbox instance.
            base_url: URL of the sandbox API (e.g., http://localhost:8080).
            home_dir: Home directory inside the sandbox. If None, will be fetched from the sandbox.
        """
        super().__init__(id)
        self._base_url = base_url
        self._client = AioSandboxClient(base_url=base_url, timeout=600)
        self._home_dir = home_dir
        self._lock = threading.Lock()

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def home_dir(self) -> str:
        """Get the home directory inside the sandbox."""
        if self._home_dir is None:
            context = self._client.sandbox.get_context()
            self._home_dir = context.home_dir
        return self._home_dir

    # Default no_change_timeout for exec_command (seconds).  Matches the
    # client-level timeout so that long-running commands which produce no
    # output are not prematurely terminated by the sandbox's built-in 120 s
    # default.
    _DEFAULT_NO_CHANGE_TIMEOUT = 600
    _DEFAULT_PREVIEW_FETCH_TIMEOUT = 30

    def execute_command(self, command: str) -> str:
        """Execute a shell command in the sandbox.

        Uses a lock to serialize concurrent requests. The AIO sandbox
        container maintains a single persistent shell session that
        corrupts when hit with concurrent exec_command calls (returns
        ``ErrorObservation`` instead of real output). If corruption is
        detected despite the lock (e.g. multiple processes sharing a
        sandbox), the command is retried on a fresh session.

        Args:
            command: The command to execute.

        Returns:
            The output of the command.
        """
        with self._lock:
            try:
                result = self._client.shell.exec_command(command=command, no_change_timeout=self._DEFAULT_NO_CHANGE_TIMEOUT)
                output = result.data.output if result.data else ""

                if output and _ERROR_OBSERVATION_SIGNATURE in output:
                    logger.warning("ErrorObservation detected in sandbox output, retrying with a fresh session")
                    fresh_id = str(uuid.uuid4())
                    result = self._client.shell.exec_command(command=command, id=fresh_id, no_change_timeout=self._DEFAULT_NO_CHANGE_TIMEOUT)
                    output = result.data.output if result.data else ""

                return output if output else "(no output)"
            except Exception as e:
                logger.error(f"Failed to execute command in sandbox: {e}")
                return f"Error: {e}"

    def read_file(self, path: str) -> str:
        """Read the content of a file in the sandbox.

        Args:
            path: The absolute path of the file to read.

        Returns:
            The content of the file.
        """
        try:
            result = self._client.file.read_file(file=path)
            return result.data.content if result.data else ""
        except Exception as e:
            logger.error(f"Failed to read file in sandbox: {e}")
            return f"Error: {e}"

    def list_dir(self, path: str, max_depth: int = 2) -> list[str]:
        """List the contents of a directory in the sandbox.

        Args:
            path: The absolute path of the directory to list.
            max_depth: The maximum depth to traverse. Default is 2.

        Returns:
            The contents of the directory.
        """
        with self._lock:
            try:
                result = self._client.shell.exec_command(command=f"find {shlex.quote(path)} -maxdepth {max_depth} -type f -o -type d 2>/dev/null | head -500", no_change_timeout=self._DEFAULT_NO_CHANGE_TIMEOUT)
                output = result.data.output if result.data else ""
                if output:
                    return [line.strip() for line in output.strip().split("\n") if line.strip()]
                return []
            except Exception as e:
                logger.error(f"Failed to list directory in sandbox: {e}")
                return []

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        """Write content to a file in the sandbox.

        Args:
            path: The absolute path of the file to write to.
            content: The text content to write to the file.
            append: Whether to append the content to the file.
        """
        with self._lock:
            try:
                if append:
                    existing = self.read_file(path)
                    if not existing.startswith("Error:"):
                        content = existing + content
                self._client.file.write_file(file=path, content=content)
            except Exception as e:
                logger.error(f"Failed to write file in sandbox: {e}")
                raise

    def glob(self, path: str, pattern: str, *, include_dirs: bool = False, max_results: int = 200) -> tuple[list[str], bool]:
        if not include_dirs:
            result = self._client.file.find_files(path=path, glob=pattern)
            files = result.data.files if result.data and result.data.files else []
            filtered = [file_path for file_path in files if not should_ignore_path(file_path)]
            truncated = len(filtered) > max_results
            return filtered[:max_results], truncated

        result = self._client.file.list_path(path=path, recursive=True, show_hidden=False)
        entries = result.data.files if result.data and result.data.files else []
        matches: list[str] = []
        root_path = path.rstrip("/") or "/"
        root_prefix = root_path if root_path == "/" else f"{root_path}/"
        for entry in entries:
            if entry.path != root_path and not entry.path.startswith(root_prefix):
                continue
            if should_ignore_path(entry.path):
                continue
            rel_path = entry.path[len(root_path) :].lstrip("/")
            if path_matches(pattern, rel_path):
                matches.append(entry.path)
                if len(matches) >= max_results:
                    return matches, True
        return matches, False

    def grep(
        self,
        path: str,
        pattern: str,
        *,
        glob: str | None = None,
        literal: bool = False,
        case_sensitive: bool = False,
        max_results: int = 100,
    ) -> tuple[list[GrepMatch], bool]:
        import re as _re

        regex_source = _re.escape(pattern) if literal else pattern
        # Validate the pattern locally so an invalid regex raises re.error
        # (caught by grep_tool's except re.error handler) rather than a
        # generic remote API error.
        _re.compile(regex_source, 0 if case_sensitive else _re.IGNORECASE)
        regex = regex_source if case_sensitive else f"(?i){regex_source}"

        if glob is not None:
            find_result = self._client.file.find_files(path=path, glob=glob)
            candidate_paths = find_result.data.files if find_result.data and find_result.data.files else []
        else:
            list_result = self._client.file.list_path(path=path, recursive=True, show_hidden=False)
            entries = list_result.data.files if list_result.data and list_result.data.files else []
            candidate_paths = [entry.path for entry in entries if not entry.is_directory]

        matches: list[GrepMatch] = []
        truncated = False

        for file_path in candidate_paths:
            if should_ignore_path(file_path):
                continue

            search_result = self._client.file.search_in_file(file=file_path, regex=regex)
            data = search_result.data
            if data is None:
                continue

            line_numbers = data.line_numbers or []
            matched_lines = data.matches or []
            for line_number, line in zip(line_numbers, matched_lines):
                matches.append(
                    GrepMatch(
                        path=file_path,
                        line_number=line_number if isinstance(line_number, int) else 0,
                        line=truncate_line(line),
                    )
                )
                if len(matches) >= max_results:
                    truncated = True
                    return matches, truncated

        return matches, truncated

    def update_file(self, path: str, content: bytes) -> None:
        """Update a file with binary content in the sandbox.

        Args:
            path: The absolute path of the file to update.
            content: The binary content to write to the file.
        """
        with self._lock:
            try:
                base64_content = base64.b64encode(content).decode("utf-8")
                self._client.file.write_file(file=path, content=base64_content, encoding="base64")
            except Exception as e:
                logger.error(f"Failed to update file in sandbox: {e}")
                raise

    def create_shell_session(
        self,
        *,
        session_id: str,
        exec_dir: str,
        no_change_timeout: int = 24 * 60 * 60,
        preserve_symlinks: bool = True,
    ) -> str:
        """Create or reconnect to a dedicated shell session."""
        result = self._client.shell.create_session(
            id=session_id,
            exec_dir=exec_dir,
            no_change_timeout=no_change_timeout,
            preserve_symlinks=preserve_symlinks,
        )
        if not result.data:
            raise RuntimeError("Failed to create sandbox shell session")
        return result.data.session_id

    def start_shell_command(
        self,
        *,
        session_id: str,
        command: str,
        exec_dir: str,
        no_change_timeout: int = 24 * 60 * 60,
        hard_timeout: float | None = None,
    ) -> dict:
        """Start a long-running command in an existing shell session."""
        result = self._client.shell.exec_command(
            id=session_id,
            command=command,
            exec_dir=exec_dir,
            async_mode=True,
            no_change_timeout=no_change_timeout,
            hard_timeout=hard_timeout,
            preserve_symlinks=True,
            truncate=False,
        )
        if not result.data:
            raise RuntimeError("Sandbox did not return shell command status")
        return {
            "session_id": result.data.session_id,
            "status": result.data.status,
            "output": result.data.output or "",
            "exit_code": result.data.exit_code,
            "command": result.data.command,
        }

    def view_shell_session(self, session_id: str) -> dict:
        """Return the current output and status of a shell session."""
        result = self._client.shell.view(id=session_id)
        if not result.data:
            raise RuntimeError("Sandbox did not return shell session output")
        return {
            "session_id": result.data.session_id,
            "status": result.data.status,
            "output": result.data.output,
            "exit_code": result.data.exit_code,
            "command": result.data.command,
        }

    def kill_shell_session(self, session_id: str) -> None:
        """Terminate the process attached to a shell session, if any."""
        self._client.shell.kill_process(id=session_id)

    def cleanup_shell_session(self, session_id: str) -> None:
        """Remove a shell session from the sandbox runtime."""
        self._client.shell.cleanup_session(session_id)

    def fetch_local_url(
        self,
        *,
        port: int,
        path: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout: int = _DEFAULT_PREVIEW_FETCH_TIMEOUT,
    ) -> dict:
        """Fetch a localhost HTTP endpoint from inside the sandbox.

        This is used by preview-session proxying for dev servers that only bind
        inside the sandbox container.
        """
        request_payload = {
            "url": f"http://127.0.0.1:{port}{path}",
            "method": method,
            "headers": headers or {},
            "bodyBase64": base64.b64encode(body).decode("ascii") if body else "",
        }
        encoded_payload = base64.b64encode(json.dumps(request_payload, separators=(",", ":")).encode("utf-8")).decode("ascii")
        code = f"""
const payload = JSON.parse(Buffer.from("{encoded_payload}", "base64").toString("utf8"));
const body = payload.bodyBase64 ? Buffer.from(payload.bodyBase64, "base64") : undefined;
try {{
  const response = await fetch(payload.url, {{
    method: payload.method,
    headers: payload.headers,
    body,
    redirect: "manual",
  }});
  const headers = {{}};
  response.headers.forEach((value, key) => {{
    headers[key] = value;
  }});
  const buffer = Buffer.from(await response.arrayBuffer());
  process.stdout.write(JSON.stringify({{
    ok: true,
    status: response.status,
    statusText: response.statusText,
    headers,
    bodyBase64: buffer.toString("base64"),
  }}));
}} catch (error) {{
  process.stdout.write(JSON.stringify({{
    ok: false,
    error: error instanceof Error ? error.message : String(error),
  }}));
}}
""".strip()
        result = self._client.nodejs.execute_code(
            code=code,
            timeout=timeout,
        )
        data = result.data
        if data is None:
            raise RuntimeError("Sandbox returned no response for local fetch")
        if data.status != "ok":
            raise RuntimeError(data.stderr or data.stdout or "Sandbox local fetch failed")
        stdout = (data.stdout or "").strip()
        if not stdout:
            raise RuntimeError("Sandbox local fetch returned empty output")
        payload = json.loads(stdout)
        if not payload.get("ok"):
            raise RuntimeError(str(payload.get("error") or "Sandbox local fetch failed"))
        body_base64 = payload.get("bodyBase64", "")
        return {
            "status": int(payload["status"]),
            "status_text": payload.get("statusText") or "",
            "headers": payload.get("headers") or {},
            "body": base64.b64decode(body_base64) if body_base64 else b"",
        }
