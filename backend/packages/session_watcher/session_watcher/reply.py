"""Reply composition — where every wording rule we accumulated actually lands.

Five clarifications converge here, and each is easy to satisfy in isolation while
producing something that reads badly as a whole. The rules, and the failure each
one prevents:

  * CAVEAT FIRST when data is stale (FR-011b). A trailing caveat can be acted on
    before it is heard, and a later phase will speak these aloud.
  * HEDGE LEADS for anything inferred (FR-016a). "finished 10 minutes ago" is a
    fact; "hasn't moved in 12 minutes, may have stalled" is an inference, and the
    sentence has to sound like one.
  * COMPLETED and STALLED never collapse (FR-003a). Different facts, different
    user action.
  * EMPTY and UNOBSERVABLE never collapse (FR-011a). "No sessions are running" is
    sayable only when we actually looked.
  * ABSENT IS ABSENT (FR-016). Nothing is estimated to fill a gap.
  * "recognized patterns", never the stronger claim (FR-011d).

The composed text is the product. Read it aloud when changing anything here.
"""

from __future__ import annotations

CANT_RELAY = "can't safely relay this, check locally"


def humanize(seconds: int) -> str:
    """Plain-English duration. Deliberately coarse — false precision is a defect."""
    if seconds < 0:
        return "an unknown time"
    if seconds < 60:
        return "less than a minute"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours = minutes // 60
    if hours < 24:
        rem = minutes % 60
        base = f"{hours} hour{'s' if hours != 1 else ''}"
        return f"{base} and {rem} minutes" if rem and hours < 3 else base
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''}"


def _progress(s: dict) -> str:
    """The agent's own plan, as of its last confirmed update: "plan 3/5 done"."""
    todos = s.get("todos")
    if not todos:
        return ""
    done = sum(1 for t in todos if t.get("status") == "completed")
    return f" Plan {done}/{len(todos)} done."


def _continued(s: dict) -> str:
    """The recorded link between a session and its continuation, said as such.

    Observed, not inferred: the earlier session's own record names the later
    one. Ids are shortened to eight characters, as the ambiguity prompt does.
    """
    if s.get("continued_from"):
        return f" Continued from an earlier session ({str(s['continued_from'])[:8]}); shown as one."
    if s.get("continued_in"):
        return f" Continued in another session ({str(s['continued_in'])[:8]}), which I can't see."
    return ""


def _line(s: dict, *, label: bool = False) -> str:
    """One session, worded by how well we actually know its state.

    `label` names the agent ("omniHarness (Codex)"). It is on whenever more
    than one agent is in the reply, and always for a non-Claude session, so a
    Claude-only reply reads as it always has.
    """
    project = s.get("project") or "(unknown project)"
    if label or (s.get("agent") and s.get("agent") != "claude"):
        project = f"{project} ({s.get('agent_label') or s.get('agent')})"
    quiet = humanize(int(s.get("quiet_seconds", -1)))
    summary = (s.get("summary") or "").strip()
    state = s.get("state")
    reason = s.get("idle_reason")

    if s.get("relay_suppressed"):
        # FR-011e: suppressed rather than sent unredacted. Say so plainly.
        return f"{project} — {CANT_RELAY}."

    if state == "working":
        head = f"{project} — working, last activity {quiet} ago"
    elif state == "waiting-on-user":
        # PURE INFERENCE (spike R2b: the format carries no pending-prompt signal).
        # The hedge LEADS and the observable evidence follows it, so the sentence
        # sounds like the inference it is. Required shape:
        #   "Looks like it's waiting on you — last activity was N ago, nothing since"
        # Forbidden shape:
        #   "It's waiting for your input"   <- states an inference as an observation
        head = f"{project} — looks like it's waiting on you; last activity was {quiet} ago, nothing since"
    elif state == "idle" and reason == "completed":
        # OBSERVED end-of-turn. Stated as fact, with no hedge, because hedging a
        # fact is its own dishonesty.
        head = f"{project} — finished {quiet} ago"
    elif state == "idle" and reason == "stalled":
        # INFERRED from silence. The hedge LEADS the clause.
        head = f"{project} — hasn't moved in {quiet}; may have stalled or been killed"
    elif state == "failed":
        head = f"{project} — failed {quiet} ago"
    else:  # unknown
        # FR-006: we could not interpret the records. Do not dress this up.
        return f"{project} — I can't tell what state it's in; its records didn't parse."

    line = f"{head}. {summary}" if summary else f"{head}."
    return line + _progress(s) + _continued(s)


def _unreadable(payload: dict) -> str:
    """Agents whose files cannot be read: never silently "no sessions" (FR-026)."""
    missing = [a for a in payload.get("agents") or [] if not a.get("readable")]
    return " ".join(f"I can't read {a.get('label') or a.get('agent')} sessions: {a.get('reason')}." for a in missing)


def compose_rollup(payload: dict) -> str:
    """The roll-up, as the user hears it."""
    sessions = payload.get("sessions") or []
    observable = bool(payload.get("observable"))
    observability = payload.get("observability")
    staleness = int(payload.get("staleness_seconds", -1))

    label = len({s.get("agent") for s in sessions}) > 1
    unreadable = _unreadable(payload)
    if observable:
        if not sessions:
            # Safe to say ONLY because we looked and the registry is current,
            # and only for the agents we could read.
            return f"No coding sessions are running. {unreadable}".strip() if unreadable else "No coding sessions are running."
        head = f"{len(sessions)} session{'s' if len(sessions) != 1 else ''}:"
        body = "\n".join([head, *(f"  • {_line(s, label=label)}" for s in sessions)])
        return f"{body}\n{unreadable}" if unreadable else body

    # --- not observable: the caveat LEADS, always ---
    if observability == "never-observed" or staleness < 0:
        caveat = "I can't see your coding sessions right now — the watcher hasn't reported yet, so I don't know whether any are running."
        return caveat

    caveat = f"I haven't seen your sessions for {humanize(staleness)} — the watcher stopped reporting, so this may be out of date."
    if not sessions:
        # THE false negative this whole mechanism exists to prevent. Note what is
        # absent: any claim about whether sessions are running.
        return caveat + " I have no last-known state to fall back on either."
    body = "\n".join(f"  • {_line(s, label=label)}" for s in sessions)
    return f"{caveat}\nAs of then, {len(sessions)} session{'s' if len(sessions) != 1 else ''}:\n{body}"


def compose_status(payload: dict) -> str:
    """Single-session detail, same rules."""
    observable = bool(payload.get("observable"))
    staleness = int(payload.get("staleness_seconds", -1))
    prefix = ""
    if not observable:
        if staleness < 0:
            return "I can't see your coding sessions right now — the watcher hasn't reported yet."
        prefix = f"I haven't seen your sessions for {humanize(staleness)} — the watcher stopped reporting, so this may be out of date. As of then: "

    if payload.get("ambiguous"):
        cands = payload.get("candidates") or []
        listed = "; ".join(cands)
        return f"{prefix}More than one session matches — which did you mean? {listed}"

    if not payload.get("found"):
        return f"{prefix}I don't have a session matching that."

    s = payload.get("session") or {}
    elapsed = humanize(int(s.get("elapsed_seconds", -1)))
    # Elapsed goes in the head, not after the summary: summaries routinely end
    # mid-clause or on a colon, and a trailing sentence reads like a non-sequitur.
    line = _line({**s, "summary": "", "continued_from": None, "continued_in": None}).rstrip(".")
    summary = (s.get("summary") or "").strip()
    head = f"{prefix}{line}, running {elapsed} in total.{_continued(s)}"
    return f"{head} {summary}" if summary else head


def observe_only_notice() -> str:
    """FR-015 — stated plainly, with no suggestion we might do it anyway."""
    return "I can only watch sessions that were started outside me — I can't answer or intervene in them in this version. You'd need to do that at the machine."
