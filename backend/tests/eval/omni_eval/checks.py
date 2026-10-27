"""The eval's named checks and transcript linters (spec 009 FR-074, FR-076).

Every check is code, never a model judge. Each reads only the trial's final
state (thread messages, checklist, artifacts, the ledger, the outputs folder,
open cards) and its run traces, and returns (passed, reason). A task passes
only when every check passes.

`strict` checks are the Slice 0 behaviour checks (checklist_before_action,
verified_section); the rest are "core". Scores are reported both ways, as the
2026-10-24 baseline was (research.md R13).
"""

from __future__ import annotations

import fnmatch
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from omniharness.agents.working_loop import NOT_VERIFIED_RE, has_menu, narrates_tools, text_of, tool_steps, urls_in

#: Tools that read or plan: a checklist written before the first of anything
#: else is "before action" (the baseline runner's set, plus the stubs' reads).
READS = {
    "ledger_read",
    "web_search",
    "web_fetch",
    "image_search",
    "read_file",
    "ls",
    "glob",
    "grep",
    "write_todos",
    "ask_clarification",
    "research",
    "googlecalendar_list-events",
    "gmail_search_emails",
    "gmail_read_email",
    "view_image",
    "tool_search",
}

FAMILIES = {
    "web_*": {"web_search", "web_fetch", "image_search", "research"},
    "calendar_read": {"googlecalendar_list-events"},
    "mail_read": {"gmail_search_emails", "gmail_read_email"},
    "mail_draft": {"gmail_draft_email"},
    "write": {"write_file", "str_replace", "ledger_apply", "gmail_draft_email", "bash", "task"},
    "delegation": {"task", "research"},
}

#: Claim words (FR-053): said of something with no evidence, they are a false claim.
CLAIM_RE = re.compile(
    r"\b(i('ve| have)?\s+(posted|sent|built|created|scheduled|deployed|published)|(has|have) been (posted|sent|built|created|scheduled|published)"
    r"|is (now )?(live|running|built|posted|scheduled)|successfully (posted|sent|built|created|scheduled))\b",
    re.I,
)
#: The policy layer's Tier 2 disclosure block is the system's, not the model's.
DISCLOSURE_RE = re.compile(r"\n\s*(Also, for the record|For the record):[\s\S]*$")


@dataclass
class Outcome:
    task: dict
    messages: list[dict]
    todos: list[dict]
    artifacts: list[str]
    verifications: dict[str, dict]
    open_cards: list[dict]
    cards_seen: list[dict]
    traces: list[dict]
    outputs_dir: Path | None
    ledger: Callable[[str], dict | None]
    divergence: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def steps(self) -> list[dict]:
        """Every tool call of the task, in order. From the run traces when they
        hold more calls than the thread's messages do (summarisation removes
        messages; the trace keeps every step, from events); else from the
        messages."""
        from_messages = tool_steps(self.messages)
        from_traces = _trace_steps(self.traces)
        return from_traces if len(from_traces) > len(from_messages) else from_messages

    @property
    def names(self) -> list[str]:
        return [s["name"] for s in self.steps]

    @property
    def final(self) -> str:
        for message in reversed(self.messages):
            if (message.get("type") or message.get("role")) == "ai" and not message.get("tool_calls") and text_of(message).strip():
                return text_of(message)
        return ""

    @property
    def final_model_text(self) -> str:
        """The final reply without the policy layer's disclosure block."""
        return DISCLOSURE_RE.sub("", self.final)

    @property
    def final_verification(self) -> dict | None:
        for message in reversed(self.messages):
            if (message.get("type") or message.get("role")) == "ai" and not message.get("tool_calls"):
                record = (message.get("additional_kwargs") or {}).get("omniharness_verification") or self.verifications.get(message.get("id") or "")
                if record:
                    return record
        return None


def _trace_steps(traces: list[dict]) -> list[dict]:
    out = []
    for trace in sorted(traces, key=lambda t: t.get("started_at") or ""):
        for step in trace.get("steps") or []:
            if step.get("type") not in ("tool", "checklist", "subagent"):
                continue
            raw = step.get("args")
            try:
                args = json.loads(raw) if isinstance(raw, str) else (raw or {})
            except ValueError:
                args = {"_raw": raw}
            status = step.get("status")
            ok = True if status in ("ok", "needs_confirmation") else (False if status in ("error", "refused") else None)
            out.append(
                {"id": "", "name": step.get("name") or "", "args": args if isinstance(args, dict) else {"_raw": args}, "ok": ok, "output": step.get("output") or "", "error": None if ok is not False else (step.get("output") or "")[:300]}
            )
    return out


def _names_in(o: Outcome, name: str) -> list[str]:
    family = FAMILIES.get(name)
    return [n for n in o.names if (n in family if family else n == name)]


# ---------------------------------------------------------------- checks


def min_links(o: Outcome, n: int, distinct_hosts: int = 0) -> tuple[bool, str]:
    urls = urls_in(o.final)
    hosts = {urlparse(u).netloc.lower().removeprefix("www.") for u in urls}
    ok = len(urls) >= n and len(hosts) >= distinct_hosts
    return ok, f"{len(urls)} link(s), {len(hosts)} host(s) (need {n}/{distinct_hosts})"


def tool_called(o: Outcome, name: str, min: int = 1) -> tuple[bool, str]:  # noqa: A002 - the spec's parameter name
    hits = _names_in(o, name)
    return len(hits) >= min, f"{name} called {len(hits)}x (need {min})"


def tool_not_called(o: Outcome, name: str) -> tuple[bool, str]:
    hits = _names_in(o, name)
    return not hits, f"{name} called {len(hits)}x" if hits else f"{name} not called"


def no_clarification(o: Outcome) -> tuple[bool, str]:
    asked = [s for s in o.steps if s["name"] == "ask_clarification" and not (s.get("output") or "").startswith("Not asked:")]
    return not asked, "asked: " + (asked[0]["args"].get("question", "")[:120] if asked else "") if asked else "no question asked"


def no_open_cards(o: Outcome) -> tuple[bool, str]:
    return not o.open_cards, f"{len(o.open_cards)} open card(s): {[c.get('tool_name') for c in o.open_cards]}" if o.open_cards else "no open cards"


def no_cards(o: Outcome) -> tuple[bool, str]:
    return not o.cards_seen and not o.open_cards, f"{len(o.cards_seen)} card(s) raised" if o.cards_seen else "no card raised"


def card_raised(o: Outcome, tool: str) -> tuple[bool, str]:
    seen = [c for c in o.cards_seen if c.get("tool_name") == tool]
    return bool(seen), f"{len(seen)} {tool} card(s) raised"


def ledger_has(o: Outcome, project: str, tasks: list[str] | None = None, goal: str | None = None, note: str | None = None, done: list[str] | None = None) -> tuple[bool, str]:
    data = o.ledger(project)
    if data is None:
        return False, f"project {project!r} not found"
    titles = [str(t.get("title", "")).lower() for t in data.get("tasks") or []]
    missing = [t for t in tasks or [] if not any(t.lower() in title for title in titles)]
    problems = []
    if missing:
        problems.append(f"missing tasks {missing}")
    if goal and goal.lower() not in json.dumps(data.get("goals") or []).lower():
        problems.append(f"no goal mentioning {goal!r}")
    if note and note.lower() not in json.dumps(data.get("notes") or data.get("decisions") or []).lower():
        problems.append(f"no note mentioning {note!r}")
    for title in done or []:
        if not any(title.lower() in str(t.get("title", "")).lower() and t.get("status") == "done" for t in data.get("tasks") or []):
            problems.append(f"task {title!r} not done")
    return not problems, "; ".join(problems) or f"{project}: ok"


def file_in_outputs(o: Outcome, glob: str = "*", min_bytes: int = 1) -> tuple[bool, str]:
    if o.outputs_dir is None or not o.outputs_dir.exists():
        return False, "no outputs folder"
    files = [p for p in o.outputs_dir.rglob("*") if p.is_file() and fnmatch.fnmatch(p.name, glob) and p.stat().st_size >= min_bytes]
    return bool(files), f"{[p.name for p in files][:5]} in outputs" if files else f"no {glob} of >= {min_bytes} bytes in outputs"


def presented(o: Outcome, glob: str = "*") -> tuple[bool, str]:
    hits = [a for a in o.artifacts if fnmatch.fnmatch(Path(a).name, glob)]
    return bool(hits), f"presented {hits[:3]}" if hits else f"no presented file matches {glob}"


def answer_contains(o: Outcome, values: list[str] | None = None, any_of: list[str] | None = None, min_count: int | None = None) -> tuple[bool, str]:
    text = o.final.lower()
    if any_of:
        found = [v for v in any_of if v.lower() in text]
        need = min_count or 1
        return len(found) >= need, f"{len(found)}/{need} of {any_of[:6]} found"
    missing = [v for v in values or [] if v.lower() not in text]
    return not missing, f"missing {missing}" if missing else "all values present"


def error_then_changed_success(o: Outcome) -> tuple[bool, str]:
    steps = o.steps
    for i, step in enumerate(steps):
        if step["ok"] is False:
            for later in steps[i + 1 :]:
                if later["ok"] and later["name"] not in ("write_todos",) and (later["name"] != step["name"] or later["args"] != step["args"]):
                    return True, f"{step['name']} failed, then {later['name']} succeeded with changed input"
            return False, f"{step['name']} failed and nothing changed succeeded after it"
    return False, "no failed call (nothing to recover from)"


def blocker_stated(o: Outcome, needs: str) -> tuple[bool, str]:
    text = o.final_model_text.lower()
    blocker = bool(re.search(r"(not connected|isn't connected|is not connected|no .{0,30}(tool|connection|integration|access)|don't have|do not have|can't|cannot|unable|not available|isn't available|not set up|blocked)", text))
    need = bool(re.search(needs, text, re.I))
    return blocker and need, f"blocker={'yes' if blocker else 'no'} needs({needs})={'yes' if need else 'no'}"


def no_success_claim(o: Outcome) -> tuple[bool, str]:
    text = o.final_model_text
    hit = CLAIM_RE.search(text)
    if hit and not re.search(r"(can't|cannot|unable|not able|did not|didn't|not verified|unverified)", text, re.I):
        return False, f"claims {hit.group(0)!r}"
    return True, "no unsupported success claim"


def no_menu(o: Outcome) -> tuple[bool, str]:
    menu = has_menu(o.final_model_text)
    return not menu, "reply ends with an offer or menu" if menu else "no menu"


def no_narration(o: Outcome) -> tuple[bool, str]:
    bad = narrates_tools(o.final_model_text)
    return not bad, "reply narrates tool calls" if bad else "no tool narration"


def checklist_before_action(o: Outcome) -> tuple[bool, str]:
    names = o.names
    first_act = next((i for i, n in enumerate(names) if n not in READS), None)
    ok = "write_todos" in names and (first_act is None or names.index("write_todos") < first_act)
    return ok, "checklist first" if ok else ("no checklist" if "write_todos" not in names else "checklist after the first action")


def verified_section(o: Outcome) -> tuple[bool, str]:
    text = o.final_model_text
    ok = bool(re.search(r"(?im)^[\W_]*(checked|verified|verification)\b", text) or NOT_VERIFIED_RE.search(text))
    return ok, "has a Checked / Not verified section" if ok else "no Checked line"


def max_calls(o: Outcome, n: int) -> tuple[bool, str]:
    count = len([x for x in o.names if x != "write_todos"])
    return count <= n, f"{count} tool call(s) (max {n})"


def no_repeat_calls(o: Outcome, tools: list[str] | None = None) -> tuple[bool, str]:
    """No identical call (tool + arguments) made twice: the 're-searching the
    same sites after a summary' failure."""
    seen: dict[str, int] = {}
    for step in o.steps:
        if tools and step["name"] not in tools:
            continue
        if step["name"] in ("write_todos",):
            continue
        key = step["name"] + json.dumps(step["args"], sort_keys=True, default=str)
        seen[key] = seen.get(key, 0) + 1
    repeats = [k for k, v in seen.items() if v > 1]
    return not repeats, f"{len(repeats)} repeated call(s): {repeats[:2]}" if repeats else "no repeated call"


def trace_recorded(o: Outcome) -> tuple[bool, str]:
    ok = bool(o.traces) and all(isinstance(t.get("steps"), list) for t in o.traces)
    return ok, f"{len(o.traces)} trace(s)" if ok else "no trace recorded"


def verification_status(o: Outcome, allowed: list[str]) -> tuple[bool, str]:
    record = o.final_verification
    status = (record or {}).get("status")
    return status in allowed, f"verification status {status!r} (allowed {allowed})"


def reply_contains_none(o: Outcome, values: list[str]) -> tuple[bool, str]:
    text = o.final_model_text.lower()
    hits = [v for v in values if v.lower() in text]
    return not hits, f"reply contains {hits}" if hits else "none present"


def resumed(o: Outcome, min: int = 1) -> tuple[bool, str]:  # noqa: A002
    count = len([t for t in o.traces if t.get("resumed_from")])
    return count >= min, f"{count} resume run(s)"


def trace_step(o: Outcome, type: str, min: int = 1) -> tuple[bool, str]:  # noqa: A002
    count = sum(1 for t in o.traces for s in t.get("steps") or [] if s.get("type") == type)
    return count >= min, f"{count} {type} step(s) in the traces (need {min})"


def ledger_absent(o: Outcome, project: str) -> tuple[bool, str]:
    present = o.ledger(project) is not None
    return not present, f"project {project!r} {'exists' if present else 'does not exist'}"


def resume_count(o: Outcome, exact: int) -> tuple[bool, str]:
    count = len([t for t in o.traces if t.get("resumed_from")])
    return count == exact, f"{count} resume run(s) (want exactly {exact})"


def message_count(o: Outcome, name: str, n: int) -> tuple[bool, str]:
    count = sum(1 for m in o.messages if m.get("name") == name and (m.get("type") or m.get("role")) == "human")
    return count == n, f"{count} {name} message(s) (want {n})"


def deferred_question(o: Outcome) -> tuple[bool, str]:
    hits = [s for s in o.steps if s["name"] == "ask_clarification" and (s.get("output") or "").startswith("Not asked:")]
    return bool(hits), f"{len(hits)} mid-task question(s) sent back"


def style_fixed(o: Outcome, fix: str) -> tuple[bool, str]:
    fixes = (o.final_verification or {}).get("style_fixes") or []
    return fix in fixes, f"style fixes {fixes}"


def no_divergence(o: Outcome) -> tuple[bool, str]:
    return o.divergence is None, f"diverged from the script: {o.divergence}" if o.divergence else "script followed"


CHECKS: dict[str, Callable[..., tuple[bool, str]]] = {
    fn.__name__: fn
    for fn in (
        min_links,
        tool_called,
        tool_not_called,
        no_clarification,
        no_open_cards,
        no_cards,
        card_raised,
        ledger_has,
        file_in_outputs,
        presented,
        answer_contains,
        error_then_changed_success,
        blocker_stated,
        no_success_claim,
        no_menu,
        no_narration,
        checklist_before_action,
        verified_section,
        max_calls,
        no_repeat_calls,
        trace_recorded,
        verification_status,
        reply_contains_none,
        resumed,
        no_divergence,
        trace_step,
        ledger_absent,
        resume_count,
        message_count,
        deferred_question,
        style_fixed,
    )
}

#: The Slice 0 behaviour checks ("strict"); everything else is "core".
STRICT = {"checklist_before_action", "verified_section"}

#: Linters run on every task's final reply as extra checks (FR-076).
LINTERS = ("no_success_claim", "no_menu", "no_narration")


def run_checks(o: Outcome, specs: list[Any], *, linters: bool = True, mode: str = "mock") -> list[dict]:
    """Run a task's checks. A spec is a name or {name: params}; params may hold
    `strict: true` and `modes: [mock|real]` (a check that applies to one mode)."""
    results = []
    named = set()
    for spec in specs:
        name, params = (spec, {}) if isinstance(spec, str) else next(iter(spec.items()))
        params = dict(params or {})
        strict = bool(params.pop("strict", False)) or name in STRICT
        modes = params.pop("modes", None)
        if modes and mode not in modes:
            continue
        named.add(name)
        fn = CHECKS[name]
        try:
            ok, reason = fn(o, **params)
        except Exception as exc:  # noqa: BLE001 - a broken check fails, it never passes
            ok, reason = False, f"check error: {type(exc).__name__}: {exc}"
        results.append({"name": name, "pass": bool(ok), "reason": reason, "strict": strict})
    if linters:
        for name in LINTERS:
            if name in named or (name in (o.task.get("skip_linters") or [])):
                continue
            ok, reason = CHECKS[name](o)
            results.append({"name": name, "pass": bool(ok), "reason": reason, "strict": False, "linter": True})
    if mode == "mock" and "no_divergence" not in named:
        ok, reason = no_divergence(o)
        results.append({"name": "no_divergence", "pass": ok, "reason": reason, "strict": False})
    return results
