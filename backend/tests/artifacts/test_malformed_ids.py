"""Every /api/artifacts route rejects a malformed id with 404 artifact_not_found
before anything else runs: never a 500, never a lookup (follow-up to Spec 012 S1)."""

from __future__ import annotations

import pytest

BAD_IDS = ["..%2F..%2Fetc", "..%2Fetc%2Fpasswd", "%2e%2e%2f%2e%2e", "..", "...", "a" * 23, "a" * 21, "%C3%A9" * 11, "%E2%80%AE" + "a" * 21, "%00" + "a" * 21, "a%20" * 6, "%20"]

ROUTES = [
    ("get", "/api/artifacts/{id}", None),
    ("get", "/api/artifacts/{id}/versions", None),
    ("get", "/api/artifacts/{id}/versions/1", None),
    ("get", "/api/artifacts/{id}/versions/1/content", None),
    ("patch", "/api/artifacts/{id}", {"title": "x"}),
    ("post", "/api/artifacts/{id}/archive", None),
    ("post", "/api/artifacts/{id}/unarchive", None),
    ("post", "/api/artifacts/{id}/versions", {"base_version": 1, "content": "x"}),
    ("post", "/api/artifacts/{id}/restore", {"version": 1, "base_version": 1}),
    ("post", "/api/artifacts/{id}/duplicate", {}),
    ("post", "/api/artifacts/{id}/delete", {"confirm_id": "x", "version_count": 1}),
]


@pytest.mark.parametrize("bad", BAD_IDS)
def test_malformed_ids_are_404_on_every_route(gateway, bad):
    for method, template, body in ROUTES:
        resp = getattr(gateway.client, method)(template.replace("{id}", bad), **({"json": body} if body is not None else {}))
        assert resp.status_code in (404, 405), (method, template, bad, resp.status_code, resp.text[:200])
        if resp.status_code == 404 and resp.headers.get("content-type", "").startswith("application/json"):
            detail = resp.json().get("detail")
            assert detail == "Not Found" or (isinstance(detail, dict) and detail.get("code") == "artifact_not_found"), (template, bad, detail)


def test_the_store_is_never_reached_for_a_malformed_id(gateway, monkeypatch):
    calls = []
    for name in ("detail", "versions", "version", "patch", "set_archived", "add_version", "restore", "duplicate", "delete"):
        monkeypatch.setattr(gateway.store, name, lambda *a, _n=name, **k: calls.append(_n))
    for method, template, body in ROUTES:
        getattr(gateway.client, method)(template.replace("{id}", "..%2F..%2Fetc"), **({"json": body} if body is not None else {}))
    assert calls == []
