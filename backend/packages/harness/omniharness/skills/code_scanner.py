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


def extract_env_keys(source_code: str) -> list[str]:
    """Return deduplicated list of env-var names referenced via os.getenv("KEY")."""
    return list(dict.fromkeys(_GETENV_RE.findall(source_code)))


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
    app_config=None,
) -> ScanResult:
    """Screen agent-generated Python source before execution.

    Static patterns are checked first — they return immediately without an LLM
    call, keeping tests fast and offline-capable.
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
        rubric = (
            "You are a security reviewer for AI-generated MCP server code. "
            "Classify as allow, warn, or block. Block: prompt-injection, privilege escalation, "
            "exfiltration, dangerous shell invocation, crypto mining, reverse shells. "
            'Return strict JSON: {"decision":"allow|warn|block","reason":"..."}.'
        )
        prompt = f"Location: {location}\n\nReview this Python code:\n-----\n{source}\n-----"
        response = await model.ainvoke(
            [{"role": "system", "content": rubric}, {"role": "user", "content": prompt}],
            config={"run_name": "mcp_security_scan"},
        )
        parsed = _extract_json_object(str(getattr(response, "content", "") or ""))
        if parsed and parsed.get("decision") in {"allow", "warn", "block"}:
            return ScanResult(parsed["decision"], str(parsed.get("reason") or "No reason provided."))
    except Exception:
        logger.warning("MCP code security scan model call failed; using conservative fallback", exc_info=True)

    return ScanResult("block", "Security scan unavailable; manual review required before execution.")
