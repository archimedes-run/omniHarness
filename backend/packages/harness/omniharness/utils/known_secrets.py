"""Exact-match redaction of the secret values this process has loaded.

Pattern redaction (session_watcher.redaction) only catches RECOGNIZED shapes: a
random 40-character token with no prefix passes straight through it. But the
process knows many of its secrets by value: it read them from `.env`,
config.yaml, the extensions config, the MCP secrets vault and the OAuth
credential stores, and it receives fresh ones every time an OAuth token is
refreshed. Every one of those values is registered here, and `redact()` replaces
each occurrence, in its raw, base64 and URL-encoded forms, before any pattern
pass runs.

What this does NOT do: catch a secret this process never loaded, or one embedded
inside a larger encoded blob (base64 of "user:secret" is not base64 of
"secret"). Those are left to the pattern pass. The limit is stated here, not
implied away.

Values shorter than MIN_LENGTH are not registered: replacing every "true" or
"8001" in a run would garble it without protecting anything.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus, urlsplit

logger = logging.getLogger(__name__)

MARKER = "[redacted]"
MIN_LENGTH = 8

#: A key whose name says it holds a secret: its value is registered whatever it
#: looks like (above MIN_LENGTH).
SECRET_KEY_NAME = re.compile(
    r"(secret|token|passw|pwd|api_?key|apikey|access_?key|private|credential|auth|cookie|session|signature|vault|dsn|webhook|bearer|(^|_)key$|^key)",
    re.IGNORECASE,
)

_BOOL_OR_NUMBER = re.compile(r"^(?:true|false|yes|no|on|off|none|null|[-+]?\d+(?:\.\d+)?)$", re.IGNORECASE)


def encoded_forms(value: str) -> set[str]:
    """The raw value and the encodings a secret commonly travels in."""
    raw = value.encode()
    forms = {value}
    for enc in (base64.b64encode(raw).decode(), base64.urlsafe_b64encode(raw).decode()):
        forms.add(enc)
        forms.add(enc.rstrip("="))
    forms.add(quote(value, safe=""))
    forms.add(quote_plus(value, safe=""))
    forms.add(quote(value))
    return {f for f in forms if len(f) >= MIN_LENGTH}


class KnownSecrets:
    """The process's set of secret values. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sources: dict[str, set[str]] = {}
        self._pattern: re.Pattern[str] | None = None
        self._files: dict[Path, tuple[float, Callable[[Path], Iterable[str]], str]] = {}
        self._last_check = 0.0

    def add(self, value: Any, source: str) -> bool:
        """Register one value. Returns True if it is (now) known."""
        if not isinstance(value, str):
            return False
        value = value.strip()
        if len(value) < MIN_LENGTH:
            return False
        with self._lock:
            known = value in self._sources
            self._sources.setdefault(value, set()).add(source)
            if not known:
                self._pattern = None
        return True

    def add_many(self, values: Iterable[Any], source: str) -> int:
        return sum(1 for v in values if self.add(v, source))

    def count(self) -> int:
        with self._lock:
            return len(self._sources)

    def clear(self) -> None:
        with self._lock:
            self._sources.clear()
            self._files.clear()
            self._pattern = None

    def _compiled(self) -> re.Pattern[str] | None:
        with self._lock:
            if self._pattern is None and self._sources:
                forms: set[str] = set()
                for v in self._sources:
                    forms |= encoded_forms(v)
                # Longest first, so a value never leaves a tail of a longer one.
                alternation = "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True))
                self._pattern = re.compile(alternation)
            return self._pattern

    def redact(self, text: str) -> tuple[str, int]:
        """`text` with every known value (and its encodings) replaced."""
        self.maybe_reload()
        pattern = self._compiled()
        if pattern is None:
            return text, 0
        return pattern.subn(MARKER, text)

    # -- files that change under us (an OAuth CLI refreshes its token file) --

    def watch_file(self, path: Path, loader: Callable[[Path], Iterable[str]], source: str) -> int:
        """Load `path` now and again whenever its mtime changes."""
        path = Path(path)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = -1.0
        with self._lock:
            self._files[path] = (mtime, loader, source)
        return self._load_file(path, loader, source) if mtime >= 0 else 0

    def _load_file(self, path: Path, loader: Callable[[Path], Iterable[str]], source: str) -> int:
        try:
            return self.add_many(loader(path), source)
        except Exception:  # noqa: BLE001 — an unreadable file is skipped, and said so
            logger.warning("known secrets: could not read %s", path.name)
            return 0

    def maybe_reload(self, *, every: float = 5.0) -> None:
        now = time.monotonic()
        if now - self._last_check < every:
            return
        self._last_check = now
        with self._lock:
            files = list(self._files.items())
        for path, (old, loader, source) in files:
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime != old:
                with self._lock:
                    self._files[path] = (mtime, loader, source)
                self._load_file(path, loader, source)


#: The process-wide set. Every loader and refresh hook registers here.
KNOWN_SECRETS = KnownSecrets()


def register_secret(value: Any, source: str) -> None:
    """Hook for code that receives a secret at runtime (e.g. a refreshed token)."""
    try:
        KNOWN_SECRETS.add(value, source)
    except Exception:  # noqa: BLE001 — registering must never break the caller
        logger.exception("known secrets: registering a value failed")


# -- what counts as a secret ---------------------------------------------------


def looks_non_secret(value: str) -> bool:
    """Values that are configuration, not secrets: booleans, numbers, paths,
    and URLs with no credentials in them."""
    v = value.strip()
    if len(v) < MIN_LENGTH or _BOOL_OR_NUMBER.match(v):
        return True
    if v.startswith(("/", "~", "./", "../")):
        return True
    if "://" in v:
        try:
            parts = urlsplit(v)
        except ValueError:
            return False
        return parts.password is None and not parts.query
    return False


def _url_password(value: str) -> str | None:
    if "://" not in value:
        return None
    try:
        return urlsplit(value).password
    except ValueError:
        return None


def secret_values_in(tree: Any, *, env: dict[str, str] | None = None, all_values: bool = False, key: str = "") -> list[str]:
    """Secret values in a parsed config tree.

    A value under a secret-named key always counts. Any other string counts
    unless it looks like plain configuration (`looks_non_secret`), or always
    when `all_values` (a .env file is a file of secrets). `$VAR` references are
    resolved from `env`, as the config loaders do.
    """
    out: list[str] = []
    if isinstance(tree, dict):
        for k, v in tree.items():
            out += secret_values_in(v, env=env, all_values=all_values, key=str(k))
    elif isinstance(tree, list):
        for v in tree:
            out += secret_values_in(v, env=env, all_values=all_values, key=key)
    elif isinstance(tree, str):
        value = tree
        if value.startswith("$") and env is not None:
            value = env.get(value[1:], "")
        if not value:
            return out
        password = _url_password(value)
        if password:
            out.append(password)
        if SECRET_KEY_NAME.search(key) or (all_values and not looks_non_secret(value)) or (not looks_non_secret(value) and _high_entropy(value)):
            out.append(value)
    return out


def _high_entropy(value: str) -> bool:
    """A long token-like string with no spaces and mixed character classes."""
    v = value.strip()
    if len(v) < 20 or any(c.isspace() for c in v):
        return False
    classes = sum(bool(re.search(p, v)) for p in (r"[a-z]", r"[A-Z]", r"\d"))
    return classes >= 2


# -- loaders --------------------------------------------------------------------


def dotenv_secrets(path: Path) -> list[str]:
    from dotenv import dotenv_values

    values = {k: v for k, v in dotenv_values(path).items() if v}
    return secret_values_in(values, all_values=True)


def yaml_secrets(path: Path) -> list[str]:
    import yaml

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return secret_values_in(data, env=dict(os.environ))


def json_secrets(path: Path) -> list[str]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return secret_values_in(data, env=dict(os.environ))


def raw_file_secret(path: Path) -> list[str]:
    return [Path(path).read_text(encoding="utf-8").strip()]


def environ_secrets(environ: dict[str, str] | None = None) -> list[str]:
    """Process environment values under secret-named variables."""
    env = os.environ if environ is None else environ
    return [v for k, v in env.items() if v and SECRET_KEY_NAME.search(k) and not looks_non_secret(v)]


def _dotenv_paths() -> list[Path]:
    from dotenv import find_dotenv

    found = {p for p in (find_dotenv(usecwd=True),) if p}
    for parent in Path(__file__).resolve().parents[:6]:
        candidate = parent / ".env"
        if candidate.is_file():
            found.add(str(candidate))
    return [Path(p) for p in sorted(found)]


def load_process_secrets(*, registry: KnownSecrets = KNOWN_SECRETS) -> dict[str, int]:
    """Register every secret this process can load from disk and its environment.

    Called at gateway startup. Returns how many values each source gave, never
    the values. A source that cannot be read gives 0 and a warning.
    """
    counts: dict[str, int] = {}
    counts["environment"] = registry.add_many(environ_secrets(), "environment")
    for path in _dotenv_paths():
        counts[f".env:{path.parent.name}"] = registry.watch_file(path, dotenv_secrets, ".env")
    try:
        from omniharness.config.app_config import AppConfig

        config_path = AppConfig.resolve_config_path()
        counts["config.yaml"] = registry.watch_file(Path(config_path), yaml_secrets, "config.yaml")
    except Exception:  # noqa: BLE001
        logger.warning("known secrets: config.yaml could not be located")
    try:
        from omniharness.config.extensions_config import ExtensionsConfig

        ext = ExtensionsConfig.resolve_config_path()
        if ext is not None:
            counts["extensions"] = registry.watch_file(Path(ext), json_secrets, "extensions config")
    except Exception:  # noqa: BLE001
        logger.warning("known secrets: the extensions config could not be located")
    for label, path, loader in _credential_files():
        counts[label] = registry.watch_file(path, loader, label)
    return counts


def _credential_files() -> list[tuple[str, Path, Callable[[Path], Iterable[str]]]]:
    """OAuth credential stores on disk, watched so a refresh by their CLI is seen."""
    from omniharness.models.credential_loader import _iter_claude_code_credential_paths, _resolve_credential_path

    files: list[tuple[str, Path, Callable[[Path], Iterable[str]]]] = [("claude-code-oauth", p, json_secrets) for p in _iter_claude_code_credential_paths()]
    files.append(("codex-oauth", _resolve_credential_path("CODEX_AUTH_PATH", ".codex/auth.json"), json_secrets))
    files.append(("mcp-vault-dev-key", Path(".omni-harness/dev_vault.key"), raw_file_secret))
    return files
