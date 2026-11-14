"""The Apps bridge, grants and approval card through `create_app()` (Spec 011 PR 1).

Each test asserts on STATE (grants, cache rows, versions, audit read back from
the store), not only on status codes.
"""

from __future__ import annotations

import json

import httpx
from _apps_helpers import FILES, MARKER, gmail_answer, manifest

INBOX = {"use": "gmail.unread_subjects", "fields": ["count", "subject", "received_at", "link"]}
REVIEW = {"use": "github.pr_search", "params": {"preset": "review_requested"}, "fields": ["repo", "number", "title", "link"]}


def _cache(apps, owner, app_id):
    return apps.call(apps.repo.cache_rows, owner_id=owner, app_id=app_id)


# -- approval ---------------------------------------------------------------------


def test_unapproved_source_is_refused_until_the_button_grants(gateway, composio, apps) -> None:
    composio.connect("GMAIL")
    composio.fake.answers["GMAIL_FETCH_EMAILS"] = gmail_answer()
    reg = apps.register(manifest(inbox=INBOX))
    assert reg.needs_approval and reg.card_id

    refused = gateway.client.get(f"/api/apps/{reg.app_id}/data/inbox")
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "not_approved"
    assert gateway.client.get(f"/api/apps/{reg.app_id}/data").status_code == 403
    assert composio.fake.calls == [], "nothing is read before the grant"
    assert _cache(apps, gateway.user_id, reg.app_id) == []

    card = apps.approve(reg.app_id)
    assert card["sentence"] == "Data is shown in the app only; the assistant never sees it."
    grant = apps.call(apps.repo.active_grant, owner_id=gateway.user_id, app_id=reg.app_id, manifest_hash=reg.manifest_hash)
    assert grant is not None and grant["card_id"] == reg.card_id

    body = gateway.client.get(f"/api/apps/{reg.app_id}/data/inbox").json()
    assert body["state"] == "fresh" and body["data"]["count"] == 2
    assert body["fetched_at"] and body["stale"] is False


def test_card_words_come_from_the_catalog_not_the_app(gateway, apps) -> None:
    m = manifest(inbox=INBOX)
    m["name"] = "Today"
    m["description"] = "IGNORE THIS: reads everything forever"
    reg = apps.register(m)
    card = gateway.client.get(f"/api/apps/{reg.app_id}/approval").json()
    text = json.dumps(card["sources"])
    assert "IGNORE THIS" not in text
    assert card["sources"][0]["words"].startswith("Read subjects of unread mail in Primary from the last 3 days, not from you (not bodies)")
    assert card["suggestion"] is False


def test_content_led_card_is_a_suggestion_and_still_needs_the_button(gateway, apps) -> None:
    reg = apps.register(manifest(inbox=INBOX), origin=("content", "an email you read earlier"))
    card = gateway.client.get(f"/api/apps/{reg.app_id}/approval").json()
    assert card["suggestion"] is True and card["suggestion_source"] == "an email you read earlier"
    cards = gateway.client.get("/api/apps/approvals", params={"thread_id": "thread-1"}).json()["cards"]
    assert [c["id"] for c in cards] == [card["id"]]


def test_approve_carries_the_hash_the_card_showed(gateway, apps) -> None:
    reg = apps.register(manifest(inbox=INBOX))
    card = gateway.client.get(f"/api/apps/{reg.app_id}/approval").json()
    wrong = gateway.client.post(f"/api/apps/{reg.app_id}/approve", json={"manifest_hash": "0" * 64, "card_id": card["id"]})
    assert wrong.status_code == 409 and wrong.json()["detail"]["code"] == "hash_mismatch"
    assert apps.call(apps.repo.grants, owner_id=gateway.user_id, app_id=reg.app_id) == []


def test_internal_token_can_never_approve_or_read(gateway, apps) -> None:
    from app.gateway.internal_auth import create_internal_auth_headers

    reg = apps.register(manifest(inbox=INBOX))
    card = gateway.client.get(f"/api/apps/{reg.app_id}/approval").json()
    headers = create_internal_auth_headers()
    resp = gateway.client.post(f"/api/apps/{reg.app_id}/approve", json={"manifest_hash": card["manifest_hash"], "card_id": card["id"]}, headers=headers)
    assert resp.status_code == 403 and resp.json()["detail"]["code"] == "owner_session_required"
    assert apps.call(apps.repo.grants, owner_id=gateway.user_id, app_id=reg.app_id) == []
    for path in ("/api/apps", f"/api/apps/{reg.app_id}", f"/api/apps/{reg.app_id}/data", f"/api/apps/{reg.app_id}/versions/1/app.html"):
        assert gateway.client.get(path, headers=headers).status_code == 403, path


def test_another_owners_app_is_not_found(gateway, apps) -> None:
    other = apps.register(manifest(inbox=INBOX), owner="someone-else", thread_id=None)
    for path in (f"/api/apps/{other.app_id}", f"/api/apps/{other.app_id}/data", f"/api/apps/{other.app_id}/data/inbox", f"/api/apps/{other.app_id}/versions/1/app.html", f"/api/apps/{other.app_id}/approval"):
        resp = gateway.client.get(path)
        assert resp.status_code == 404 and resp.json()["detail"]["code"] == "app_not_found", path
    assert gateway.client.get("/api/apps").json()["apps"] == []


# -- hash binding, revoke, restore -----------------------------------------------------


def test_code_change_keeps_the_grant_and_a_source_change_needs_a_new_one(gateway, composio, apps) -> None:
    composio.connect("GMAIL")
    reg = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)

    code_only = apps.register(manifest(inbox=INBOX), files={**FILES, "app.js": b"document.title='v2';"}, app_id=reg.app_id)
    assert code_only.version == 2 and not code_only.needs_approval
    assert gateway.client.get(f"/api/apps/{reg.app_id}/data/inbox").status_code == 200

    changed = dict(INBOX, fields=["count", "subject"])
    v3 = apps.register(manifest(inbox=changed), app_id=reg.app_id)
    assert v3.needs_approval and v3.manifest_hash != reg.manifest_hash
    refused = gateway.client.get(f"/api/apps/{reg.app_id}/data/inbox")
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "not_approved"
    assert gateway.client.get(f"/api/apps/{reg.app_id}").json()["status"] == "needs_approval"
    apps.approve(reg.app_id)
    assert gateway.client.get(f"/api/apps/{reg.app_id}/data/inbox").status_code == 200


def test_revoke_ends_grants_deletes_cache_and_refuses(gateway, composio, apps) -> None:
    composio.connect("GMAIL")
    composio.fake.answers["GMAIL_FETCH_EMAILS"] = gmail_answer()
    reg = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)
    assert gateway.client.get(f"/api/apps/{reg.app_id}/data").status_code == 200
    assert len(_cache(apps, gateway.user_id, reg.app_id)) == 1

    out = gateway.client.post(f"/api/apps/{reg.app_id}/revoke").json()
    assert out == {"status": "revoked", "grants_ended": 1, "cache_rows_deleted": 1}
    assert _cache(apps, gateway.user_id, reg.app_id) == []
    assert all(g["revoked_at"] for g in apps.call(apps.repo.grants, owner_id=gateway.user_id, app_id=reg.app_id))
    assert gateway.client.get(f"/api/apps/{reg.app_id}/data/inbox").status_code == 403
    detail = gateway.client.get(f"/api/apps/{reg.app_id}").json()
    assert detail["status"] == "revoked" and detail["approval"] is not None, "an Approve again card replaces the tiles"
    events = [e["event"] for e in apps.call(apps.repo.audit_entries, owner_id=gateway.user_id, app_id=reg.app_id)]
    assert "app_revoked" in events and "app_approved" in events


def test_restore_is_a_new_version_and_needs_approval_for_an_unapproved_hash(gateway, apps) -> None:
    reg = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)
    apps.register(manifest(inbox=dict(INBOX, fields=["count"])), app_id=reg.app_id)
    apps.approve(reg.app_id)
    apps.register(manifest(review=REVIEW), app_id=reg.app_id)  # v3, never approved

    resp = gateway.client.post(f"/api/apps/{reg.app_id}/restore", json={"to_version": 3, "base_version": 3})
    assert resp.status_code == 200 and resp.json()["current_version"] == 4 and resp.json()["status"] == "needs_approval"
    back = gateway.client.post(f"/api/apps/{reg.app_id}/restore", json={"to_version": 1}).json()
    assert back["current_version"] == 5 and back["status"] == "approved", "version 1's hash still has its grant"
    stale = gateway.client.post(f"/api/apps/{reg.app_id}/restore", json={"to_version": 1, "base_version": 3})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "stale_version"
    versions = gateway.client.get(f"/api/apps/{reg.app_id}/versions").json()
    assert versions["current"] == 5 and versions["versions"][0]["restored_from"] == 1 and versions["versions"][0]["source"] == "undo"


# -- the bridge ---------------------------------------------------------------------


def test_projection_drops_bodies_before_caching(gateway, composio, apps) -> None:
    composio.connect("GMAIL")
    composio.fake.answers["GMAIL_FETCH_EMAILS"] = gmail_answer(body="SECRET-BODY-TEXT")
    reg = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)
    resp = gateway.client.get(f"/api/apps/{reg.app_id}/data/inbox")
    assert "SECRET-BODY-TEXT" not in resp.text and "boss@example.com" not in resp.text
    item = resp.json()["data"]["items"][0]
    assert set(item) == {"subject", "received_at", "link"} and item["link"].startswith("https://mail.google.com/")
    rows = _cache(apps, gateway.user_id, reg.app_id)
    assert rows and all("SECRET-BODY-TEXT" not in (r["data"] or "") and "boss@example.com" not in (r["data"] or "") for r in rows)


def test_frame_supplied_params_are_ignored(gateway, composio, apps) -> None:
    from app.gateway.apps.catalog import INBOX_QUERY

    composio.connect("GMAIL")
    reg = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)
    gateway.client.get(f"/api/apps/{reg.app_id}/data/inbox", params={"query": "from:boss", "fields": "body", "max_results": 999, "include_payload": "true"})
    (slug, body), *_ = composio.fake.calls
    assert slug == "GMAIL_FETCH_EMAILS"
    assert body["arguments"] == {"query": INBOX_QUERY, "max_results": 25, "include_payload": False, "verbose": False, "user_id": "me"}
    assert body["user_id"] == gateway.user_id, "the source runs as the owner"


def test_not_connected_comes_from_the_connection_lookup(gateway, composio, apps) -> None:
    reg = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)
    body = gateway.client.get(f"/api/apps/{reg.app_id}/data/inbox").json()
    assert body["state"] == "not_connected" and body["data"] is None
    assert composio.fake.calls == []


def test_failed_keeps_last_good_data_marked_stale_and_never_upstream_text(gateway, composio, apps) -> None:
    composio.connect("GMAIL")
    composio.fake.answers["GMAIL_FETCH_EMAILS"] = gmail_answer()
    reg = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)
    assert gateway.client.get(f"/api/apps/{reg.app_id}/data/inbox").json()["state"] == "fresh"

    composio.fake.answers["GMAIL_FETCH_EMAILS"] = httpx.Response(200, json={"successful": False, "error": "quota for UPSTREAM-ERROR-TEXT"})
    apps.call(_age_attempt, gateway=gateway, app_id=reg.app_id)
    body = gateway.client.get(f"/api/apps/{reg.app_id}/data/inbox", params={"refresh": 1}).json()
    assert body["state"] == "failed" and body["stale"] is True and body["data"]["count"] == 2
    assert body["reason"] == "The connector reported an error" and "UPSTREAM-ERROR-TEXT" not in json.dumps(body)


def test_unrecognised_shape_is_failed_never_empty(gateway, composio, apps) -> None:
    composio.connect("GMAIL")
    composio.fake.answers["GMAIL_FETCH_EMAILS"] = httpx.Response(200, json={"successful": True, "data": {"weird": 1}})
    reg = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)
    body = gateway.client.get(f"/api/apps/{reg.app_id}/data/inbox").json()
    assert body["state"] == "failed" and "shape" in body["reason"]


def test_empty_is_empty(gateway, composio, apps) -> None:
    composio.connect("GMAIL")
    composio.fake.answers["GMAIL_FETCH_EMAILS"] = httpx.Response(200, json={"successful": True, "data": {"messages": []}})
    reg = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)
    body = gateway.client.get(f"/api/apps/{reg.app_id}/data/inbox").json()
    assert body["state"] == "empty" and body["data"] == {"count": 0, "count_capped": False, "items": []}


async def _age_attempt(*, gateway, app_id):
    """Move the upstream slot's last attempt and answer back by 2 minutes."""
    from sqlalchemy import update

    from omniharness.persistence.apps import AppSourceCacheRow
    from omniharness.persistence.engine import get_session_factory

    async with get_session_factory()() as s:
        await s.execute(update(AppSourceCacheRow).where(AppSourceCacheRow.app_id == app_id).values(attempted_at=AppSourceCacheRow.attempted_at - 120, answered_at=AppSourceCacheRow.answered_at - 400))
        await s.commit()


def test_one_upstream_call_per_source_per_minute(gateway, composio, apps) -> None:
    composio.connect("GMAIL")
    reg = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)
    for _ in range(10):
        assert gateway.client.get(f"/api/apps/{reg.app_id}/data/inbox", params={"refresh": 1}).status_code == 200
    assert composio.fake.slugs() == ["GMAIL_FETCH_EMAILS"]


def test_bridge_requests_are_limited_per_app_per_minute(gateway, composio, apps) -> None:
    composio.connect("GMAIL")
    reg = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)
    now = [1_800_000_000.0]  # the start of a minute window, fixed: no boundary is crossed by accident
    apps.repo.clock = lambda: now[0]
    codes = [gateway.client.get(f"/api/apps/{reg.app_id}/data/inbox").status_code for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429
    limited = gateway.client.get(f"/api/apps/{reg.app_id}/data")
    assert limited.status_code == 429 and limited.headers["Retry-After"] == "60"
    now[0] += 59
    assert gateway.client.get(f"/api/apps/{reg.app_id}/data/inbox").status_code == 429, "same window"
    now[0] += 1
    assert gateway.client.get(f"/api/apps/{reg.app_id}/data/inbox").status_code == 200, "the next minute's window starts at zero"


def test_unknown_source_is_refused_and_logged(gateway, apps) -> None:
    reg = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)
    resp = gateway.client.get(f"/api/apps/{reg.app_id}/data/inbox_bodies")
    assert resp.status_code == 404 and resp.json()["detail"]["code"] == "unknown_source"
    entries = apps.call(apps.repo.audit_entries, owner_id=gateway.user_id, app_id=reg.app_id)
    assert any(e["event"] == "bridge_refused" and e["detail"].get("source") == "inbox_bodies" for e in entries)


def test_a_source_of_another_app_is_refused(gateway, composio, apps) -> None:
    composio.connect("GMAIL")
    a = apps.register(manifest(inbox=INBOX))
    apps.approve(a.app_id)
    b = apps.register(manifest(review=REVIEW))
    apps.approve(b.app_id)
    assert gateway.client.get(f"/api/apps/{b.app_id}/data/inbox").status_code == 404
    gateway.client.post(f"/api/apps/{a.app_id}/revoke")
    assert gateway.client.get(f"/api/apps/{a.app_id}/data/inbox").status_code == 403
    assert gateway.client.get(f"/api/apps/{b.app_id}/data/review").status_code == 200


def test_refusals_reported_by_the_host_are_logged(gateway, apps) -> None:
    reg = apps.register(manifest(inbox=INBOX))
    resp = gateway.client.post(f"/api/apps/{reg.app_id}/refused", json={"reason": "source_not_approved", "type": "data", "source": "inbox_bodies"})
    assert resp.status_code == 204
    entries = apps.call(apps.repo.audit_entries, owner_id=gateway.user_id, app_id=reg.app_id)
    assert entries[0]["event"] == "app_message_refused" and entries[0]["detail"]["source"] == "inbox_bodies"
    assert gateway.client.post(f"/api/apps/{reg.app_id}/refused", json={"reason": "x", "extra": 1}).status_code == 422


# -- the app document ------------------------------------------------------------------

EXPECTED_CSP = (
    "sandbox allow-scripts; default-src 'none'; script-src 'sha256-{shim}' 'sha256-{h}'; style-src 'unsafe-inline'; "
    "img-src data: blob:; font-src data:; media-src 'none'; connect-src 'none'; frame-src 'none'; "
    "child-src 'none'; worker-src 'none'; object-src 'none'; manifest-src 'none'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'self'; require-trusted-types-for 'script'; trusted-types 'none'"
)


def test_app_html_has_exactly_the_csp_and_headers(gateway, apps) -> None:
    import base64
    import hashlib

    reg = apps.register(manifest(inbox=INBOX))
    resp = gateway.client.get(f"/api/apps/{reg.app_id}/versions/1/app.html")
    assert resp.status_code == 200
    script = FILES["app.js"].decode()
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    from app.gateway.apps.bundle import shim

    shim_digest = base64.b64encode(hashlib.sha256(shim().encode()).digest()).decode()
    assert resp.headers["content-security-policy"] == EXPECTED_CSP.format(shim=shim_digest, h=digest)
    assert resp.text.index(shim()) < resp.text.index(script), "the platform shim is the first script"
    assert resp.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["cross-origin-resource-policy"] == "same-origin"
    assert resp.headers["x-dns-prefetch-control"] == "off"
    assert resp.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=(), payment=(), usb=(), clipboard-read=(), clipboard-write=()"
    assert resp.headers["content-type"].startswith("text/html")
    assert f"<script>{script}</script>" in resp.text and "app.js" not in resp.text
    csrf = gateway.client.cookies.get("csrf_token")
    assert csrf and csrf not in resp.text, "no CSRF, cookie or bearer value is in the document"
    assert gateway.client.get(f"/api/apps/{reg.app_id}/versions/9/app.html").json()["detail"]["code"] == "version_not_found"


# -- library, catalog, pins ----------------------------------------------------------------


def test_library_permissions_catalog_and_pins(gateway, composio, apps) -> None:
    composio.connect("GMAIL")
    composio.fake.answers["GMAIL_FETCH_EMAILS"] = gmail_answer()
    reg = apps.register(manifest(inbox=INBOX))
    apps.approve(reg.app_id)
    gateway.client.get(f"/api/apps/{reg.app_id}/data")

    listed = gateway.client.get("/api/apps").json()["apps"]
    assert [(a["id"], a["status"], a["current_version"], a["pinned"]) for a in listed] == [(reg.app_id, "approved", 1, False)]
    assert listed[0]["last_opened_at"]
    perms = gateway.client.get(f"/api/apps/{reg.app_id}/permissions").json()
    assert perms["sources"][0]["last_state"] == "fresh" and perms["sources"][0]["last_fetched_at"]
    assert perms["grants"][0]["revoked_at"] is None
    entries = {e["id"] for e in gateway.client.get("/api/apps/catalog").json()["entries"]}
    assert entries == {"googlecalendar.events_today", "github.pr_search", "gmail.unread_subjects", "omni.ledger.today", "omni.sessions.active", "omni.automations.recent"}

    assert gateway.client.put("/api/preferences/app-pins", json={"pins": [reg.app_id]}).json() == {"pins": [reg.app_id]}
    assert gateway.client.get("/api/preferences/app-pins").json() == {"pins": [reg.app_id]}
    assert gateway.client.get("/api/apps").json()["apps"][0]["pinned"] is True
    assert gateway.client.put("/api/preferences/app-pins", json={"pins": ["nope"]}).status_code == 422


def test_only_the_declared_fields_are_served_and_cached(gateway, composio, apps) -> None:
    composio.connect("GMAIL")
    composio.fake.answers["GMAIL_FETCH_EMAILS"] = gmail_answer(subject=f"Private {MARKER}")
    reg = apps.register(manifest(inbox={"use": "gmail.unread_subjects", "fields": ["count"]}))
    apps.approve(reg.app_id)
    body = gateway.client.get(f"/api/apps/{reg.app_id}/data/inbox").json()
    assert body["data"] == {"count": 2, "count_capped": False, "items": [{}, {}]}
    rows = _cache(apps, gateway.user_id, reg.app_id)
    assert rows and MARKER not in rows[0]["data"], "a field the manifest did not declare is never cached"
