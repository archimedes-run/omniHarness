"""What the triggers surface shows (Feature 004, US2): why a rule produced nothing.

Read at request time from the engine's own durable state — the rule file, the
evaluation log (FR-020) and the audit log — so every worker answers the same,
whichever one runs the engine.

Three rule conditions that used to look identical (FR-017, SC-009):
never evaluated · evaluated, never fired · fired.

"Not recorded" is not "never" (FR-022). A rule that has firings but no
evaluation record was evaluated before evaluation times were kept; an audit row
without a `batch_id` KEY was written before batches were. Both read as "not
recorded", never as a recorded absence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

Activity = Literal["never-evaluated", "evaluated-never-fired", "fired"]
Recorded = Literal["recorded", "never", "not-recorded"]
#: When the rule next runs, as far as the server can say (Feature 006):
#: scheduled (next_run_at holds the instant) · off (the rule is switched off)
#: · engine-off (nothing runs any rule) · on-event (a watcher rule runs when
#: its event happens, so there is no time to give) · cant-tell (the schedule
#: could not be computed; never a guessed time).
NextRun = Literal["scheduled", "off", "engine-off", "on-event", "cant-tell"]
#: One run of a rule, as the Automations history words it (Automations.dc.html):
#: delivered · held-then-delivered · delivered-with-others · failed ·
#: pending (held or awaiting delivery; not settled) · cant-tell.
RunKind = Literal["delivered", "held-then-delivered", "delivered-with-others", "failed", "pending", "cant-tell"]
#: Why a run was held, from the outcome the engine recorded: QUEUED behind an
#: exchange, SUPPRESSED by quiet hours, or anything else (reason verbatim).
HeldBecause = Literal["mid-conversation", "quiet-hours", "other"]

#: The coalescing wait every delivery passes through. Not a hold: a run that
#: only waited for the window was delivered on time.
COALESCING_REASON = "awaiting the coalescing window"


class RuleView(BaseModel):
    id: str
    #: The display name the person gave it; empty for a rule written without one.
    name: str = ""
    type: str
    enabled: bool
    match: dict
    #: What the rule asks the assistant, where the answer goes, and whether it
    #: may interrupt quiet hours: what the Automations edit form shows.
    prompt: str = ""
    destination: str = "auto"
    urgent: bool = False
    activity: Activity
    last_evaluated_at: str | None = None
    last_evaluated: Recorded
    last_fired_at: str | None = None
    last_outcome: str | None = None
    next_run: NextRun = "cant-tell"
    #: ISO instant, in the rule's own zone, when next_run is "scheduled".
    next_run_at: str | None = None


class QuietHoursView(BaseModel):
    enabled: bool
    start: str
    end: str
    timezone: str


class BatchMember(BaseModel):
    rule_id: str
    event_id: str


class FiringView(BaseModel):
    at: str
    rule_id: str
    event_type: str
    event_id: str
    outcome: str
    #: VERBATIM from the audit record (FR-019). Never summarised.
    reason: str
    #: alone | batched | not-recorded (FR-021, FR-022)
    batch: Literal["alone", "batched", "not-recorded"]
    batch_id: str | None = None
    #: The OTHER firings delivered in the same message, resolved here (T053).
    delivered_with: list[BatchMember] = []
    #: The conversation the firing ran in, when the record names one.
    thread_id: str | None = None


class RunView(BaseModel):
    """One run of one rule: every audit record for one event, read together.

    The audit log has a row per state change (held, then delivered), so a
    single run is several rows. The wording is decided here, from the records,
    and never guessed: a run whose records do not settle it is `pending` or
    `cant-tell`, and says so.
    """

    event_id: str
    #: When it was due: the scheduled instant for a cron run (its event id),
    #: otherwise when it was first recorded.
    at: str
    kind: RunKind
    #: When the final record was written (the delivery time, for a held run).
    settled_at: str
    #: The final record's reason, VERBATIM (FR-019); empty for a delivery.
    reason: str = ""
    held_because: HeldBecause | None = None
    #: The hold's own reason, verbatim, when held_because is "other".
    held_reason: str = ""
    delivered_with: list[BatchMember] = []
    #: Whether it went out alone is unknown: the record predates batch ids.
    batch_not_recorded: bool = False
    thread_id: str | None = None


class RunsView(BaseModel):
    rule_id: str
    runs: list[RunView]


class RulesView(BaseModel):
    engine_enabled: bool
    rules: list[RuleView]
    rules_error: str | None = None
    #: Hash of the rule file's bytes. An edit names the version it was based
    #: on, and is refused if the file changed since (no clobbered hand edits).
    version: str | None = None
    #: False when no rules_path is configured: the engine is running the
    #: shipped defaults, which are not edited in place. `not_writable_reason`
    #: says so, for the page to show instead of edit controls.
    writable: bool = False
    not_writable_reason: str | None = None
    #: The quiet hours in the rule file (None: the file could not be read).
    quiet_hours: QuietHoursView | None = None


class FiringsView(BaseModel):
    firings: list[FiringView]


def describe_rules(
    *,
    rules: list,
    evaluated: dict[str, str | None],
    audit: list[dict],
    engine_enabled: bool,
    rules_error: str | None = None,
    version: str | None = None,
    writable: bool = False,
    not_writable_reason: str | None = None,
    quiet_hours=None,
    now: datetime | None = None,
) -> RulesView:
    """Pure. `evaluated` maps rule id -> last evaluated ISO time (absent: no record)."""
    now = now or datetime.now(UTC)
    out = []
    for rule in rules:
        mine = [e for e in audit if e.get("rule_id") == rule.id]
        last = max(mine, key=lambda e: e.get("at", "")) if mine else None
        stamp = evaluated.get(rule.id)
        if stamp:
            recorded: Recorded = "recorded"
        elif mine:
            recorded = "not-recorded"  # it fired, so it was evaluated: before FR-020 kept the time
        else:
            recorded = "never"
        if last is not None:
            activity: Activity = "fired"
        elif stamp:
            activity = "evaluated-never-fired"
        else:
            activity = "never-evaluated"
        out.append(
            RuleView(
                id=rule.id,
                name=getattr(rule, "name", ""),
                type=str(rule.type),
                enabled=rule.enabled,
                match=dict(rule.match),
                prompt=rule.prompt,
                destination=str(rule.destination),
                urgent=rule.urgent,
                activity=activity,
                last_evaluated_at=stamp,
                last_evaluated=recorded,
                last_fired_at=last.get("at") if last else None,
                last_outcome=last.get("outcome") if last else None,
                **next_run(rule, now=now, engine_enabled=engine_enabled),
            )
        )
    qh = None
    if quiet_hours is not None:
        qh = QuietHoursView(enabled=quiet_hours.enabled, start=quiet_hours.start, end=quiet_hours.end, timezone=quiet_hours.timezone)
    return RulesView(engine_enabled=engine_enabled, rules=out, rules_error=rules_error, version=version, writable=writable, not_writable_reason=not_writable_reason, quiet_hours=qh)


def next_run(rule, *, now: datetime, engine_enabled: bool) -> dict:
    """When `rule` next runs, computed with the scheduler's own function (the
    one the engine fires by), in the rule's zone. Never a guess: a schedule that
    cannot be computed is "cant-tell"."""
    from app.trigger_engine.scheduler import next_due

    if not engine_enabled:
        return {"next_run": "engine-off"}
    if not rule.enabled:
        return {"next_run": "off"}
    if str(rule.type) != "cron":
        return {"next_run": "on-event"}
    try:
        due = next_due(str(rule.match["schedule"]), now, rule.match.get("timezone") or None)
    except Exception:  # noqa: BLE001 — any failure means "cannot say", not a time
        return {"next_run": "cant-tell"}
    return {"next_run": "scheduled", "next_run_at": due.isoformat()}


def describe_firings(audit: list[dict], *, limit: int = 200) -> FiringsView:
    """Pure. Newest first; each delivered firing names its batch-mates."""
    batches: dict[str, list[dict]] = {}
    for e in audit:
        if e.get("batch_id"):
            batches.setdefault(e["batch_id"], []).append(e)
    out = []
    for e in sorted(audit, key=lambda e: e.get("at", ""), reverse=True)[:limit]:
        if "batch_id" not in e:
            batch, mates = "not-recorded", []
        elif e["batch_id"] is None:
            batch, mates = "alone", []
        else:
            batch = "batched"
            mates = [BatchMember(rule_id=m["rule_id"], event_id=m["event_id"]) for m in batches[e["batch_id"]] if (m["rule_id"], m["event_id"]) != (e["rule_id"], e["event_id"])]
        out.append(
            FiringView(
                at=e.get("at", ""),
                rule_id=e.get("rule_id", ""),
                event_type=e.get("event_type", ""),
                event_id=e.get("event_id", ""),
                outcome=e.get("outcome", ""),
                reason=e.get("reason", ""),
                batch=batch,
                batch_id=e.get("batch_id"),
                delivered_with=mates,
                thread_id=e.get("thread_id"),
            )
        )
    return FiringsView(firings=out)


def _mates(entry: dict, audit: list[dict]) -> list[BatchMember]:
    bid = entry.get("batch_id")
    if not bid:
        return []
    seen: set[tuple[str, str]] = set()
    out = []
    for m in audit:
        key = (m.get("rule_id", ""), m.get("event_id", ""))
        if m.get("batch_id") == bid and key != (entry.get("rule_id"), entry.get("event_id")) and key not in seen:
            seen.add(key)
            out.append(BatchMember(rule_id=key[0], event_id=key[1]))
    return out


def _held(rows: list[dict]) -> tuple[HeldBecause, str] | None:
    """The first real hold among a run's earlier records, if any."""
    for r in rows:
        if r.get("outcome") == "suppressed":
            return "quiet-hours", r.get("reason", "")
        if r.get("outcome") == "queued" and r.get("reason", "") != COALESCING_REASON:
            reason = r.get("reason", "")
            return ("mid-conversation" if reason.startswith("user is mid-exchange") else "other"), reason
    return None


def _instant(value: str) -> datetime:
    try:
        t = datetime.fromisoformat(value)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _due_at(event_type: str, event_id: str, fallback: str) -> str:
    if event_type == "cron":
        try:
            return datetime.fromisoformat(event_id).isoformat()
        except ValueError:
            pass
    return fallback


def describe_runs(audit: list[dict], rule_id: str, *, limit: int = 50) -> RunsView:
    """Pure. One rule's runs, newest first, each worded from its records."""
    groups: dict[str, list[dict]] = {}
    for e in audit:
        if e.get("rule_id") == rule_id:
            groups.setdefault(e.get("event_id", ""), []).append(e)
    runs = []
    for event_id, rows in groups.items():
        rows.sort(key=lambda e: e.get("at", ""))
        final = rows[-1]
        outcome = final.get("outcome")
        held = _held(rows[:-1])
        thread = next((r.get("thread_id") for r in reversed(rows) if r.get("thread_id")), None)
        run = RunView(
            event_id=event_id,
            at=_due_at(final.get("event_type", ""), event_id, rows[0].get("at", "")),
            kind="cant-tell",
            settled_at=final.get("at", ""),
            reason=final.get("reason", "") if outcome != "delivered" else "",
            thread_id=thread,
        )
        if outcome == "delivered":
            mates = _mates(final, audit)
            run.delivered_with = mates
            run.batch_not_recorded = "batch_id" not in final
            if held is not None:
                run.kind = "held-then-delivered"
                run.held_because, why = held
                run.held_reason = why if run.held_because == "other" else ""
            elif mates:
                run.kind = "delivered-with-others"
            else:
                run.kind = "delivered"
        elif outcome in ("failed", "expired"):
            run.kind = "failed"
        elif outcome in ("queued", "suppressed"):
            run.kind = "pending"
            hold = _held([final])
            if hold is not None:
                run.held_because, why = hold
                run.held_reason = why if run.held_because == "other" else ""
        runs.append(run)
    runs.sort(key=lambda r: _instant(r.at), reverse=True)
    return RunsView(rule_id=rule_id, runs=runs[:limit])
