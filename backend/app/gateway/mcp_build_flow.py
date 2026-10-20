"""MCP Suite > Build (Feature 006): describe a tool in words, an agent builds it
and tests it in a sandbox, and you approve its first real run.

Two jobs live here, both pure:

1. **Secrets never reach the model.** A description can carry a key ("use my
   token ghp_…"). ``extract_secrets`` lifts every secret-shaped value out and
   puts a placeholder in its place (``{{secret:GITHUB_TOKEN}}``); the router
   stores the value in the vault under that name, and the build prompt only
   ever says which environment variable to read. ``scrub`` does the same for
   anything that goes back to the model or to a log (test output, errors),
   given the values stored for that server.

2. **Where a build is, in words.** ``describe_build`` turns the server row, the
   manager's record and the build run into one of: drafting, building, tests
   failed (with the reason), waiting for your approval, turning on, enabled,
   off, stalled; and the checklist the Build tab shows. Each step says what
   was observed; nothing is claimed that the records do not show.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

BuildState = Literal["drafting", "building", "tests_failed", "awaiting_approval", "turning_on", "turn_on_failed", "enabled", "off", "stalled"]

#: Known key shapes and the environment variable each is stored under.
_KNOWN: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "GITHUB_TOKEN"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "GITHUB_TOKEN"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}"), "ANTHROPIC_API_KEY"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"), "API_KEY"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"), "SLACK_TOKEN"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS_ACCESS_KEY_ID"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"), "GOOGLE_API_KEY"),
]
#: ``NAME=value`` / ``NAME: value`` with an env-style name: stored under NAME.
_NAMED = re.compile(r"\b([A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASS|PAT))\s*[:=]\s*[\"']?([^\s\"',;]{4,})")
#: ``token: value``, ``password is value``, ``api key value`` in prose.
_WORDED = re.compile(r"(?i)\b(api[\s_-]?key|access[\s_-]?token|token|password|passwd|secret)\b\s*(?:[:=]|is)?\s*[\"']?([A-Za-z0-9_\-./+]{8,})")
#: Anything else long and random: 24+ characters mixing letters and digits.
_OPAQUE = re.compile(r"(?<![A-Za-z0-9_\-])(?=[A-Za-z0-9_\-]{24,})(?=[^\s]*[0-9][^\s]*[0-9])(?=[^\s]*[A-Za-z])[A-Za-z0-9_\-]{24,}(?![A-Za-z0-9_\-])")

_PLACEHOLDER = re.compile(r"\{\{secret:[A-Z0-9_]+\}\}")


def placeholder(name: str) -> str:
    """What the model and the logs see where a secret's value was."""
    return "{{secret:" + name + "}}"


@dataclass
class Extracted:
    """A text with its secrets lifted out. ``secrets`` maps NAME -> value and
    goes to the vault only; it is never logged and never put in a prompt."""

    text: str
    secrets: dict[str, str] = field(default_factory=dict)


def extract_secrets(text: str) -> Extracted:
    """Replace every secret-shaped value in *text* with a placeholder."""
    secrets: dict[str, str] = {}
    by_value: dict[str, str] = {}

    def name_for(value: str, wanted: str) -> str:
        if value in by_value:
            return by_value[value]
        name, n = wanted, 2
        while name in secrets:
            name, n = f"{wanted}_{n}", n + 1
        secrets[name] = value
        by_value[value] = name
        return name

    def lift(value: str, wanted: str) -> str:
        if _PLACEHOLDER.fullmatch(value):
            return value
        return placeholder(name_for(value, wanted))

    def outside(text: str, fn) -> str:
        # Placeholders already put in are never read again as text.
        pieces = _PLACEHOLDER.split(text)
        kept = _PLACEHOLDER.findall(text)
        return "".join(fn(p) + (kept[i] if i < len(kept) else "") for i, p in enumerate(pieces))

    def worded(m: re.Match[str]) -> str:
        value = m.group(2)
        if not re.search(r"[0-9]", value) and len(value) < 16:
            return m.group(0)  # an ordinary word ("token is required"), not a key
        word = re.sub(r"[\s\-]+", "_", m.group(1)).upper()
        return m.group(0).replace(value, lift(value, word if word != "PASSWD" else "PASSWORD"))

    out = outside(text, lambda t: _NAMED.sub(lambda m: m.group(0).replace(m.group(2), lift(m.group(2), m.group(1))), t))
    for pattern, wanted in _KNOWN:
        out = outside(out, lambda t, p=pattern, w=wanted: p.sub(lambda m: lift(m.group(0), w), t))
    out = outside(out, lambda t: _WORDED.sub(worded, t))
    out = outside(out, lambda t: _OPAQUE.sub(lambda m: lift(m.group(0), "SECRET"), t))
    return Extracted(text=out, secrets=secrets)


def scrub(text: str, secrets: Mapping[str, str]) -> str:
    """Replace each stored secret's value in *text* with its placeholder."""
    # Longest first, so a value that contains another is replaced whole.
    for name, value in sorted(secrets.items(), key=lambda kv: -len(kv[1] or "")):
        if value and value in text:
            text = text.replace(value, placeholder(name))
    return text


def server_name_from(description: str) -> str:
    """A short slug for the server: the description's first meaningful words."""
    stop = {"a", "an", "the", "my", "and", "or", "of", "to", "for", "in", "on", "with", "that", "which", "it", "is", "me", "i"}
    words = [w for w in re.findall(r"[a-z0-9]+", _PLACEHOLDER.sub("", description).lower()) if w not in stop]
    slug = "-".join(words[:4])[:40].strip("-")
    return slug or "new-tool"


def build_prompt(*, server_id: str, name: str, description: str, secret_names: list[str]) -> str:
    """The build agent's first message. *description* must already be
    placeholder-only (``extract_secrets``); secret values are never passed."""
    parts = [
        "Use the mcp-server-builder skill to build an MCP server.",
        f"Server ID: {server_id}",
        f"Name: {name}",
        f"What the user asked for, in their words: {description}",
        "Template type: custom_tool",
    ]
    if secret_names:
        parts.append(
            "Secrets: the user's credentials are stored for this server and are NOT shown to you. "
            "Placeholders like {{secret:NAME}} above stand for them. Inside each tool handler, read "
            + ", ".join(f"os.environ['{n}']" for n in secret_names)
            + " at call time. Never print, return or log their values, and never ask the user for them."
        )
    parts.append("\nWrite the complete server.py source code, then call mcp_build with the server_id and source_code.")
    return "\n".join(parts)


@dataclass
class BuildDescription:
    state: BuildState
    label: str
    reason: str | None
    steps: list[dict]
    tool_count: int | None
    tests_passed: int | None
    tests_total: int | None


def _step(status: str, text: str) -> dict:
    return {"status": status, "text": text}


def describe_build(
    server: Mapping,
    *,
    phase: str | None,
    error: str | None,
    tools: list[dict],
    test_results: list[dict],
    deploy_steps: list[dict],
    testing_now: bool,
    run_status: str | None,
    run_error: str | None,
    stored_secrets: set[str] | None,
) -> BuildDescription:
    """Where one built server is, in words, from what the records show.

    ``run_status`` is the build agent's run (None: no run known to this
    process). ``stored_secrets`` is None when the vault could not be read:
    then a secret's step says so instead of guessing.
    """
    approved = bool(server.get("approved"))
    status = server.get("status") or ""
    has_source = bool(server.get("source_code"))
    calls = [t for t in test_results if t.get("tool") != "__sandbox__"]
    sandbox = next((t for t in test_results if t.get("tool") == "__sandbox__"), None)
    passed = sum(1 for t in calls if t.get("ok")) if calls else None
    total = len(calls) if calls else None
    tool_count = len(tools) if (tools or has_source and phase not in (None, "idle")) else None
    secrets = list(server.get("detected_secrets") or [])

    steps: list[dict] = []
    if tools:
        names = ", ".join(t.get("name", "?") for t in tools)
        steps.append(_step("done", f"Scaffolded server, {len(tools)} tool{'s' if len(tools) != 1 else ''}: {names}"))
    if total:
        if passed == total:
            steps.append(_step("done", f"Tests passed in sandbox: {passed} of {total}"))
        else:
            first = next((t for t in calls if not t.get("ok")), {})
            steps.append(_step("failed", f"Tests in sandbox: {passed} of {total} passed. {first.get('tool', '')}: {first.get('error', 'failed')}"))
    for name in secrets:
        if stored_secrets is None:
            steps.append(_step("waiting", f"Uses secret {name}: can't tell whether it is stored"))
        elif name in stored_secrets:
            steps.append(_step("done", f"Uses secret {name}: stored, never shown to the model"))
        else:
            steps.append(_step("waiting", f"Needs secret {name}: not stored yet, so its tools can't work"))

    def done(state: BuildState, label: str, reason: str | None = None) -> BuildDescription:
        return BuildDescription(state, label, reason, steps, tool_count, passed, total)

    if phase == "deploying":
        current = next((s for s in deploy_steps if s.get("status") == "running"), None)
        steps.append(_step("done", "You approved its first run"))
        steps.append(_step("waiting", f"Turning on: {current['label']}" if current else "Turning on"))
        return done("turning_on", "Turning on")
    if approved and phase == "failed" and any(s.get("status") == "failed" for s in deploy_steps):
        failed = next(s for s in deploy_steps if s.get("status") == "failed")
        steps.append(_step("done", "You approved its first run"))
        steps.append(_step("failed", f"Couldn't turn on: {failed.get('detail') or error or 'no reason given'}"))
        return done("turn_on_failed", "Couldn't turn on", failed.get("detail") or error)
    if approved and status == "deployed":
        steps.append(_step("done", "You approved its first run"))
        steps.append(_step("done", "On: agents can use its tools"))
        return done("enabled", "Enabled")
    if status == "stopped" or phase == "stopped":
        return done("off", "Off")
    if testing_now:
        steps.append(_step("waiting", "Building and testing in the sandbox"))
        return done("building", "Building")
    if not has_source:
        if run_status in ("pending", "running"):
            steps.append(_step("waiting", "The agent is writing the server"))
            return done("drafting", "Drafting")
        if run_status in ("error", "timeout", "interrupted"):
            return done("stalled", "Build stopped", f"The build agent stopped ({run_status}) before writing any code" + (f": {run_error}" if run_error else "."))
        if run_status == "success":
            return done("stalled", "Build stopped", "The build agent finished without submitting any code.")
        return done("stalled", "No build running", "There is no code yet, and no build is running for it (the gateway may have restarted).")
    if phase == "failed":
        return done("tests_failed", "Tests failed", error or "The safety scan stopped it, without giving a reason.")
    if phase == "testing":
        why = (sandbox or {}).get("error") or "The server started, but no tools were found."
        return done("tests_failed", "Tests failed", why)
    if phase == "verified" and not approved:
        steps.append(_step("waiting", "First real run needs your approval"))
        return done("awaiting_approval", "Waiting for your approval")
    if approved:
        steps.append(_step("done", "You approved its first run"))
        return done("off", "Approved · off")
    if run_status in ("pending", "running"):
        steps.append(_step("waiting", "The agent is still working on it"))
        return done("building", "Building")
    return done("stalled", "Not tested", "The code is written but has not been tested in the sandbox.")
