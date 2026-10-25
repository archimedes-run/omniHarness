"""OpenCode's `run --format json` events, turned into the job's steps.

Statuses and exit codes come from the event stream (the bash tool's
`metadata.exit`), never from the worker's prose (FR-044). Everything here is
untrusted content from the sandbox: text is redacted and made one-line-safe
before it is stored, and capped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.gateway.display_redaction import for_display
from app.gateway.display_safe import safe_field

FILE_TOOLS = {"write": "wrote", "edit": "edited", "multiedit": "edited", "patch": "patched", "apply_patch": "patched"}
_TEST_RE = re.compile(r"\b(npm (run )?test|pnpm (run )?test|yarn test|vitest|jest|pytest|python -m pytest|go test|cargo test|npm run test:\S+)\b")
_BUILD_RE = re.compile(r"\b(npm run build|pnpm (run )?build|yarn build|vite build|tsc( |$)|next build|cargo build|go build|make\b)")
_PERMISSION_RE = re.compile(r"permission requested: ([^\n]{0,200})")


def _shown(text: object, limit: int) -> str:
    raw = str(text or "")
    if len(raw) > limit:
        raw = raw[: limit // 2] + "\n…\n" + raw[-limit // 2 :]
    out, _ = for_display(raw)
    return out


def _one_line(text: object, limit: int = 300) -> str:
    return safe_field(_shown(text, limit))[:limit]


@dataclass
class Tally:
    """What the stream showed, for the result's evidence."""

    commands: list[dict] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    tokens_in: int = 0
    tokens_out: int = 0
    last_text: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def tests(self) -> list[dict]:
        return [c for c in self.commands if c.get("is_test")]

    @property
    def builds(self) -> list[dict]:
        return [c for c in self.commands if c.get("is_build")]


def _rel(path: str, workspace: str) -> str:
    return path[len(workspace) + 1 :] if path.startswith(workspace + "/") else path


def to_step(event: dict, tally: Tally, *, workspace: str = "/mnt/user-data/workspace") -> tuple[str, dict] | None:
    """(kind, data) for one event, or None for events that are not steps."""
    etype = event.get("type")
    part = event.get("part") if isinstance(event.get("part"), dict) else {}
    if etype == "tool_use":
        tool = str(part.get("tool") or "")
        state = part.get("state") if isinstance(part.get("state"), dict) else {}
        status = str(state.get("status") or "")
        inp = state.get("input") if isinstance(state.get("input"), dict) else {}
        meta = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
        if tool in ("bash", "shell"):
            command = str(inp.get("command") or "")
            exit_code = meta.get("exit") if isinstance(meta.get("exit"), int) else None
            if status == "error":
                exit_code = exit_code if exit_code is not None else None
            data = {
                "command": _one_line(command, 500),
                "exit_code": exit_code,
                "status": "ok" if status == "completed" and exit_code == 0 else ("error" if status == "error" or (exit_code not in (None, 0)) else "unknown"),
                "output": _shown(meta.get("output") if meta.get("output") is not None else state.get("output") or state.get("error") or "", 4000),
                "is_test": bool(_TEST_RE.search(command)),
                "is_build": bool(_BUILD_RE.search(command)),
            }
            tally.commands.append({k: data[k] for k in ("command", "exit_code", "status", "is_test", "is_build")})
            return "command", data
        if tool in FILE_TOOLS:
            path = str(inp.get("filePath") or inp.get("path") or meta.get("filepath") or "")
            rel = _one_line(_rel(path, workspace), 400)
            if status == "completed" and rel:
                tally.files[rel] = FILE_TOOLS[tool]
            return "file", {"action": FILE_TOOLS[tool], "path": rel, "status": "ok" if status == "completed" else "error", "error": _one_line(state.get("error") or "", 400) if status == "error" else None}
        title = state.get("title") or inp.get("filePath") or inp.get("pattern") or inp.get("path") or ""
        return "tool", {"tool": _one_line(tool, 60), "title": _one_line(_rel(str(title), workspace), 300), "status": "ok" if status == "completed" else "error"}
    if etype == "text":
        text = str(part.get("text") or "").strip()
        if not text:
            return None
        tally.last_text = text
        return "message", {"text": _shown(text, 6000)}
    if etype == "step_finish":
        tok = part.get("tokens") if isinstance(part.get("tokens"), dict) else {}
        tally.tokens_in += int(tok.get("input") or 0)
        tally.tokens_out += int(tok.get("output") or 0)
        return None
    if etype == "error":
        err = event.get("error")
        message = ""
        if isinstance(err, dict):
            data = err.get("data") if isinstance(err.get("data"), dict) else {}
            message = str(data.get("message") or err.get("name") or "")
        else:
            message = str(err or "")
        shown = _one_line(message or "the worker reported an error", 600)
        tally.errors.append(shown)
        return "error", {"message": shown}
    return None


def permission_prompt(stderr: str) -> str | None:
    """OpenCode's run mode auto-rejects a permission prompt and says so on
    stderr; D6: if one appears anyway, the job fails with a clear reason."""
    m = _PERMISSION_RE.search(stderr or "")
    return _one_line(m.group(1), 200) if m else None
