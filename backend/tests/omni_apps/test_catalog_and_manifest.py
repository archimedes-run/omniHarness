"""The source catalog and `omni-app.json` validation (Spec 011 FR-001, FR-002, FR-004, FR-011). Pure."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.gateway.apps import catalog
from app.gateway.apps.manifest import ManifestError, manifest_hash, validate_manifest

NOW = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)


def _m(**sources):
    return {"schema": 1, "name": "Today", "description": "d", "sources": sources}


INBOX = {"use": "gmail.unread_subjects", "fields": ["subject", "count"]}


def test_defaults_are_filled_and_fields_follow_catalog_order() -> None:
    m = validate_manifest(_m(inbox=INBOX))
    assert m["sources"]["inbox"] == {"use": "gmail.unread_subjects", "params": {"limit": 25}, "fields": ["count", "subject"], "refresh_s": 300}


@pytest.mark.parametrize(
    "bad,needle",
    [
        ({**_m(inbox=INBOX), "extra": 1}, "unknown key"),
        (_m(inbox={**INBOX, "query": "x"}), "unknown key"),
        (_m(inbox={**INBOX, "params": {"query": "in:anywhere"}}), "unknown key"),
        (_m(inbox={**INBOX, "fields": ["subject", "body"]}), "not allowed"),
        (_m(inbox={**INBOX, "fields": ["snippet"]}), "not allowed"),
        (_m(inbox={**INBOX, "fields": ["sender"]}), "not allowed"),
        (_m(inbox={**INBOX, "params": {"limit": 51}}), "integer from 1 to 50"),
        (_m(inbox={**INBOX, "params": {"limit": True}}), "integer"),
        (_m(inbox={**INBOX, "refresh_s": 59}), "refresh_s"),
        (_m(inbox={**INBOX, "refresh_s": 3601}), "refresh_s"),
        (_m(cal={"use": "googlecalendar.events_today", "params": {"tz": "../../etc/passwd"}, "fields": ["title"]}), "IANA"),
        (_m(gh={"use": "github.pr_search", "fields": ["title"]}), "required"),
        (_m(gh={"use": "github.pr_search", "params": {"preset": "is:pr author:x"}, "fields": ["title"]}), "one of"),
        (_m(x={"use": "gmail.send_email", "fields": ["subject"]}), "catalog entry"),
        (_m(Bad={"use": "gmail.unread_subjects", "fields": ["subject"]}), "source name"),
        ({**_m(inbox=INBOX), "schema": 2}, "schema"),
        (_m(), "1 to 12"),
    ],
)
def test_invalid_manifests_are_refused(bad, needle) -> None:
    with pytest.raises(ManifestError, match=needle):
        validate_manifest(bad)


def test_hash_covers_sources_only() -> None:
    a = validate_manifest(_m(inbox=INBOX))
    renamed = validate_manifest({**_m(inbox=INBOX), "name": "Other", "description": "changed"})
    assert manifest_hash(a) == manifest_hash(renamed)
    reordered = validate_manifest(_m(inbox={**INBOX, "fields": ["count", "subject"]}))
    assert manifest_hash(a) == manifest_hash(reordered), "field order is not a change"
    defaulted = validate_manifest(_m(inbox={**INBOX, "params": {"limit": 25}, "refresh_s": 300}))
    assert manifest_hash(a) == manifest_hash(defaulted), "an explicit default is not a change"
    for changed in ({**INBOX, "fields": ["subject"]}, {**INBOX, "params": {"limit": 10}}, {**INBOX, "refresh_s": 600}):
        assert manifest_hash(validate_manifest(_m(inbox=changed))) != manifest_hash(a)
    assert manifest_hash(validate_manifest(_m(mail=INBOX))) != manifest_hash(a), "a renamed source is a change"


def test_gmail_projection_never_carries_body_snippet_or_sender() -> None:
    message = {"messageId": "abc", "threadId": "18c0000000abcdef", "subject": "Hi", "sender": "a@b.c", "messageText": "BODY", "snippet": "SNIP"}
    message.update(preview={"body": "BODY"}, payload={"parts": ["BODY"]}, messageTimestamp="1731500000000")
    raw = {"messages": [message]}
    projected = catalog.CATALOG["gmail.unread_subjects"].project(raw, {"limit": 25}, NOW)
    text = repr(projected)
    assert "BODY" not in text and "SNIP" not in text and "a@b.c" not in text
    assert projected["items"][0] == {"subject": "Hi", "received_at": "2024-11-13T12:13:20+00:00", "link": "https://mail.google.com/mail/u/0/#inbox/18c0000000abcdef"}


def test_select_keeps_only_declared_fields_and_caps() -> None:
    entry = catalog.CATALOG["gmail.unread_subjects"]
    projected = {"count": 80, "count_capped": True, "items": [{"subject": "x" * 500, "received_at": "t", "link": "l"}] * 80}
    out = catalog.select(projected, entry, ["subject"])
    assert set(out) == {"items"} and len(out["items"]) == catalog.ITEMS_MAX
    assert out["items"][0] == {"subject": "x" * catalog.STRING_MAX}
    with_count = catalog.select(projected, entry, ["count"])
    assert with_count["count"] == 80 and with_count["count_capped"] is True and with_count["items"][0] == {}


def test_payload_is_bounded() -> None:
    entry = catalog.CATALOG["github.pr_search"]
    projected = {"items": [{"repo": "r" * 200, "number": 1, "title": "t" * 200, "updated_at": "u" * 200, "merged_at": "m" * 200, "link": "l" * 200}] * 50}
    out = catalog.select(projected, entry, list(entry.fields))
    import json

    assert len(json.dumps(out, separators=(",", ":")).encode()) <= catalog.PAYLOAD_MAX_BYTES


def test_github_links_are_built_not_taken_from_the_payload() -> None:
    raw = {"items": [{"number": 7, "title": "Fix", "repository_url": "https://api.github.com/repos/o/r", "html_url": "https://evil.example/x", "updated_at": "2026-11-13T10:00:00Z"}]}
    item = catalog.CATALOG["github.pr_search"].project(raw, {"preset": "review_requested", "limit": 20}, NOW)["items"][0]
    assert item["link"] == "https://github.com/o/r/pull/7" and item["repo"] == "o/r"


def test_github_presets_are_fixed_queries() -> None:
    args = catalog.CATALOG["github.pr_search"].arguments
    assert args({"preset": "review_requested", "limit": 20}, NOW)["q"] == "is:pr is:open review-requested:@me"
    assert args({"preset": "failing", "limit": 20}, NOW)["q"] == "is:pr is:open author:@me status:failure"
    assert args({"preset": "merged_7d", "limit": 20}, NOW)["q"] == "is:pr is:merged author:@me merged:>=2026-11-06"


def test_calendar_is_the_owners_day_in_the_zone() -> None:
    entry = catalog.CATALOG["googlecalendar.events_today"]
    args = entry.arguments({"tz": "America/New_York"}, NOW)
    assert args["timeMin"] == "2026-11-13T00:00:00-05:00" and args["timeMax"] == "2026-11-14T00:00:00-05:00" and args["calendarId"] == "primary"
    standup = {"summary": "Standup", "start": {"dateTime": "2026-11-13T09:00:00-05:00"}, "end": {"dateTime": "2026-11-13T09:15:00-05:00"}, "description": "SECRET", "attendees": [{"email": "x@y"}]}
    raw = {"items": [standup, {"summary": "Gone", "status": "cancelled", "start": {"date": "2026-11-13"}}]}
    out = entry.project(raw, {"tz": "America/New_York"}, NOW)
    assert out == {"items": [{"title": "Standup", "start": "2026-11-13T09:00:00-05:00", "end": "2026-11-13T09:15:00-05:00", "all_day": False}]}


def test_words_and_refresh_words() -> None:
    entry = catalog.CATALOG["github.pr_search"]
    assert entry.words({"preset": "failing", "limit": 5}, ["title", "link"]) == "Search GitHub for your open pull requests with failing checks, up to 5: title, link"
    assert catalog.refresh_words(300) == "Refreshes every 5 minutes while you use it"
    assert catalog.refresh_words(3600) == "Refreshes every hour while you use it"
    assert catalog.refresh_words(90) == "Refreshes every 90 seconds while you use it"


def test_every_entry_describes_itself_for_the_kit() -> None:
    for entry in catalog.CATALOG.values():
        described = entry.describe()
        assert described["fields"] and described["id"] == entry.id
        assert (entry.kind == "connector") == (entry.tool is not None)
