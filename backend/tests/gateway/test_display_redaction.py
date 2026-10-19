"""T091/T092 — outside content passes the redactor before a surface shows it (FR-031, SC-015).

Three surfaces show text the assistant did not write: session summaries (from
session records), and the plan and targets of a confirmation and of a recorded
Tier 3 execution (worded from emails and pages). Each is checked two ways:

  * a planted credential is redacted, so the redactor really runs on the path;
  * content that FAILS redaction is withheld, visibly: `withheld` is set and a
    sentence says so. It is never shown raw, and never shown as empty.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient
from session_watcher.redaction import RedactionError

from app.gateway import display_redaction
from app.gateway.display_redaction import WITHHELD
from app.gateway.routers import confirmations
from app.gateway.routers import policy as policy_router
from app.gateway.sessions_view import describe_sessions
from app.policy.models import Outcome, PendingAction, Tier

#: Obviously fake, in the shape the redactor recognises.
FAKE = "sk-test-FAKEFAKEFAKEFAKE1234"


def _session(**fields) -> dict:
    return {"sessions": [{"session_id": "s1", "project": "demo", "state": "working", **fields}], "observability": "live"}


def _break_the_redactor(monkeypatch) -> None:
    """Fault injection where no real input makes the redactor raise."""

    def broken(text, channel=None):
        raise RedactionError("injected")

    monkeypatch.setattr(display_redaction, "redact", broken)


# --- sessions --------------------------------------------------------------


def test_a_session_summary_is_redacted() -> None:
    [row] = describe_sessions(_session(summary=f"exported OPENAI_API_KEY={FAKE} and reran")).sessions

    assert FAKE not in row.summary and "[redacted]" in row.summary
    assert row.withheld is False


def test_a_summary_that_fails_redaction_is_withheld_visibly() -> None:
    """Real input, no injection: the watcher's payload is JSON from another
    process, and a summary that is not a string makes the redactor raise."""
    [row] = describe_sessions(_session(summary={"text": FAKE})).sessions

    assert row.withheld is True
    assert row.summary == WITHHELD, "suppressed, but displayed as something other than a withholding"
    assert FAKE not in row.model_dump_json()


# --- confirmations -----------------------------------------------------------


def _action(plan: str, targets: list[str]) -> PendingAction:
    return PendingAction(plan_text=plan, tool_name="gmail_send", arguments={}, targets=targets, tier_at_statement=Tier.TIER_3, expires_at=datetime.now(UTC) + timedelta(hours=1))


def test_a_confirmation_plan_and_its_targets_are_redacted() -> None:
    view = confirmations._view(_action(f"I will forward the mail containing {FAKE}", [f"Re: key {FAKE}", "Standup"]), threshold=5)

    assert FAKE not in view.plan_text and FAKE not in "".join(view.targets)
    assert view.targets[1] == "Standup" and view.withheld is False


def test_a_confirmation_that_fails_redaction_is_withheld_and_still_counts_its_targets(monkeypatch) -> None:
    _break_the_redactor(monkeypatch)
    view = confirmations._view(_action(f"I will forward {FAKE}", ["a", "b", "c"]), threshold=2)

    assert view.withheld is True and view.plan_text == WITHHELD
    assert FAKE not in view.model_dump_json()
    assert view.requires_typed_count is True, "withholding the wording must not weaken the typed-count gate"


# --- the policy audit, through its route ----------------------------------------


@pytest.fixture
def audit_client(tmp_path, monkeypatch):
    from app.policy.audit import PolicyAuditLog

    app_config = SimpleNamespace(policy=SimpleNamespace(enabled=True, rules_path=str(tmp_path / "rules.yaml"), state_dir=str(tmp_path / "state")))
    monkeypatch.setattr("omniharness.config.get_app_config", lambda: app_config)
    action = _action(f"I will delete the page that printed {FAKE}", [f"page {FAKE}"])
    action.claimed_by = "worker-1"
    action.resolve(Outcome.EXECUTED)
    PolicyAuditLog(path=tmp_path / "state" / "audit.jsonl", actor="default").record_tier3(action)
    app = make_authed_test_app()
    app.include_router(policy_router.router)
    return TestClient(app)


def test_the_audit_route_redacts_the_plan_as_stated(audit_client) -> None:
    [row] = audit_client.get("/api/policy/audit").json()

    assert FAKE not in row["plan_as_stated"] and "[redacted]" in row["plan_as_stated"]
    assert FAKE not in "".join(row["targets"]) and row["withheld"] is False


def test_the_audit_route_withholds_visibly_when_redaction_fails(audit_client, monkeypatch) -> None:
    _break_the_redactor(monkeypatch)
    resp = audit_client.get("/api/policy/audit")

    assert FAKE not in resp.text
    [row] = resp.json()
    assert row["withheld"] is True and row["plan_as_stated"] == WITHHELD
