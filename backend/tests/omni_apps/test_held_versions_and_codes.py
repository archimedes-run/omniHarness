"""Content-led versions wait on the owner's button; refusal codes from the host;
audit tokens; the revoke race (Spec 011 FR-007, FR-008, FR-022)."""

from __future__ import annotations

import pytest
from _apps_helpers import FILES, gmail_answer, manifest

INBOX = {"use": "gmail.unread_subjects", "fields": ["count", "subject", "received_at", "link"]}


@pytest.mark.parametrize("code", ["second_document", "no_hello", "bad_nonce", "second_load", "source_not_approved", "oversized"])
def test_host_refusal_codes_are_accepted(gateway, apps, code) -> None:
    reg = apps.register(manifest(inbox=INBOX))
    assert gateway.client.post(f"/api/apps/{reg.app_id}/refused", json={"reason": code}).status_code == 204
    assert apps.call(apps.repo.audit_entries, owner_id=gateway.user_id, app_id=reg.app_id)[0]["detail"]["reason"] == code


def test_unknown_source_names_are_audited_as_a_fixed_token(gateway, apps) -> None:
    reg = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)
    assert gateway.client.get(f"/api/apps/{reg.app_id}/data/Bad%20Name%3Cx%3E").status_code == 404
    entry = next(e for e in apps.call(apps.repo.audit_entries, owner_id=gateway.user_id, app_id=reg.app_id) if e["event"] == "bridge_refused")
    assert entry["detail"]["source"] == "invalid"


def test_content_led_code_change_waits_on_the_button_and_the_last_version_keeps_serving(gateway, composio, apps) -> None:
    composio.connect("GMAIL")
    composio.fake.answers["GMAIL_FETCH_EMAILS"] = gmail_answer()
    reg = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)

    v2 = apps.register(manifest(inbox=INBOX), files={**FILES, "app.js": b"document.title='from content';"}, app_id=reg.app_id, origin=("content", 'an email "Re: <script>"\n‮ from x'))
    assert v2.version == 2 and v2.needs_approval, "even a code-only change led by content needs the button"
    detail = gateway.client.get(f"/api/apps/{reg.app_id}").json()
    assert detail["current_version"] == 1 and detail["pending_version"] == 2 and detail["status"] == "approved"
    assert detail["html_url"].endswith("/versions/1/app.html")
    assert gateway.client.get(f"/api/apps/{reg.app_id}/data").json()["version"] == 1, "the approved version keeps serving"

    card = detail["approval"]
    assert card["version"] == 2 and card["suggestion"] is True
    assert card["suggestion_source"] == "an email Re: script from x"
    assert card["suggestion_words"] == "Suggested after reading: “an email Re: script from x”"
    apps.approve(reg.app_id)
    after = gateway.client.get(f"/api/apps/{reg.app_id}").json()
    assert after["current_version"] == 2 and after["pending_version"] is None
    assert gateway.client.get(f"/api/apps/{reg.app_id}/data").json()["version"] == 2


def test_owner_led_code_change_is_served_at_once(gateway, apps) -> None:
    reg = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)
    v2 = apps.register(manifest(inbox=INBOX), files={**FILES, "app.js": b"document.title='v2';"}, app_id=reg.app_id)
    assert not v2.needs_approval
    assert gateway.client.get(f"/api/apps/{reg.app_id}").json()["current_version"] == 2


def test_suggestion_source_is_capped_and_cleaned() -> None:
    from app.gateway.apps.service import SUGGESTION_SOURCE_MAX, clean_source

    assert len(clean_source("x" * 1000)) == SUGGESTION_SOURCE_MAX
    assert clean_source("\x00​<>") is None


def test_a_revoke_mid_fetch_neither_refills_nor_recreates_the_cache(gateway, composio, apps) -> None:
    from app.gateway.apps import bridge
    from app.gateway.apps.service import load_app

    composio.connect("GMAIL")
    composio.fake.answers["GMAIL_FETCH_EMAILS"] = gmail_answer()
    reg = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)
    app = load_app(gateway.user_id, reg.app_id)
    key = {"owner_id": gateway.user_id, "app_id": reg.app_id, "source": "inbox", "manifest_hash": app.manifest_hash}
    assert apps.call(apps.repo.claim_upstream, **key, min_interval_s=60)

    # Revoke lands while the fetch is in flight: grants end first, then the rows go.
    apps.call(apps.repo.revoke_all, owner_id=gateway.user_id, app_id=reg.app_id)
    gateway.client.portal.call(bridge.fetch_and_record, gateway.app.state, apps.repo, app, "inbox")
    row = apps.call(apps.repo.cache_row, **key)
    assert row is not None and row["data"] is None and row["answered_at"] is None, "the ended grant blocks the write"

    apps.call(apps.repo.delete_cache, owner_id=gateway.user_id, app_id=reg.app_id)
    assert not apps.call(apps.repo.claim_upstream, **key, min_interval_s=-1)
    assert apps.call(apps.repo.cache_row, **key) is None, "no row is recreated after a revoke"
