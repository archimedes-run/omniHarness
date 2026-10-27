"""The per-run trace of a lead run (spec 009 Slice 0, FR-080 to FR-083).

Every lead run (a chat turn, a run resumed after a confirmation, a scheduled
run) leaves one run-history record of kind ``chat`` when it ends: its ordered
steps (checklist writes, tool calls with tier and outcome, cards raised and how
they were resolved, retries, the resume it continues, summarisation, the
verification record), its tokens by model and an estimated cost. It is written
through ``RunHistory.record()``, so redaction, encryption at rest, the caps,
the 30-day retention and Delete apply unchanged (FR-080).

Step statuses come from EVENTS, never from the agent's prose (FR-081): the
run's journal (tool results with their status and the policy layer's stamp,
model responses with their tool calls and usage) and the pending store (card
outcomes). The verification record is the server's (verification_middleware),
read from thread state.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

#: The run kind of a lead run's trace (recorder.AUTOMATION is the other).
CHAT = "chat"
TRACE_VERSION = 1

#: Estimated USD per million tokens: (input, cached input, output). Matched by
#: the longest key the model name starts with; an unknown model has no cost
#: (shown as unknown, never guessed). List prices, an estimate only.
PRICES: dict[str, tuple[float, float, float]] = {
    "gpt-5-nano": (0.05, 0.005, 0.40),
    "gpt-5-mini": (0.25, 0.025, 2.00),
    "gpt-5": (1.25, 0.125, 10.00),
    "gpt-4.1-mini": (0.40, 0.10, 1.60),
    "gpt-4.1": (2.00, 0.50, 8.00),
    "gpt-4o-mini": (0.15, 0.075, 0.60),
    "gpt-4o": (2.50, 1.25, 10.00),
}

_ARGS_MAX = 240
_OUTPUT_MAX = 400


def price_of(model: str | None) -> tuple[float, float, float] | None:
    name = (model or "").lower()
    best = None
    for key in PRICES:
        if name.startswith(key) and (best is None or len(key) > len(best)):
            best = key
    return PRICES[best] if best else None


def estimate_cost(by_model: dict[str, dict[str, int]]) -> float | None:
    """Sum over models; None when any model with tokens has no price."""
    total = 0.0
    for model, usage in by_model.items():
        price = price_of(model)
        if price is None:
            if usage.get("input") or usage.get("output"):
                return None
            continue
        cached = usage.get("cached", 0)
        total += ((usage.get("input", 0) - cached) * price[0] + cached * price[1] + usage.get("output", 0) * price[2]) / 1e6
    return round(total, 6)


def _short(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return ""


def _step_type(name: str) -> str:
    if name == "write_todos":
        return "checklist"
    if name in ("task", "research"):
        return "subagent"
    return "tool"


def build_trace(
    events: list[dict],
    *,
    run_id: str,
    thread_id: str,
    status: str,
    resume: dict | None = None,
    cards: dict[str, Any] | None = None,
    verification: dict | None = None,
    todos: list | None = None,
    state_results: dict[str, dict] | None = None,
) -> dict:
    """The trace from a run's journal events (ordered by seq).

    `cards`: the pending store's actions by id (for outcomes); `resume`: the
    server-owned resume record when this run resumed a turn."""
    cards = cards or {}
    steps: list[dict] = []
    by_call: dict[str, int] = {}
    by_model: dict[str, dict[str, int]] = {}
    llm_calls = 0
    retries = 0
    failed_tools: set[str] = set()
    last_reply: str | None = None
    times = [e.get("created_at") for e in events if e.get("created_at")]

    def add(**step: Any) -> int:
        step.setdefault("parent", None)
        step.setdefault("tier", None)
        step.setdefault("started_at", None)
        step.setdefault("ended_at", step.get("started_at"))
        step.setdefault("args", None)
        step.setdefault("output", None)
        step.setdefault("card_id", None)
        step.setdefault("source_event", None)
        step["index"] = len(steps)
        steps.append(step)
        return step["index"]

    if resume:
        ids = [str(i) for i in resume.get("ids") or []]
        parent = add(type="resume", name=f"resumed after {len(ids)} card(s)", status="ok", started_at=times[0] if times else None)
        for card_id in ids:
            action = cards.get(card_id)
            outcome = str(getattr(action, "outcome", None) or "expired") if action is not None else "unknown"
            add(type="card_resolved", name=getattr(action, "tool_name", "card"), status=outcome, parent=parent, card_id=card_id, tier=3)

    for event in events:
        kind = event.get("event_type")
        meta = event.get("metadata") or {}
        content = event.get("content") if isinstance(event.get("content"), dict) else {}
        seq = str(event.get("seq") or event.get("id") or "") or None
        at = event.get("created_at")
        if kind == "llm.ai.response":
            caller = str(meta.get("caller") or "lead_agent")
            usage = meta.get("usage") or {}
            model = ((content.get("response_metadata") or {}).get("model_name")) or "unknown"
            if usage:
                llm_calls += 1
                bucket = by_model.setdefault(model, {"input": 0, "output": 0, "cached": 0})
                bucket["input"] += int(usage.get("input_tokens") or 0)
                bucket["output"] += int(usage.get("output_tokens") or 0)
                bucket["cached"] += int(((usage.get("input_token_details") or {}).get("cache_read")) or 0)
            if caller.startswith("middleware:summarize"):
                add(type="summary", name="context summarised", status="ok", started_at=at, source_event=seq)
                continue
            if caller != "lead_agent":
                continue
            calls = content.get("tool_calls") or []
            for call in calls:
                name = str(call.get("name") or "")
                by_call[str(call.get("id") or "")] = add(type=_step_type(name), name=name, status="running", started_at=at, args=_short(call.get("args"), _ARGS_MAX), source_event=seq)
            text = _text(content.get("content"))
            if not calls and text.strip():
                last_reply = text
        elif kind == "llm.tool.result":
            call_id = str(content.get("tool_call_id") or "")
            index = by_call.get(call_id)
            output = _text(content.get("content"))
            kwargs = content.get("additional_kwargs") or {}
            stamp = kwargs.get("omniharness_policy_step") if isinstance(kwargs, dict) else None
            failed = content.get("status") == "error" or output.lstrip().lower().startswith("error")
            if index is None:
                index = add(type=_step_type(str(content.get("name") or "")), name=str(content.get("name") or "tool"), status="running", started_at=at, source_event=seq)
            step = steps[index]
            step["ended_at"] = at
            step["output"] = _short(output, _OUTPUT_MAX)
            if isinstance(stamp, dict):
                step["tier"] = stamp.get("tier")
                outcome = stamp.get("outcome")
                if outcome == "needs_confirmation":
                    step["status"] = "needs_confirmation"
                    card_id = stamp.get("card_id")
                    step["card_id"] = card_id
                    action = cards.get(str(card_id)) if card_id else None
                    add(type="card", name=f"card: {step['name']}", status=str(getattr(action, "outcome", None) or "open"), parent=index, card_id=card_id, tier=3, started_at=at, source_event=seq)
                    continue
                if outcome == "refused":
                    step["status"] = "refused"
                    continue
            step["status"] = "error" if failed else "ok"
            if failed:
                failed_tools.add(step["name"])

    # A result the journal did not carry (a card's plan is the policy layer's
    # answer, not a tool run; the policy stamp is added after the tool's own
    # callback), from the thread's checkpointed messages: still events, never
    # the reply's prose.
    for call_id, index in by_call.items():
        result = (state_results or {}).get(call_id)
        if result is None:
            continue
        step = steps[index]
        stamp = result.get("stamp") if isinstance(result.get("stamp"), dict) else None
        if step["status"] == "running":
            step["output"] = _short(result.get("output") or "", _OUTPUT_MAX)
            step["status"] = "error" if result.get("failed") else "ok"
        if stamp:
            step["tier"] = stamp.get("tier")
            if stamp.get("outcome") == "needs_confirmation" and step["status"] != "needs_confirmation":
                step["status"] = "needs_confirmation"
                card_id = stamp.get("card_id")
                step["card_id"] = card_id
                action = cards.get(str(card_id)) if card_id else None
                add(type="card", name=f"card: {step['name']}", status=str(getattr(action, "outcome", None) or "open"), parent=index, card_id=card_id, tier=3, started_at=step.get("started_at"))
            elif stamp.get("outcome") == "refused":
                step["status"] = "refused"

    for step in steps:
        if step["status"] == "running":
            step["status"] = "interrupted" if status != "success" else "ok"

    # Retries, from the steps' statuses (events): a call of a tool after an
    # earlier call of it failed is a retry of that step.
    failed_tools = set()
    for step in list(steps):
        if step["type"] not in ("tool", "subagent"):
            continue
        if step["name"] in failed_tools:
            retries += 1
            add(type="retry", name=f"retry {step['name']}", status=step["status"], parent=step["index"], started_at=step.get("started_at"), source_event=step.get("source_event"))
            failed_tools.discard(step["name"])
        if step["status"] == "error":
            failed_tools.add(step["name"])

    done_criteria = (verification or {}).get("done_criteria")
    if not done_criteria:
        for todo in todos or []:
            text = str((todo or {}).get("content") or "")
            if text.lower().startswith("done when"):
                done_criteria = text.split(":", 1)[-1].strip()
                break
    if verification:
        add(type="verify", name="verification", status=str(verification.get("status") or "none"), started_at=times[-1] if times else None)
    if last_reply is not None:
        add(type="reply", name="final reply", status="ok", output=_short(last_reply, _OUTPUT_MAX), started_at=times[-1] if times else None)

    tokens = {"input": sum(b["input"] for b in by_model.values()), "output": sum(b["output"] for b in by_model.values())}
    tokens["total"] = tokens["input"] + tokens["output"]
    started, finished = (times[0], times[-1]) if times else (None, None)
    duration_ms = None
    try:
        if started and finished:
            duration_ms = int((datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds() * 1000)
    except ValueError:
        duration_ms = None
    card_list = []
    for step in steps:
        if step["type"] == "card" and step.get("card_id"):
            action = cards.get(str(step["card_id"]))
            card_list.append({"id": step["card_id"], "tool": getattr(action, "tool_name", step["name"].removeprefix("card: ")), "tier": 3, "outcome": str(getattr(action, "outcome", None)) if getattr(action, "outcome", None) else None})
    models = [m for m in by_model if m != "unknown"]
    return {
        "version": TRACE_VERSION,
        "run_id": run_id,
        "thread_id": thread_id,
        "status": status,
        "started_at": started,
        "finished_at": finished,
        "duration_ms": duration_ms,
        "model": models[0] if models else None,
        "tokens": tokens,
        "tokens_by_model": by_model,
        "llm_calls": llm_calls,
        "cost_usd": estimate_cost(by_model),
        "resumed_from": {"run_id": (resume or {}).get("from_run_id"), "card_ids": [str(i) for i in (resume or {}).get("ids") or []]} if resume else None,
        "resumes": [],
        "done_criteria": done_criteria,
        "verification": verification,
        "retries": retries,
        "steps": steps,
        "cards": card_list,
    }


async def record_chat_trace(app: Any, *, run_id: str, thread_id: str, status: str, owner_id: str | None, resume: dict | None) -> str:
    """Build and store one lead run's trace; returns the run-history id ("" if
    nothing was stored). Never raises: a trace that cannot be written is
    logged, and the run's own outcome is unaffected."""
    history = getattr(app.state, "run_history", None)
    event_store = getattr(app.state, "run_event_store", None)
    if history is None or event_store is None:
        return ""
    try:
        events = await event_store.list_events(thread_id, run_id, limit=5000)
        cards: dict[str, Any] = {}
        pending = _pending_store()
        card_ids = set(str(i) for i in (resume or {}).get("ids") or [])
        for event in events:
            kwargs = ((event.get("content") or {}) if isinstance(event.get("content"), dict) else {}).get("additional_kwargs") or {}
            stamp = kwargs.get("omniharness_policy_step") if isinstance(kwargs, dict) else None
            if isinstance(stamp, dict) and stamp.get("card_id"):
                card_ids.add(str(stamp["card_id"]))
        if pending is not None:
            for card_id in card_ids:
                action = pending.get(card_id)
                if action is not None:
                    cards[card_id] = action
        verification, todos, state_results = await _final_state(app, thread_id, events)
        for result in state_results.values():
            stamp = result.get("stamp")
            if isinstance(stamp, dict) and stamp.get("card_id") and pending is not None and str(stamp["card_id"]) not in cards:
                action = pending.get(str(stamp["card_id"]))
                if action is not None:
                    cards[str(stamp["card_id"])] = action
        if resume and resume.get("ids"):
            resume = {**resume, "from_run_id": _resumed_from(history, thread_id, set(str(i) for i in resume["ids"]))}
        trace = build_trace(events, run_id=run_id, thread_id=thread_id, status=status, resume=resume, cards=cards, verification=verification, todos=todos, state_results=state_results)
        started = datetime.fromisoformat(trace["started_at"]) if trace.get("started_at") else None
        finished = datetime.fromisoformat(trace["finished_at"]) if trace.get("finished_at") else None
        return history.record(kind=CHAT, source_id=run_id, thread_id=thread_id, body={"trace": trace}, status=status, started_at=started, finished_at=finished, owner_id=owner_id)
    except Exception:  # noqa: BLE001 - the trace is a record of the run, never part of it
        logger.warning("chat trace for run %s could not be recorded", run_id, exc_info=True)
        return ""


def _pending_store() -> Any:
    try:
        from app.policy.registration import build
        from omniharness.config import get_app_config

        middleware = build(get_app_config())
        return getattr(middleware, "pending", None)
    except Exception:  # noqa: BLE001
        return None


async def _final_state(app: Any, thread_id: str, events: list[dict]) -> tuple[dict | None, list | None, dict[str, dict]]:
    """The verification record of this run's final reply, the checklist, and
    each tool result still in the thread (by tool-call id), from the thread's
    checkpoint."""
    checkpointer = getattr(app.state, "checkpointer", None)
    if checkpointer is None:
        return None, None, {}
    try:
        tup = await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
    except Exception:  # noqa: BLE001
        return None, None, {}
    values = ((getattr(tup, "checkpoint", None) or {}).get("channel_values") or {}) if tup is not None else {}
    verifications = values.get("verifications") or {}
    ids = [((e.get("content") or {}).get("id")) for e in events if e.get("event_type") == "llm.ai.response" and isinstance(e.get("content"), dict)]
    record = None
    for message_id in reversed([i for i in ids if i]):
        if message_id in verifications:
            record = verifications[message_id]
            break
    results: dict[str, dict] = {}
    for message in values.get("messages") or []:
        if getattr(message, "type", None) != "tool":
            continue
        output = _text(getattr(message, "content", ""))
        kwargs = getattr(message, "additional_kwargs", None) or {}
        results[str(getattr(message, "tool_call_id", ""))] = {
            "output": output,
            "failed": getattr(message, "status", None) == "error" or output.lstrip().lower().startswith("error"),
            "stamp": kwargs.get("omniharness_policy_step") if isinstance(kwargs, dict) else None,
        }
    return record, values.get("todos"), results


def _resumed_from(history: Any, thread_id: str, card_ids: set[str]) -> str | None:
    """The run whose cards this resume answers: the latest chat trace of the
    thread that raised one of them."""
    try:
        for summary in history.list(kind=CHAT, thread_id=thread_id, limit=20):
            body = (history.get(summary.id) or {}).get("body") or {}
            trace = body.get("trace") if isinstance(body, dict) else None
            if isinstance(trace, dict) and any(str(c.get("id")) in card_ids for c in trace.get("cards") or []):
                return trace.get("run_id")
    except Exception:  # noqa: BLE001
        return None
    return None
