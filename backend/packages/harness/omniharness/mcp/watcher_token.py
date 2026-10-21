"""The session-watcher's shared token (security baseline): REQUIRED, never optional.

The watcher refuses every request without it. The token lives in one file,
``~/.omni-harness-secrets/watcher.token`` (0600, in a 0700 directory), created
on first start (``scripts/ensure-watcher-token.sh``, run by `make daily` and
deploy.sh, or the watcher itself when run on the host). Compose mounts it
read-only into the watcher and the gateway as /run/secrets/watcher.token
(``OMNI_HARNESS_WATCHER_TOKEN_FILE``). The gateway sends it automatically to
the MCP server named ``session-watcher``: nothing goes in .env or
extensions_config.json, and it is never logged.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

WATCHER_SERVER_NAME = "session-watcher"
TOKEN_FILE_ENV = "OMNI_HARNESS_WATCHER_TOKEN_FILE"
TOKEN_HEADER = "X-OmniHarness-Watcher-Token"


def token_path() -> Path:
    configured = os.environ.get(TOKEN_FILE_ENV, "").strip()
    return Path(configured) if configured else Path.home() / ".omni-harness-secrets" / "watcher.token"


def read_watcher_token(path: Path | None = None) -> str | None:
    try:
        value = (path or token_path()).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def ensure_watcher_token(path: Path | None = None) -> str:
    """Create the token file (0600, directory 0700) if it is missing; return the token."""
    target = path or token_path()
    existing = read_watcher_token(target)
    if existing:
        return existing
    target.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(target.parent, 0o700)
    token = secrets.token_urlsafe(32)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(token + "\n")
    return token


def watcher_headers(server_name: str, headers: dict[str, str] | None = None) -> dict[str, str]:
    """``headers`` plus the watcher token, for the server named session-watcher."""
    out = dict(headers or {})
    if server_name == WATCHER_SERVER_NAME and TOKEN_HEADER not in out:
        token = read_watcher_token()
        if token:
            out[TOKEN_HEADER] = token
    return out
