"""Channel-aware redaction (FR-011c-f).

Four properties, each chosen against a specific failure:

  * It runs on EVERY channel, local included. A filter exercised only on the
    remote path is one whose bugs debut in front of the least recoverable
    audience. Channel governs aggressiveness, not whether it runs.
  * It removes RECOGNIZED PATTERNS, and every surface says exactly that and no
    more. The stronger claim is one pattern matching cannot honour, and making
    it would be the fake precision Article X names as a defect (FR-011d).
    Unrecognized shapes pass through; that limit is stated, not implied.
  * It FAILS CLOSED. If redaction errors, the caller suppresses the send. There
    is no path where an error results in unredacted content going out.
  * Redactions are VISIBLE. A silently dropped credential yields a message that
    reads as complete but is not — the same false-confidence failure as an empty
    registry rendering as "no sessions running".
"""

from __future__ import annotations

import re
from enum import StrEnum

MARKER = "[redacted]"


class Channel(StrEnum):
    LOCAL = "local"
    REMOTE = "remote"


class RedactionError(RuntimeError):
    """Redaction could not be completed. The caller MUST suppress the send."""


# Recognized shapes. Not an assertion that secrets take only these shapes.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("api-key", re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{16,}\b")),
    ("aws-key-id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b")),
    ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{12,}")),
    ("uri-credentials", re.compile(r"\b([a-zA-Z][\w+.-]*)://[^\s:/@]+:[^\s/@]+@")),
    ("pem-block", re.compile(r"-----BEGIN[^-]{0,40}PRIVATE KEY-----.*?-----END[^-]{0,40}PRIVATE KEY-----", re.DOTALL)),
    (
        "secretish-assignment",
        re.compile(
            r"\b([A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API_?KEY|ACCESS_?KEY)[A-Z0-9_]*)\s*[=:]\s*[\"']?([^\s\"',]{6,})",
        ),
    ),
)

# Remote-only reduction (FR-011c, SC-004m).
_ABS_PATH = re.compile(r"(/(?:Users|home)/[^/\s]+)((?:/[^\s,;:)\]}\"']+)*)")
_FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)


def _apply_patterns(text: str) -> tuple[str, list[str]]:
    hits: list[str] = []
    for name, pat in _PATTERNS:

        def _sub(m: re.Match[str], _name: str = name) -> str:
            hits.append(_name)
            if _name == "uri-credentials":
                return f"{m.group(1)}://{MARKER}@"
            if _name == "secretish-assignment":
                return f"{m.group(1)}={MARKER}"
            if _name == "bearer":
                return f"Bearer {MARKER}"
            return MARKER

        text = pat.sub(_sub, text)
    return text, hits


def _shorten_paths(text: str) -> str:
    def _sub(m: re.Match[str]) -> str:
        tail = m.group(2) or ""
        leaf = tail.rsplit("/", 1)[-1] if tail else ""
        return f"~/…/{leaf}" if leaf else "~"

    return _ABS_PATH.sub(_sub, text)


def redact(text: str, channel: Channel = Channel.LOCAL) -> str:
    """Redact for a channel. Raises RedactionError; callers must fail closed."""
    if text is None:
        return ""
    try:
        out, _ = _apply_patterns(text)
        if channel is Channel.REMOTE:
            out = _FENCED_CODE.sub(" [code] ", out)
            out = _shorten_paths(out)
        return out
    except RedactionError:
        raise
    except Exception as exc:  # noqa: BLE001 — any failure must fail closed
        raise RedactionError(f"redaction failed: {exc}") from exc


def redact_or_suppress(text: str, channel: Channel = Channel.LOCAL) -> tuple[str, bool]:
    """Return (text, ok). On failure returns the can't-relay line and ok=False.

    FR-011e: the reply is suppressed rather than sent unredacted. There is no
    third option, and in particular no "send it anyway with a warning".
    """
    try:
        return redact(text, channel), True
    except RedactionError:
        return "can't safely relay this, check locally", False
