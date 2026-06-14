"""Generalized Python source-code security scanner.

Provides :func:`scan_python_code` for screening any agent-generated Python
before it executes, regardless of whether it originates from a skill or an
MCP server build.

Two-stage pipeline
------------------
1. **Static pre-filter** — regex patterns that immediately return ``"block"``
   for obviously dangerous constructs (subprocess, os.system, eval, exec, …).
   Tests rely on this path; it never needs an LLM.
2. **LLM scan** — same rubric as :mod:`omniharness.skills.security_scanner` for
   borderline cases. If the model call fails, the fallback is ``"block"``
   (fail-closed).

The existing :func:`omniharness.skills.security_scanner.scan_skill_content`
delegates to this function for its executable-code path.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ScanResult:
    decision: str  # "allow" | "warn" | "block"
    reason: str


# ---------------------------------------------------------------------------
# Static patterns — block without LLM
# ---------------------------------------------------------------------------

_STATIC_BLOCK: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bsubprocess\b"), "subprocess usage is not permitted in MCP server code"),
    (re.compile(r"\bos\.system\s*\(|\bos\.popen\s*\(|\bos\.exec"), "os shell execution is not permitted"),
    (re.compile(r"\beval\s*\("), "eval() usage is not permitted"),
    (re.compile(r"\bexec\s*\("), "exec() usage is not permitted"),
    (re.compile(r"\b__import__\s*\("), "__import__() usage is not permitted"),
    (re.compile(r"\bpickle\b"), "pickle deserialization is not permitted"),
    (re.compile(r"\bctypes\b"), "ctypes usage is not permitted"),
    (
        re.compile(r"base64\.b64decode.*(?:exec|eval)", re.DOTALL),
        "base64-decode-then-execute pattern detected",
    ),
]

# ---------------------------------------------------------------------------
# os.getenv key extraction
# ---------------------------------------------------------------------------

_GETENV_RE = re.compile(r"""os\.getenv\(\s*['"]([A-Z_][A-Z0-9_]*)['"]""")

# Env-var name suffixes that are config/tuning knobs, not credentials.
# These are excluded from the "required secrets" list shown in the UI.
_CONFIG_SUFFIX_RE = re.compile(
    r"_(LOG_LEVEL|DEBUG|VERBOSE|ENV|MODE|ENVIRONMENT|DIR|PATH|PORT|HOST|TIMEOUT|"
    r"LIMIT|MAX|MIN|SIZE|FORMAT|ENCODING|CHARSET|LOCALE|LANG|TZ|TIMEZONE|WORKERS|"
    r"THREADS|CONCURRENCY|RETRY|RETRIES|INTERVAL|ENABLED|DISABLED|FLAG)$"
)


def extract_env_keys(source_code: str) -> list[str]:
    """Return deduplicated list of credential env-var names referenced via os.getenv("KEY").

    Config/tuning knobs (LOG_LEVEL, DEBUG, MODE, DIR, PORT, …) are excluded —
    only names that look like secrets or API keys are returned.
    """
    keys = list(dict.fromkeys(_GETENV_RE.findall(source_code)))
    return [k for k in keys if not _CONFIG_SUFFIX_RE.search(k)]


# ---------------------------------------------------------------------------
# Public scanner
# ---------------------------------------------------------------------------


def scan_python_code_static(source: str) -> ScanResult | None:
    """Run only the static pre-filter patterns.

    Returns a ``ScanResult("block", reason)`` if a known-dangerous pattern is
    found, or ``None`` if the static stage passes (caller should continue to
    the LLM stage).  Never makes network calls.
    """
    for pattern, reason in _STATIC_BLOCK:
        if pattern.search(source):
            return ScanResult("block", reason)
    return None


async def scan_python_code(
    source: str,
    *,
    location: str = "<generated>",
    egress_hosts: list[str] | None = None,
    app_config=None,
) -> ScanResult:
    """Screen agent-generated Python source before execution.

    Static patterns are checked first — they return immediately without an LLM
    call, keeping tests fast and offline-capable.

    ``egress_hosts`` should be the server's declared external hosts so the LLM
    reviewer can distinguish a normal API connector (calling its own declared
    endpoint with its own API key) from genuine exfiltration to undeclared hosts.
    """
    # Stage 1: static fast-path
    for pattern, reason in _STATIC_BLOCK:
        if pattern.search(source):
            logger.info("Static security block at %s: %s", location, reason)
            return ScanResult("block", reason)

    # Stage 2: LLM scan for borderline cases
    try:
        from omniharness.config import get_app_config
        from omniharness.models import create_chat_model
        from omniharness.skills.security_scanner import _extract_json_object

        config = app_config or get_app_config()
        model_name = getattr(getattr(config, "skill_evolution", None), "moderation_model_name", None)
        model = create_chat_model(name=model_name, thinking_enabled=False, app_config=config) if model_name else create_chat_model(thinking_enabled=False, app_config=config)

        if egress_hosts:
            hosts_str = ", ".join(egress_hosts)
            rubric = (
                "You are a security reviewer for AI-generated MCP server connector code. "
                f"This server declares the following allowed egress hosts: {hosts_str}. "
                "Classify as allow, warn, or block. "
                "ALLOW: code that calls only its declared host(s) using its own API credentials "
                "for authentication, or that processes user-supplied inputs sent to declared hosts. "
                "Passing an API key in an HTTP header or query parameter to a declared host is "
                "NORMAL and ALWAYS allowed — this is standard API authentication, not exfiltration. "
                "BLOCK: (1) code that reads credentials and sends them to undeclared hosts; "
                "(2) code that exfiltrates data to hosts not in the declared list; "
                "(3) obfuscated/base64-encoded payloads hiding exfiltration destinations; "
                "(4) shell injection, spawned processes, reverse shells, or dynamic code execution. "
                "Default posture for an API connector calling only declared hosts: allow. "
                'Return strict JSON: {"decision":"allow|warn|block","reason":"..."}.'
            )
        else:
            rubric = (
                "You are a security reviewer for AI-generated MCP server code. "
                "Classify as allow, warn, or block. "
                "ALLOW: standard API integrations using httpx or requests; reading secrets via "
                "os.getenv for use with declared APIs is normal and allowed. "
                "BLOCK: prompt-injection, privilege escalation, exfiltration to arbitrary or "
                "undeclared hosts, dangerous shell invocation, crypto mining, reverse shells, "
                "or code that reads credentials and sends them to unexpected destinations. "
                'Return strict JSON: {"decision":"allow|warn|block","reason":"..."}.'
            )

        prompt = f"Location: {location}\n\nReview this Python code:\n-----\n{source}\n-----"
        response = await model.ainvoke(
            [{"role": "system", "content": rubric}, {"role": "user", "content": prompt}],
            config={"run_name": "mcp_security_scan"},
        )
        raw = getattr(response, "content", "") or ""
        # Reasoning models (e.g. via Responses API) return content as a list of typed
        # blocks; str() on a list yields Python repr, not valid JSON.
        if isinstance(raw, list):
            raw = " ".join(b.get("text", "") for b in raw if isinstance(b, dict) and b.get("type") == "text").strip()
        parsed = _extract_json_object(str(raw))
        if parsed and parsed.get("decision") in {"allow", "warn", "block"}:
            return ScanResult(parsed["decision"], str(parsed.get("reason") or "No reason provided."))
    except Exception:
        logger.warning("MCP code security scan model call failed; using conservative fallback", exc_info=True)

    return ScanResult("block", "Security scan unavailable; manual review required before execution.")
