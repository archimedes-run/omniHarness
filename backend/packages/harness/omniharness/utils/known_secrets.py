"""Exact-match redaction of the secret values this process has loaded.

Pattern redaction (session_watcher.redaction) only catches RECOGNIZED shapes: a
random 40-character token with no prefix passes straight through it. But the
process knows many of its secrets by value: it read them from `.env`,
config.yaml, the extensions config, the MCP secrets vault and the OAuth
credential stores, and it receives fresh ones every time an OAuth token is
refreshed. Every one of those values is registered here, and `redact()` replaces
each occurrence before any pattern pass runs. It matches:

  * the value in any letter case;
  * with any of its characters JSON-escaped (\\uXXXX, \\/) or percent-encoded
    (either hex case), so URL-, form- and JSON-encoded copies, and mixtures;
  * as hex (either case);
  * as base64 and base64url at all three byte alignments, so the value is found
    inside a larger encoded body (a mail, a header), with or without padding;
  * as base64 wrapped over several lines (MIME, 76 columns): a base64 block
    that contains a known value once its line breaks are removed is replaced
    whole.

WHAT IT STILL CANNOT CATCH, stated rather than implied away: a secret this
process never loaded; one compressed, encrypted, hashed or transformed in any
way other than the encodings above (gzip, rot13, reversed, split by other
text); one split across separate strings (the run store joins content parts
for this, see store.redact_tree); one encoded twice. Those are left to the
pattern pass, which has its own stated limits.

LENGTH FLOOR, decided. A value under SECRET_MIN (4) characters is never
registered: "1" or "abc" would be replaced everywhere and protect nothing. A
value of 4 to 7 characters is registered only when it is KNOWN to be a secret
(a secret-named key such as PIN or PASS, or an explicit register_secret hook),
and is then matched only as a whole word, raw, never inside a longer token and
never in encoded forms: "483920" is redacted where it stands alone, not inside
"2483920". Any other value must be at least MIN_LENGTH (8) characters and look
like a secret (see `secret_values_in`).
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
from urllib.parse import quote, urlsplit

logger = logging.getLogger(__name__)

MARKER = "[redacted]"
#: Values not known to be secrets must be at least this long.
MIN_LENGTH = 8
#: Nothing shorter is ever registered (see the module docstring).
SECRET_MIN = 4

#: A key whose name says it holds a secret: its value is registered whatever its
#: shape (numbers included), from SECRET_MIN characters.
SECRET_KEY_NAME = re.compile(
    r"(secret|token|pass|pwd|(^|_)pin($|_)|otp|cvv|api_?key|apikey|access_?key|private|credential|auth|cookie|session|signature|vault|dsn|webhook|bearer|(^|_)key$|^key)",
    re.IGNORECASE,
)

_BOOL_OR_NUMBER = re.compile(r"^(?:true|false|yes|no|on|off|none|null|[-+]?\d+(?:\.\d+)?)$", re.IGNORECASE)


def _char_pattern(c: str) -> str:
    """One character: literal, JSON-escaped, or percent-encoded."""
    alts = [re.escape(c), re.escape(f"\\u{ord(c):04x}") if ord(c) < 0x10000 else None]
    pct = quote(c, safe="")
    if pct != c:
        alts.append(re.escape(pct))
    if c == "/":
        alts.append(re.escape("\\/"))
    if c == " ":
        alts.append(re.escape("+"))
    alts = [a for a in alts if a]
    return alts[0] if len(alts) == 1 else "(?:" + "|".join(alts) + ")"


def _b64_segments(raw: bytes) -> set[str]:
    """The base64/base64url characters fixed by `raw` alone, at each of the
    three byte alignments it can start at inside a larger body."""
    out: set[str] = set()
    for k in range(3):
        padded = b"\0" * k + raw
        start, stop = (8 * k + 5) // 6, (8 * len(padded)) // 6
        for enc in (base64.b64encode(padded).decode(), base64.urlsafe_b64encode(padded).decode()):
            seg = enc[start:stop]
            if len(seg) >= MIN_LENGTH:
                out.add(seg)
    return out


def value_pattern(value: str) -> str:
    """The regex source matching `value` in every supported form."""
    if len(value) < MIN_LENGTH:
        return r"(?<![A-Za-z0-9])" + re.escape(value) + r"(?![A-Za-z0-9])"
    flex = "".join(_char_pattern(c) for c in value)
    literal = sorted({value.encode().hex()} | _b64_segments(value.encode()), key=len, reverse=True)
    return "|".join([flex, *(re.escape(f) for f in literal)])


#: How many layers of encoding are undone to look for a known value.
VIEW_DEPTH = 2


def _direct_pass(text: str, pattern: re.Pattern[str]) -> tuple[str, int]:
    out, n = pattern.subn(MARKER, text)

    if "\n" not in out:
        return out, n
    out, m = _wrapped_blocks(out, pattern)
    return out, n + m


_B64_FULL = re.compile(r"[A-Za-z0-9+/_=-]{4,}")
_B64_TRAIL = re.compile(r"[A-Za-z0-9+/_=-]{8,}$")
_B64_LEAD = re.compile(r"^[A-Za-z0-9+/_=-]{4,}")


def _wrapped_blocks(text: str, pattern: re.Pattern[str]) -> tuple[str, int]:
    """Base64 wrapped over lines (MIME): a block that starts with a line's
    trailing base64 token, runs through whole base64 lines, and ends with the
    next line's leading token. When the block, joined, holds a known value,
    the block is replaced. Linear in the text (a line-by-line scan, not a
    backtracking regex over the whole text)."""
    lines = text.split("\n")
    stripped = [ln.rstrip("\r").strip() for ln in lines]
    full = [bool(_B64_FULL.fullmatch(s)) for s in stripped]
    out: list[str] = []
    n, i = 0, 0
    while i < len(lines):
        trail = _B64_TRAIL.search(stripped[i]) if i < len(lines) - 1 else None
        if trail:
            j = i + 1
            while j < len(lines) and full[j]:
                j += 1
            lead = _B64_LEAD.match(stripped[j]) if j < len(lines) else None
            last = j if lead else j - 1
            if last > i:
                joined = trail.group(0) + "".join(stripped[i + 1 : j]) + (lead.group(0) if lead else "")
                if pattern.search(joined):
                    # The whole block becomes one marker, on one line.
                    n += 1
                    out.append(stripped[i][: trail.start()] + MARKER + (stripped[j][lead.end() :] if lead else ""))
                    i = last + 1
                    continue
        out.append(lines[i])
        i += 1
    return ("\n".join(out), n) if n else (text, 0)


_JSON_ESCAPE = re.compile(r"\\(u[0-9a-fA-F]{4}|[nrtbf/\\\"])")
_JSON_SIMPLE = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "/": "/", "\\": "\\", '"': '"'}


def _json_unescape(text: str) -> str:
    return _JSON_ESCAPE.sub(lambda m: chr(int(m.group(1)[1:], 16)) if m.group(1)[0] == "u" else _JSON_SIMPLE[m.group(1)], text)


def _percent_decode(text: str) -> str:
    from urllib.parse import unquote

    return unquote(text) if "%" in text else text


_QP = re.compile(r"=(?:\r?\n|([0-9A-Fa-f]{2}))")


def _qp_decode(text: str) -> str:
    return _QP.sub(lambda m: chr(int(m.group(1), 16)) if m.group(1) else "", text) if "=" in text else text


def _html_unescape(text: str) -> str:
    import html

    return html.unescape(text) if "&" in text else text


_VIEWS = (_json_unescape, _percent_decode, _qp_decode, _html_unescape)


class KnownSecrets:
    """The process's set of secret values. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sources: dict[str, set[str]] = {}
        self._pattern: re.Pattern[str] | None = None
        self._files: dict[Path, tuple[float, Callable[[Path], Iterable[str]], str]] = {}
        self._last_check = 0.0

    def add(self, value: Any, source: str) -> bool:
        """Register one KNOWN secret (from SECRET_MIN characters). Callers that
        are guessing (a config value under an ordinary key) apply MIN_LENGTH
        themselves; see `secret_values_in`."""
        if not isinstance(value, str):
            return False
        value = value.strip()
        if len(value) < SECRET_MIN:
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
                # Longest first, so a value never leaves a tail of a longer one.
                values = sorted(self._sources, key=len, reverse=True)
                self._pattern = re.compile("|".join(f"(?:{value_pattern(v)})" for v in values), re.IGNORECASE)
            return self._pattern

    def redact(self, text: str) -> tuple[str, int]:
        """`text` with every known value, in every supported form, replaced.

        Then DECODED VIEWS, to a depth of two layers: JSON string escapes,
        percent-encoding, quoted-printable and HTML entities. When a view still
        holds a known value (a PIN after `\\n` or `%3D`, base64 that was then
        URL-encoded, MIME base64 whose line breaks are the JSON text `\\r\\n`),
        the redacted VIEW is returned in place of the text: its escaping
        changes, its words do not, and the secret does not survive."""
        self.maybe_reload()
        pattern = self._compiled()
        if pattern is None:
            return text, 0
        return self._redact_views(text, pattern, VIEW_DEPTH)

    def _redact_views(self, text: str, pattern: re.Pattern[str], depth: int) -> tuple[str, int]:
        out, n = _direct_pass(text, pattern)
        if depth <= 0:
            return out, n
        for decode in _VIEWS:
            try:
                view = decode(out)
            except Exception:  # noqa: BLE001 — an undecodable view has nothing to find
                continue
            if view == out:
                continue
            red, m = self._redact_views(view, pattern, depth - 1)
            if m:
                out, n = red, n + m
        return out, n

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

    def maybe_reload(self, *, every: float = 0.0) -> None:
        """Reload watched files whose mtime changed. A stat per file per call:
        cheap, and a token a CLI refreshed a moment ago is known at once."""
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


#: Words that, anywhere in a secret-named key, make it a SETTING about the
#: secret (a timeout, a URL, a path, a flag, a model's max_tokens), not one.
NOT_SECRET_KEY_WORDS = frozenset("timeout ttl seconds minutes hours days port size count length limit max min expiry expires expiration url uri path file dir name enabled id type mode header field".split())


def _key_words(key: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    return [w for w in re.split(r"[_\-.\s]+", spaced.lower()) if w]


_FLAG_WORD = re.compile(r"^(?:true|false|yes|no|on|off|none|null)$", re.IGNORECASE)


#: A key naming a webhook: the URL IS the credential (Slack, Discord and most
#: alerting hooks carry their secret in the path), so `url` does not exclude it.
_HOOK_KEY = re.compile(r"(web)?hook", re.IGNORECASE)


def is_secret_key(key: str) -> bool:
    if _HOOK_KEY.search(key):
        return True
    return bool(SECRET_KEY_NAME.search(key)) and not NOT_SECRET_KEY_WORDS.intersection(_key_words(key))


def url_secret_parts(value: str) -> list[str]:
    """A URL's path segments that look like credentials (16+ characters,
    token-like): a webhook's secret path, a capability URL's key."""
    if "://" not in value:
        return []
    try:
        path = urlsplit(value).path
    except ValueError:
        return []
    return [seg for seg in path.split("/") if len(seg) >= 16 and _token_like(seg)]


def _token_like(v: str) -> bool:
    if any(c.isspace() for c in v):
        return False
    return sum(bool(re.search(p, v)) for p in (r"[a-z]", r"[A-Z]", r"\d")) >= 2


def secret_values_in(tree: Any, *, env: dict[str, str] | None = None, all_values: bool = False, key: str = "") -> list[str]:
    """Secret values in a parsed config tree.

    A value under a secret-named key (`is_secret_key`) always counts, numbers
    included, from SECRET_MIN characters, unless it is a flag word or a path.
    Any other string counts only from MIN_LENGTH characters and unless it
    looks like plain configuration (`looks_non_secret`); under `all_values` (a
    .env file is a file of secrets) that is enough, otherwise it must also look
    like a token. `$VAR` references are resolved from `env`, as the config
    loaders do.
    """
    out: list[str] = []
    if isinstance(tree, dict):
        for k, v in tree.items():
            out += secret_values_in(v, env=env, all_values=all_values, key=str(k))
    elif isinstance(tree, list):
        for v in tree:
            out += secret_values_in(v, env=env, all_values=all_values, key=key)
    elif isinstance(tree, (int, float)) and not isinstance(tree, bool):
        if is_secret_key(key) and len(str(tree)) >= SECRET_MIN:
            out.append(str(tree))
    elif isinstance(tree, str):
        value = tree
        if value.startswith("$") and env is not None:
            value = env.get(value[1:], "")
        value = value.strip()
        if not value:
            return out
        password = _url_password(value)
        if password:
            out.append(password)
        # A URL with a credential in its path: the segment AND the whole URL.
        secret_segments = url_secret_parts(value)
        if secret_segments:
            out += [*secret_segments, value]
        if _HOOK_KEY.search(key) and "://" in value:
            out.append(value)
        elif is_secret_key(key):
            if len(value) >= SECRET_MIN and not _FLAG_WORD.match(value) and not value.startswith(("/", "~", "./", "../")) and not (("://" in value) and looks_non_secret(value)):
                out.append(value)
        elif (all_values and not looks_non_secret(value)) or (not looks_non_secret(value) and _high_entropy(value)):
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
    return secret_values_in({k: v for k, v in env.items() if v and is_secret_key(k)})


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
