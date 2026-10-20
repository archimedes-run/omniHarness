"""What is waiting on the user, from the trigger engine's side (Phase 2.5, Inbox).

Pending confirmations come from /api/confirmations (listing them runs Feature
004's supersede sweep, so they stay with that router). This is the other half:
alerts — what the engine tried to tell the user, from its audit log, by each
firing's LATEST recorded outcome:

  * waiting        still held (quiet hours, behind an exchange, coalescing)
  * not-delivered  failed or expired: the user missed it
  * suppressed     the engine decided not to send it (shown, not counted)
  * delivered      sent; shown as recent, not counted

`waiting_count` is what the sidebar badge adds to the pending confirmations:
waiting plus not-delivered, within the window, leaving out what the user
dismissed on Home (Feature 006). Pure; reads nothing itself.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel

AlertState = Literal["waiting", "not-delivered", "suppressed", "delivered"]
STATE_OF: dict[str, AlertState] = {"queued": "waiting", "failed": "not-delivered", "expired": "not-delivered", "suppressed": "suppressed", "delivered": "delivered"}
WINDOW = timedelta(hours=24)


class Alert(BaseModel):
    rule_id: str
    event_id: str
    event_type: str
    at: str
    state: AlertState
    #: Verbatim from the audit record.
    reason: str = ""
    #: The rule's conversation, where the message and any reply live.
    thread_id: str | None = None
    #: The user dismissed it on Home: still listed, never counted.
    dismissed: bool = False


def alert_key(rule_id: str, event_id: str) -> str:
    """The one key a dismissal names an alert by (Home sends the same)."""
    return f"{rule_id}:{event_id}"


class InboxAlerts(BaseModel):
    alerts: list[Alert]
    waiting_count: int
    #: False when the dismissals could not be read: the count may then include
    #: alerts the user already dismissed.
    dismissals_readable: bool = True


def describe_alerts(audit: list[dict], *, now: datetime, window: timedelta = WINDOW, dismissed: set[str] | frozenset[str] = frozenset(), dismissals_readable: bool = True) -> InboxAlerts:
    latest: dict[tuple[str, str], dict] = {}
    for e in audit:
        key = (e.get("rule_id", ""), e.get("event_id", ""))
        if key not in latest or e.get("at", "") >= latest[key].get("at", ""):
            latest[key] = e
    out = []
    for e in sorted(latest.values(), key=lambda e: e.get("at", ""), reverse=True):
        state = STATE_OF.get(e.get("outcome", ""))
        if state is None:
            continue
        try:
            at = datetime.fromisoformat(e.get("at", ""))
        except ValueError:
            continue
        # A held firing is waiting however old it is; everything else is
        # listed only within the window.
        if state != "waiting" and now - at > window:
            continue
        rule_id, event_id = e.get("rule_id", ""), e.get("event_id", "")
        gone = alert_key(rule_id, event_id) in dismissed
        out.append(Alert(rule_id=rule_id, event_id=event_id, event_type=e.get("event_type", ""), at=e.get("at", ""), state=state, reason=e.get("reason", ""), thread_id=e.get("thread_id"), dismissed=gone))
    return InboxAlerts(alerts=out, waiting_count=sum(1 for a in out if a.state in ("waiting", "not-delivered") and not a.dismissed), dismissals_readable=dismissals_readable)
