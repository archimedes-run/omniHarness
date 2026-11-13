"""The three read-only checks (Spec 011 FR-010), each on its own.

A write tool must be unreachable through any manifest. Each check refuses a
catalog entry naming GMAIL_DELETE_MESSAGE by itself, so removing any one check
still leaves the source refused; and each check has a test that passes only
because THAT check is there (the others are forced to pass).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

import app.policy as policy_pkg
from app.gateway.apps import catalog, checks
from app.policy.config import ConfigLoader
from app.policy.models import Tier

RULES_FILE = Path(policy_pkg.__file__).parent / "default_rules.yaml"
SHIPPED = ConfigLoader(path=RULES_FILE).load()
NOW = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)
GMAIL = catalog.CATALOG["gmail.unread_subjects"]
#: A catalog entry someone added by mistake: a write tool dressed as a read.
DELETER = replace(GMAIL, id="gmail.delete_for_test", tool="GMAIL_DELETE_MESSAGE")


def test_every_shipped_connector_entry_passes_all_three() -> None:
    assert not SHIPPED.unreadable
    for entry in catalog.CATALOG.values():
        args = entry.arguments(_params(entry), NOW) if entry.arguments else {}
        assert checks.read_only_refusal(entry, args, SHIPPED) is None, entry.id


def _params(entry):
    return {k: (p.default if not p.required else p.values[0]) for k, p in entry.params.items()}


def test_allowlist_refuses_a_write_tool() -> None:
    assert checks.check_allowlist(DELETER) == "GMAIL_DELETE_MESSAGE is not in the catalog's read allowlist"


def test_tier_refuses_a_write_tool() -> None:
    assert checks.check_tier(DELETER, {}, SHIPPED) == "GMAIL_DELETE_MESSAGE is not Tier 1 in the policy rules"


def test_tier_refuses_when_rules_are_unreadable_or_missing() -> None:
    from app.policy.config import RuleSet

    assert checks.check_tier(GMAIL, {}, RuleSet(unreadable=True)) == "the policy rules could not be read"
    assert checks.check_tier(GMAIL, {}, None) == "the policy rules could not be read"


def test_tier_refuses_an_allowlisted_tool_the_rules_no_longer_make_tier_1(tmp_path) -> None:
    """Allowlist and floor pass; only the tier check stands between the tool and a run."""
    text = tmp_path / "rules.yaml"
    raw = RULES_FILE.read_text()
    text.write_text(raw.replace('    - pattern: "connector-gmail_GMAIL_FETCH_EMAILS"\n      tier: 1', '    - pattern: "connector-gmail_GMAIL_FETCH_EMAILS"\n      tier: 2', 1))
    raised = ConfigLoader(path=text).load()
    assert not raised.unreadable
    args = GMAIL.arguments({"limit": 25}, NOW)
    assert checks.check_allowlist(GMAIL) is None and checks.check_floor(GMAIL) is None
    assert checks.read_only_refusal(GMAIL, args, raised) == "GMAIL_FETCH_EMAILS is not Tier 1 in the policy rules"


def test_tier_refuses_a_tool_with_no_rule() -> None:
    nameless = replace(GMAIL, tool="GMAIL_SOMETHING_NEW_NEXT_YEAR")
    assert checks.check_tier(nameless, {}, SHIPPED) == "GMAIL_SOMETHING_NEW_NEXT_YEAR has no policy rule"


def test_allowlist_alone_refuses_when_the_rules_would_allow(monkeypatch) -> None:
    """Tier and floor forced to pass: only the allowlist refuses."""
    monkeypatch.setattr(checks, "check_tier", lambda *a, **k: None)
    monkeypatch.setattr(checks, "check_floor", lambda *a, **k: None)
    assert checks.read_only_refusal(DELETER, {}, SHIPPED) == "GMAIL_DELETE_MESSAGE is not in the catalog's read allowlist"


def test_tier_alone_refuses_when_the_allowlist_would_allow(monkeypatch) -> None:
    monkeypatch.setattr(checks, "check_allowlist", lambda *a, **k: None)
    monkeypatch.setattr(checks, "check_floor", lambda *a, **k: None)
    assert checks.read_only_refusal(DELETER, {}, SHIPPED) == "GMAIL_DELETE_MESSAGE is not Tier 1 in the policy rules"


def test_floor_alone_refuses(monkeypatch) -> None:
    """A runtime floor on a read tool: allowlist and tier forced to pass."""
    monkeypatch.setattr(checks, "runtime_floor", lambda name: Tier.TIER_3 if name.endswith("gmail_fetch_emails") else None)
    monkeypatch.setattr(checks, "check_allowlist", lambda *a, **k: None)
    monkeypatch.setattr(checks, "check_tier", lambda *a, **k: None)
    assert checks.read_only_refusal(GMAIL, {}, SHIPPED) == "a runtime floor applies to GMAIL_FETCH_EMAILS"


def test_registration_refuses_a_write_tool_entry(gateway, apps, monkeypatch) -> None:
    from app.gateway.apps.registry import AppRegistrationError

    monkeypatch.setitem(catalog.CATALOG, DELETER.id, DELETER)
    with pytest.raises(AppRegistrationError) as err:
        apps.register({"schema": 1, "name": "x", "sources": {"bad": {"use": DELETER.id, "fields": ["subject"]}}})
    assert err.value.code == "source_refused"
    assert gateway.client.get("/api/apps").json()["apps"] == [], "nothing was stored"


def test_run_refuses_a_write_tool_entry_even_with_a_grant(gateway, composio, apps, monkeypatch) -> None:
    """Registered while the entry looked like a read; the entry changes; the run refuses it."""
    composio.connect("GMAIL")
    reg = apps.register({"schema": 1, "name": "x", "sources": {"inbox": {"use": "gmail.unread_subjects", "fields": ["subject"]}}})
    apps.approve(reg.app_id)
    monkeypatch.setitem(catalog.CATALOG, "gmail.unread_subjects", replace(GMAIL, tool="GMAIL_DELETE_MESSAGE"))
    resp = gateway.client.get(f"/api/apps/{reg.app_id}/data/inbox")
    assert resp.status_code == 403 and resp.json()["detail"]["code"] == "source_refused"
    batch = gateway.client.get(f"/api/apps/{reg.app_id}/data").json()["results"]["inbox"]
    assert batch["state"] == "failed" and batch["reason"].startswith("Refused")
    assert composio.fake.calls == [], "the write tool was never called"


def test_execute_read_tool_holds_its_own_allowlist() -> None:
    """Defence in depth below the checks: the executor refuses a slug outside the list it was given."""
    import asyncio

    import httpx

    from app.gateway.composio_client import ComposioClient, ComposioError, execute_read_tool

    calls = []
    client = ComposioClient("k")
    client._transport = httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200, json={"successful": True, "data": {}}))
    with pytest.raises(ComposioError):
        asyncio.run(execute_read_tool(client, slug="GMAIL_DELETE_MESSAGE", connected_account_id="ca", user_id="u", arguments={}, allowed=catalog.READ_ALLOWLIST))
    assert calls == []


def test_upstream_answers_over_the_byte_cap_are_refused() -> None:
    import asyncio

    import httpx

    from app.gateway.composio_client import ComposioClient, ComposioError, execute_read_tool

    client = ComposioClient("k")
    client._transport = httpx.MockTransport(lambda r: httpx.Response(200, content=b'{"data": "' + b"x" * 2048 + b'"}'))
    with pytest.raises(ComposioError, match="larger than"):
        asyncio.run(execute_read_tool(client, slug="GMAIL_FETCH_EMAILS", connected_account_id="ca", user_id="u", arguments={}, allowed=catalog.READ_ALLOWLIST, max_bytes=1024))


@pytest.mark.parametrize("flag", ["after_content", "after_private_read"])
def test_tier_refuses_a_tool_an_exception_can_raise(tmp_path, flag) -> None:
    """A read whose rule an exception lifts out of Tier 1 under some lineage is
    not a read the bridge may run: every lineage is checked, not only the plain one."""
    rules = tmp_path / "rules.yaml"
    rules.write_text(
        RULES_FILE.read_text().replace(
            '    - pattern: "connector-gmail_GMAIL_FETCH_EMAILS"\n      tier: 1\n      reversible: true\n',
            f'    - pattern: "connector-gmail_GMAIL_FETCH_EMAILS"\n      tier: 1\n      reversible: true\n      exceptions:\n        - {flag}: true\n          tier: 2\n',
            1,
        )
    )
    raised = ConfigLoader(path=rules).load()
    assert not raised.unreadable, raised.error
    assert checks.check_tier(GMAIL, GMAIL.arguments({"limit": 25}, NOW), raised) == "GMAIL_FETCH_EMAILS is not Tier 1 in the policy rules"


def test_the_calendar_read_still_counts_as_a_private_read() -> None:
    """Tier 1 lets it run silently; the result is still the owner's private data
    (it arms the outbound tools' after-private-read card like any mail read)."""
    from app.policy.private_reads import reads_private

    assert reads_private("connector-googlecalendar_GOOGLECALENDAR_EVENTS_LIST", SHIPPED) is True
