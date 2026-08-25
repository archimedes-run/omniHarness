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
    # --- widened for feature 002 (FR-008c) --------------------------------
    # Agent-composed output carries shapes session records did not. The wording
    # below does NOT strengthen: these remain RECOGNIZED patterns, and
    # unrecognized shapes still pass through (FR-008d).
    ("gcp-service-account", re.compile(r'"type"\s*:\s*"service_account"')),
    ("gcp-api-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
    ("openai-project-key", re.compile(r"\bsk-proj-[A-Za-z0-9_\-]{16,}\b")),
    ("private-key-header", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("basic-auth-header", re.compile(r"\bBasic\s+[A-Za-z0-9+/]{16,}={0,2}")),
    (
        "secretish-assignment",
        re.compile(
            r"\b([A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API_?KEY|ACCESS_?KEY)[A-Z0-9_]*)\s*[=:]\s*[\"']?([^\s\"',]{6,})",
        ),
    ),
    # --- widened for feature 003 (FR-022) ---------------------------------
    # Email bodies and web pages are WIDER AND LESS STRUCTURED than anything
    # earlier features handled. Session records are machine-written and agent
    # output is prose the assistant composed; both are narrow next to arbitrary
    # human correspondence and arbitrary HTML.
    #
    # The shapes below appear in that material and did not appear in the
    # earlier two. Every one is still a RECOGNIZED pattern — the wording does
    # not strengthen, and unrecognized shapes still pass through (FR-008d).
    # This reduces exposure; it does not make a guarantee.
    #
    # Widened HERE, in the redactor's own module, so its own suite covers it
    # and a change made for Feature 003 cannot silently weaken 001 or 002.
    #
    # A password reset or "here is your login" mail, verbatim in a reply.
    ("reset-link", re.compile(r"https?://[^\s<>\"']*(?:reset|verify|confirm|activate|magic|invite)[^\s<>\"']*[?&](?:token|key|code|t|k)=[A-Za-z0-9._\-]{12,}", re.IGNORECASE)),
    # Any URL carrying a credential-shaped query parameter. Web pages are full
    # of these and a session record essentially never contains one.
    # `#` as well as `?&`: OAuth implicit flow returns the token in the URL
    # FRAGMENT, which is the single most common way one ends up pasted into a
    # page the assistant then reads back.
    ("url-credential-param", re.compile(r"[?&#](?:access_token|id_token|refresh_token|api_?key|apikey|auth|password|signature|sig)=[A-Za-z0-9%._\-]{8,}", re.IGNORECASE)),
    # A one-time code quoted back from a mail. Deliberately requires the
    # surrounding words: a bare 6-digit number is a year, a price, or a room.
    ("one-time-code", re.compile(r"\b(?:one[- ]?time|verification|security|auth(?:entication)?|login|access|confirmation)\s+code(?:\s+is)?[:\s]+\b\d{4,8}\b", re.IGNORECASE)),
    # Stripe and similar live keys, which turn up in receipts and dashboards.
    ("stripe-live-key", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}\b")),
    # Payment card numbers in a receipt body. Luhn is not checked — this is a
    # shape match, and over-matching a 16-digit order number is the acceptable
    # direction.
    ("card-number", re.compile(r"\b(?:\d[ -]?){13,19}\b(?=[^\d]|$)")),
    # Cookie and Set-Cookie headers, which a page fetch can surface verbatim.
    ("cookie-header", re.compile(r"\b(?:Set-)?Cookie:\s*[^\s;]{8,}", re.IGNORECASE)),
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
    """Redact for a channel. Raises RedactionError; callers must fail closed.

    THERE IS DELIBERATELY NO `if text is None` GUARD. One existed and was
    removed: mypy reported it unreachable (the parameter is `str`), and tracing
    every caller confirmed nothing passes None —

        release.py         merge() returns str, explicitly "" when empty
        server.py          raw = summary.text if summary else "", and
                           Summary.text is typed str
        wiring.py          passes through from release.py

    — in production or in tests.

    But dead was not the worst of it. The guard returned "", which reads
    downstream as "successfully redacted to nothing" and DELIVERS. Without it,
    a None falls into the broad handler below, becomes a RedactionError, and
    `redact_or_suppress` suppresses the message. On a security path those are
    opposite outcomes, and the guard was short-circuiting the safe one.
    """
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
