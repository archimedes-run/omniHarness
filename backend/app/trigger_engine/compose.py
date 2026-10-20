"""How a proactive message reads (FR-004, Article X).

The assistant is speaking first here, which changes the standard. A reply the
user asked for can afford to be terse; a message that arrives unbidden has to
justify its own interruption in its first clause, or it trains the user to
ignore the next one.

Two rules carried from Feature 001, because the same honesty applies whether
the assistant was asked or not:

  * anything INFERRED leads with its hedge — "looks like it's waiting on you",
    never "it is waiting for your input"
  * anything OBSERVED is stated plainly, without a hedge, because hedging a
    fact is its own dishonesty
"""

from __future__ import annotations

from datetime import datetime
from string import Formatter

from .models import Rule, TriggerEvent


class _Missing(dict):
    """Renders an absent field as an explicit gap rather than a crash.

    Templates are validated at load (config.AVAILABLE_FIELDS), so this is a
    belt-and-braces path. When it fires, the gap is visible in the output
    instead of the message silently reading as though the field were empty.
    """

    def __missing__(self, key: str) -> str:
        return f"<{key} unavailable>"


#: Event text in a prompt is QUOTED: ⟦<event type> <field>: <value>⟧. Whoever
#: wrote it (the sender of a calendar invite, a session's last message) is
#: not the user, so the model is shown where it starts and ends, and the
#: policy layer labels a write it steers by it (lineage.source_label: "from:
#: calendar event “…”"), never as the schedule's own prompt (review round 3).
EVENT_OPEN, EVENT_CLOSE = "⟦", "⟧"

#: The fields an outside party writes (an invite's sender, a session's last
#: message). Engine-made fields (scheduled_at, state, ids, times) are not
#: quoted.
UNTRUSTED_FIELDS = frozenset({"last_message", "idle_reason", "summary", "attendees", "description"})


class _Quoted(_Missing):
    def __init__(self, fields: dict, kind: str):
        super().__init__(fields)
        self.kind = kind

    def __getitem__(self, key: str) -> str:
        value = super().__getitem__(key) if key in self else self.__missing__(key)
        if key not in self or key not in UNTRUSTED_FIELDS:
            return value
        clean = str(value).replace(EVENT_OPEN, "").replace(EVENT_CLOSE, "")
        return f"{EVENT_OPEN}{self.kind} {key}: {clean}{EVENT_CLOSE}"


def render_prompt(rule: Rule, event: TriggerEvent) -> str:
    """The prompt injected as the synthetic user turn, with every value taken
    from the event quoted (EVENT_OPEN … EVENT_CLOSE)."""
    kind = getattr(getattr(event, "type", None), "value", None) or "event"
    fields = _Quoted(dict(event.fields), str(kind))
    return Formatter().vformat(rule.prompt, (), fields)


def compose_proactive(rule: Rule, event: TriggerEvent, reply: str, *, late: bool = True) -> str:
    """The message actually delivered.

    The agent's reply is the substance; this frames it so the user knows why
    their phone buzzed without having to infer it.
    """
    reply = (reply or "").strip()
    project = str(event.fields.get("project") or "").strip()

    if event.type.value == "watcher":
        state = str(event.fields.get("state") or "")
        if state == "waiting-on-user":
            # INFERRED (Feature 001 R2b: nothing in the record distinguishes a
            # permission prompt from a pause). The hedge leads.
            head = f"{project} looks like it's waiting on you" if project else "A session looks like it's waiting on you"
        elif state == "failed":
            head = f"{project} failed" if project else "A session failed"
        else:
            head = f"{project}" if project else "A session"
        return f"{head}.\n\n{reply}" if reply else f"{head}."

    body = reply or "(the assistant returned nothing)"
    return with_late_note(event, body) if late else body


def with_late_note(event: TriggerEvent, body: str, *, now: datetime | None = None, held: bool = False) -> str:
    note = late_note(event, now=now, held=held)
    return f"{note}\n\n{body}" if note else body


#: A scheduled firing later than this says so. The loop wakes AT the scheduled
#: instant, so anything past a few minutes means it was not running then, or
#: the message was held. A stated threshold, not a measured one.
LATE_AFTER_SECONDS = 5 * 60


def late_note(event: TriggerEvent, *, now: datetime | None = None, held: bool = False) -> str:
    """Why a scheduled message is arriving now and not when it was due.

    Without it a 08:45 briefing delivered at 10:05 reads as current, and runs
    that were skipped are silently absent. Both are facts the engine OBSERVED,
    so they are stated plainly (FR-018). `held` says the delay was a
    conversation in progress rather than the engine being down (FR-016d).
    """
    if event.type.value != "cron":
        return ""
    late = int((now - event.at).total_seconds()) if now is not None else int(event.fields.get("late_by_seconds") or 0)
    skipped = int(event.fields.get("skipped") or 0)
    if late < LATE_AFTER_SECONDS and not skipped:
        return ""
    parts = []
    if late >= LATE_AFTER_SECONDS:
        why = "and held while you were mid-conversation" if held else "when I was not running"
        parts.append(f"Running late: this was scheduled for {event.at:%H:%M} {event.at:%Z}".rstrip() + f", {_ago(late)} ago, {why}.")
    if skipped:
        parts.append(f"{skipped} earlier scheduled run{'s were' if skipped != 1 else ' was'} missed while I was not running, and skipped rather than replayed.")
    return " ".join(parts)


def _ago(seconds: int) -> str:
    minutes = seconds // 60
    if minutes < 90:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60} min"
