"""The lead's working loop, read from its own messages (spec 009 Slice 0).

Pure functions over a run's messages and its checklist (`todos`), shared by
the middlewares that enforce the loop (todo_middleware, verification_middleware,
clarification_middleware, summarization_middleware), the per-run trace and the
eval checks. Nothing here reads the model's prose to decide what happened: a
step's outcome comes from tool results (FR-044, FR-081). The prose is read only
to find what the reply itself says it checked or could not check, and to find
the reply's trailing menu, which is a style rule, not a fact.
"""

from __future__ import annotations

import json
import re
from typing import Any

from omniharness.agents.turns import INVITATION_MARKER, POLICY_STEP_MARKER, TURN_SUMMARY_MARKER, UNTAGGED_INPUT_MARKER, USER_TURN_MARKER

#: On the final AI message of a lead run: the server's verification record
#: (FR-052). Read by the chat (the Verified/Unverified badge), the per-run
#: trace and the eval. Server-set only; never read for a policy decision.
VERIFICATION_KEY = "omniharness_verification"

#: On the summary message (next to turns.TURN_SUMMARY_MARKER): the plan that
#: must survive summarisation (FR-059): the checklist, the done-criteria, the
#: findings already verified and the open blockers.
PLAN_RECORD_KEY = "omniharness_plan_record"

#: Human messages the harness itself injects (reminders). They are not a turn.
REMINDER_NAMES = frozenset(
    {
        "todo_reminder",
        "todo_completion_reminder",
        "preview_verification_reminder",
        "verification_reminder",
        "summary",
    }
)

#: Tools that plan or talk rather than do: they are not evidence of work.
NON_EVIDENCE_TOOLS = frozenset({"write_todos", "ask_clarification"})

DONE_WHEN_RE = re.compile(r"^\s*done\s+when\s*[:\-]\s*", re.I)
URL_RE = re.compile(r"https?://[^\s<>\"'`\])}]+")
_URL_TRAIL = ".,;:!?*_"

#: The reply's own "Not verified" section (a heading, a bold label or a line).
NOT_VERIFIED_RE = re.compile(r"(?im)^[\s>*_#-]*(not\s+verified|unverified)\b")
#: The reply's own "Checked:" line.
CHECKED_RE = re.compile(r"(?im)^[\s>*_#-]*(checked|verified|verification)\b\s*[:\-]?\s*(.*)$")

#: An offer or a menu at the end of a reply (FR-056). Matched on the LAST
#: paragraph only, so an itinerary's "Option A" in the body is not a menu.
MENU_RE = re.compile(
    r"(would you like|do you want me|want me to|shall i\b|should i\b|let me know (if|which|whether|what)|"
    r"which (one|option)s? (would|do|should)|\bor would you\b|would you prefer|i can also\b.*\?|"
    r"(reply|answer) (with )?(yes|no|a|b|1|2)\b|\b(yes/no|y/n)\b|pick (one|an option)|choose (one|an option|between))",
    re.I,
)
#: Tool-call narration (owner rule: replies do not narrate tool calls).
NARRATION_RE = re.compile(
    r"\b(i\s+(used|called|ran|invoked|executed)\s+(the\s+)?`?(write_file|read_file|str_replace|web_search|web_fetch|image_search|"
    r"ledger_apply|ledger_read|present_files|write_todos|bash|ls|task|research|tool)\b|using the `?\w+`? tool\b|"
    r"i('ve| have)\s+(used|called)\s+(the\s+)?`?\w+`?\s+tool)",
    re.I,
)


# ---------------------------------------------------------------- messages


def _type(message: Any) -> str | None:
    return (message.get("type") or message.get("role")) if isinstance(message, dict) else getattr(message, "type", None)


def _kwargs(message: Any) -> dict:
    kwargs = message.get("additional_kwargs") if isinstance(message, dict) else getattr(message, "additional_kwargs", None)
    return kwargs if isinstance(kwargs, dict) else {}


def _name(message: Any) -> str | None:
    return message.get("name") if isinstance(message, dict) else getattr(message, "name", None)


def _tool_calls(message: Any) -> list[dict]:
    calls = message.get("tool_calls") if isinstance(message, dict) else getattr(message, "tool_calls", None)
    return [c for c in (calls or []) if isinstance(c, dict)]


def text_of(message: Any) -> str:
    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return ""


def is_turn_start(message: Any) -> bool:
    """A message that starts a turn: the person's tagged message, an
    invitation, an untagged input, or a summary (which stands in for what came
    before it in this turn)."""
    if _type(message) != "human":
        return False
    kwargs = _kwargs(message)
    return any(kwargs.get(marker) is True for marker in (USER_TURN_MARKER, INVITATION_MARKER, UNTAGGED_INPUT_MARKER)) or TURN_SUMMARY_MARKER in kwargs


def is_reminder(message: Any) -> bool:
    return _type(message) == "human" and (_name(message) or "") in REMINDER_NAMES


def turn_messages(messages: list[Any]) -> list[Any]:
    """The current turn: everything after the latest turn start (inclusive).

    A human message that is neither tagged nor a reminder (a test, a client
    that does not tag) also starts a turn, so a missing tag never merges two
    turns. A resume run's input (the confirmed calls and their results) has no
    human message, so a resume continues the turn it resumes (FR-058)."""
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if _type(message) != "human":
            continue
        if is_reminder(message) and TURN_SUMMARY_MARKER not in _kwargs(message):
            continue
        return list(messages[index:])
    return list(messages)


def clean_url(url: str) -> str:
    return url.rstrip(_URL_TRAIL)


def urls_in(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for raw in URL_RE.findall(text or ""):
        seen.setdefault(clean_url(raw), None)
    return list(seen)


def _norm_url(url: str) -> str:
    u = clean_url(url).lower()
    u = re.sub(r"^https?://(www\.)?", "", u)
    return u.rstrip("/")


# ---------------------------------------------------------------- evidence


def tool_steps(messages: list[Any]) -> list[dict]:
    """Each tool call in `messages` with its result, in order:
    {id, name, args, ok, output, error}. A call with no result yet has ok None."""
    results: dict[str, Any] = {}
    for message in messages:
        if _type(message) == "tool":
            call_id = message.get("tool_call_id") if isinstance(message, dict) else getattr(message, "tool_call_id", None)
            if call_id:
                results[str(call_id)] = message
    steps: list[dict] = []
    for message in messages:
        if _type(message) != "ai":
            continue
        for call in _tool_calls(message):
            call_id = str(call.get("id") or "")
            result = results.get(call_id)
            output = text_of(result) if result is not None else ""
            ok: bool | None
            if result is None:
                ok = None
            else:
                status = result.get("status") if isinstance(result, dict) else getattr(result, "status", None)
                ok = status != "error" and not output.lstrip().lower().startswith("error")
            steps.append({"id": call_id, "name": str(call.get("name") or ""), "args": call.get("args") or {}, "ok": ok, "output": output, "error": None if ok is not False else output[:300]})
    return steps


def evidence_urls(steps: list[dict]) -> set[str]:
    """Normalised URLs that a successful tool result or a successful call's
    arguments named in this turn (a fetched page counts as seen)."""
    seen: set[str] = set()
    for step in steps:
        if not step.get("ok"):
            continue
        for url in urls_in(step.get("output") or ""):
            seen.add(_norm_url(url))
        args = step.get("args") or {}
        for value in args.values() if isinstance(args, dict) else []:
            if isinstance(value, str):
                for url in urls_in(value):
                    seen.add(_norm_url(url))
    return seen


def reply_sections(reply: str) -> tuple[str | None, list[str]]:
    """What the reply says it checked (its "Checked:" line) and its "Not
    verified" items."""
    checked = None
    match = CHECKED_RE.search(reply or "")
    if match and match.group(1).lower() == "checked":
        checked = match.group(2).strip() or None
    not_verified: list[str] = []
    found = NOT_VERIFIED_RE.search(reply or "")
    if found:
        tail = (reply or "")[found.end() :]
        first_line, _, rest = tail.partition("\n")
        first_line = first_line.strip(" :*_-")
        if first_line:
            not_verified.append(first_line)
        for line in rest.splitlines():
            stripped = line.strip()
            if not stripped:
                if not_verified:
                    break
                continue
            if re.match(r"^[-*\d.)\s]+", stripped):
                not_verified.append(re.sub(r"^[-*\d.)\s]+", "", stripped).strip())
            else:
                break
    return checked, [item for item in not_verified if item]


def card_pending(messages: list[Any]) -> bool:
    """A call in the current turn ended in a confirmation card (the policy
    layer's stamp on its result), and no resume has answered it yet: the turn
    stops at the card (FR-055 (c)), it is not finishing early."""
    pending = False
    for message in turn_messages(messages):
        if _type(message) == "tool":
            stamp = _kwargs(message).get(POLICY_STEP_MARKER)
            if isinstance(stamp, dict) and stamp.get("outcome") == "needs_confirmation":
                pending = True
            elif (text_of(message) or "").startswith(("The user confirmed this call", "The user declined this call", "This call did not complete", "Nobody answered the confirmation")):
                pending = False
    return pending


def done_criteria(todos: list[dict] | None) -> str | None:
    for todo in todos or []:
        content = str(todo.get("content") or "")
        if DONE_WHEN_RE.match(content):
            return DONE_WHEN_RE.sub("", content).strip() or None
    return None


def build_verification_record(messages: list[Any], todos: list[dict] | None, *, run_id: str | None, reply: str) -> dict:
    """The server's record of what this turn's reply rests on (FR-052).

    status:
      "none"        nothing to verify: no checklist and no tool evidence;
      "verified"    every checklist item is completed, the reply has no "Not
                    verified" section, at least one tool result backs the turn,
                    and every link in the reply appeared in a tool result;
      "unverified"  anything else (an item not completed, a "Not verified"
                    section, a link no tool returned, a failed last attempt).
    """
    turn = turn_messages(messages)
    steps = tool_steps(turn)
    work = [s for s in steps if s["name"] not in NON_EVIDENCE_TOOLS]
    ok_work = [s for s in work if s["ok"]]
    seen = evidence_urls(work)
    # Results whose calls were folded into a summary still show what was seen.
    for message in turn:
        if _type(message) == "tool" and (_name(message) or "") not in NON_EVIDENCE_TOOLS:
            output = text_of(message)
            if not output.lstrip().lower().startswith("error"):
                for url in urls_in(output):
                    seen.add(_norm_url(url))
    # Findings folded into a summary earlier in this turn still count (FR-059).
    carried = 0
    if turn and TURN_SUMMARY_MARKER in _kwargs(turn[0]):
        record = _kwargs(turn[0]).get(PLAN_RECORD_KEY)
        for finding in (record.get("findings") or []) if isinstance(record, dict) else []:
            if isinstance(finding, dict):
                carried += 1
                for url in finding.get("urls") or []:
                    seen.add(_norm_url(str(url)))
    if carried and not ok_work:
        ok_work = [{"name": "summary", "ok": True}]
    reply_links = urls_in(reply)
    verified_links = [u for u in reply_links if _norm_url(u) in seen]
    unverified_links = [u for u in reply_links if _norm_url(u) not in seen]
    checked, not_verified = reply_sections(reply)
    items = [{"content": str(t.get("content") or ""), "status": str(t.get("status") or "pending")} for t in (todos or [])]
    criteria = done_criteria(todos)

    checks: list[dict] = []
    for item in items:
        if DONE_WHEN_RE.match(item["content"]):
            continue
        done = item["status"] == "completed"
        checks.append({"claim": item["content"], "verified": done and bool(ok_work), "evidence": "checklist item completed after tool results" if done and ok_work else ("item not completed" if not done else "no tool result in this turn")})
    failed_last: dict[str, dict] = {}
    for step in work:
        failed_last[step["name"]] = step
    for name, step in failed_last.items():
        if step["ok"] is False:
            checks.append({"claim": f"{name} succeeded", "verified": False, "evidence": f"last {name} call failed: {(step['error'] or '')[:120]}"})
    if reply_links:
        checks.append(
            {
                "claim": f"{len(reply_links)} link(s) in the reply",
                "verified": not unverified_links,
                "evidence": f"{len(verified_links)} appeared in this turn's tool results" + (f"; {len(unverified_links)} did not" if unverified_links else ""),
            }
        )

    if not items and not work:
        status = "none"
    else:
        incomplete = [i for i in items if i["status"] != "completed" and not DONE_WHEN_RE.match(i["content"])]
        criteria_open = any(DONE_WHEN_RE.match(i["content"]) and i["status"] != "completed" for i in items) and incomplete
        unverified = bool(incomplete or criteria_open or not_verified or unverified_links or not ok_work or any(c["verified"] is False for c in checks))
        status = "unverified" if unverified else "verified"
        if not items and ok_work and not unverified_links and not not_verified and not any(c["verified"] is False for c in checks):
            status = "verified"
    return {
        "version": 1,
        "run_id": run_id,
        "status": status,
        "done_criteria": criteria,
        "items": items,
        "checks": checks,
        "checked": checked,
        "not_verified": not_verified,
        "links": {"verified": verified_links, "unverified": unverified_links},
        "evidence_count": len(ok_work) + carried,
        "waiting_on_card": card_pending(messages),
        # Measurement only (owner rule: replies do not narrate tool calls).
        "narrates_tools": narrates_tools(reply),
    }


# ---------------------------------------------------------------- style


def _paragraphs(text: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]


def has_menu(reply: str) -> bool:
    """The reply ends with an offer or a menu of options (FR-056)."""
    paragraphs = _paragraphs(reply or "")
    if not paragraphs:
        return False
    last = paragraphs[-1]
    if MENU_RE.search(last) and ("?" in last or re.search(r"(?m)^\s*([-*]|\d+[.)]|[a-c][.)])\s+", last)):
        return True
    # "Options:" followed by a list as the final block.
    if len(paragraphs) >= 2 and re.search(r"(?i)(options|choices|which would you|what would you like)\s*[:?]\s*$", paragraphs[-2].strip()):
        return True
    return False


def strip_trailing_menu(reply: str, *, min_kept: int = 160) -> tuple[str, bool]:
    """Remove a trailing offer/menu paragraph (and an options list right after
    it) when enough of the reply stays to stand on its own. Returns (text,
    changed). A reply that IS only a question is left alone."""
    if not has_menu(reply):
        return reply, False
    paragraphs = _paragraphs(reply)
    cut = len(paragraphs) - 1
    # An options list after the question: drop it too.
    if cut >= 1 and re.match(r"^\s*([-*]|\d+[.)]|[a-c][.)])\s+", paragraphs[cut]) and MENU_RE.search(paragraphs[cut - 1]):
        cut -= 1
    kept = "\n\n".join(paragraphs[:cut]).rstrip()
    if len(kept) < min_kept:
        return reply, False
    return kept, True


def narrates_tools(reply: str) -> bool:
    return bool(NARRATION_RE.search(reply or ""))


# ---------------------------------------------------------------- plan record


def plan_record(messages_to_summarize: list[Any], todos: list[dict] | None) -> dict:
    """What summarisation must not lose (FR-059): the checklist, the
    done-criteria, the verified findings (tool, query or URL) and the open
    blockers, carried forward from an earlier summary of the same turn."""
    prior: dict = {}
    for message in messages_to_summarize:
        record = _kwargs(message).get(PLAN_RECORD_KEY)
        if isinstance(record, dict):
            prior = record
    turn = turn_messages(list(messages_to_summarize))
    calls: dict[str, dict] = {}
    for message in turn:
        if _type(message) == "ai":
            for call in _tool_calls(message):
                calls[str(call.get("id") or "")] = call
    findings: list[dict] = list(prior.get("findings") or []) if isinstance(prior.get("findings"), list) else []
    blockers: list[dict] = []
    # From the tool RESULTS: a result whose call was folded into an earlier
    # summary still counts (its call is gone, its evidence is not).
    for message in turn:
        if _type(message) != "tool":
            continue
        call_id = str((message.get("tool_call_id") if isinstance(message, dict) else getattr(message, "tool_call_id", "")) or "")
        call = calls.get(call_id, {})
        name = str(_name(message) or call.get("name") or "")
        if name in NON_EVIDENCE_TOOLS:
            continue
        output = text_of(message)
        status = message.get("status") if isinstance(message, dict) else getattr(message, "status", None)
        ok = status != "error" and not output.lstrip().lower().startswith("error")
        args = call.get("args") or {}
        ref = ""
        if isinstance(args, dict):
            for key in ("query", "url", "path", "file_path", "description", "q"):
                if isinstance(args.get(key), str) and args[key]:
                    ref = args[key][:200]
                    break
            if not ref and args:
                ref = json.dumps(args, default=str)[:200]
        if ok:
            findings.append({"tool": name, "ref": ref, "urls": urls_in(output)[:20]})
        else:
            blockers.append({"tool": name, "ref": ref, "error": output[:200]})
    # A blocker later fixed by a successful call of the same tool is not open.
    fixed = {f["tool"] for f in findings}
    open_blockers = [b for b in blockers if b["tool"] not in fixed] + [b for b in (prior.get("blockers") or []) if isinstance(b, dict) and b.get("tool") not in fixed]
    items = [{"content": str(t.get("content") or ""), "status": str(t.get("status") or "pending")} for t in (todos or prior.get("todos") or [])]
    return {
        "version": 1,
        "todos": items,
        "done_criteria": done_criteria(items),
        "findings": findings[-40:],
        "blockers": open_blockers[-10:],
    }


def plan_record_text(record: dict) -> str:
    """The plan record as the model reads it, appended to the summary."""
    lines = ["<plan_record>", "Server record of this task so far. Continue from it; do not redo what is listed as done."]
    if record.get("done_criteria"):
        lines.append(f"Done when: {record['done_criteria']}")
    todos = record.get("todos") or []
    if todos:
        lines.append("Checklist:")
        lines.extend(f"- [{t['status']}] {t['content']}" for t in todos)
    else:
        lines.append("Checklist: none was recorded (if the task has 3+ steps, re-plan with write_todos).")
    findings = record.get("findings") or []
    if findings:
        lines.append("Already done and verified (do not repeat these calls):")
        for f in findings:
            urls = ", ".join(f.get("urls") or [])
            lines.append(f"- {f['tool']}: {f.get('ref') or ''}" + (f" -> {urls}" if urls else ""))
    blockers = record.get("blockers") or []
    if blockers:
        lines.append("Open blockers:")
        lines.extend(f"- {b['tool']}: {b.get('ref') or ''}: {b.get('error') or ''}" for b in blockers)
    lines.append("</plan_record>")
    return "\n".join(lines)
