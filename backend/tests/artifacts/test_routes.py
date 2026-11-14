"""/api/artifacts through `create_app()` (Spec 012 FR-034 to FR-038). State is
read back from the store after every write."""

from __future__ import annotations

import pytest

from app.gateway.artifacts_store.kinds import canonical, canonical_image
from omniharness.config.paths import get_paths

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4"><rect width="4" height="4"/></svg>'


def make(gw, kind="markdown", content="# hello", owner=None, title="Note", **kw):
    canon = canonical_image(content) if kind == "image" else canonical(kind, content, language=kw.pop("language", None))
    where = {"thread_id": kw.pop("thread_id", "thread-a"), "turn_id": "run-1", "tool_call_id": kw.pop("tool_call_id", "call-1")}
    summary, _ = gw.store.create(owner or gw.user_id, kind=kind, title=title, canon=canon, lineage=kw.pop("lineage", "user"), lineage_source=None, origin="tool", **where)
    return summary["id"]


def test_list_get_versions_and_content(gateway):
    aid = make(gateway)
    c = gateway.client
    listing = c.get("/api/artifacts").json()
    assert [a["id"] for a in listing["artifacts"]] == [aid] and listing["usage"]["used"] == len(b"# hello")
    detail = c.get(f"/api/artifacts/{aid}").json()
    assert detail["kind"] == "markdown" and detail["versions"][0]["n"] == 1 and detail["lineage"] == "user"
    assert c.get(f"/api/artifacts/{aid}/versions/1").json()["content"] == "# hello"
    resp = c.get(f"/api/artifacts/{aid}/versions/1/content")
    assert resp.status_code == 200 and resp.text == "# hello" and resp.headers["content-type"].startswith("text/plain")


def test_svg_and_images_are_served_only_as_inert_images(gateway):
    c = gateway.client
    for aid, media in ((make(gateway, "svg", SVG), "image/svg+xml"), (make(gateway, "image", b"GIF89a" + b"\x00" * 20), "image/gif")):
        resp = c.get(f"/api/artifacts/{aid}/versions/1/content")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == media
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["content-security-policy"] == "default-src 'none'; sandbox"
        assert resp.headers["cross-origin-resource-policy"] == "same-origin"
        assert c.get(f"/api/artifacts/{aid}/versions/1").json()["content"] is None


def test_another_accounts_artifact_is_404_with_no_oracle(gateway):
    theirs = make(gateway, owner="someone-else", content="their secret")
    c = gateway.client
    missing = c.get("/api/artifacts/AAAAAAAAAAAAAAAAAAAAAA")
    for method, path, body in (
        ("get", f"/api/artifacts/{theirs}", None),
        ("get", f"/api/artifacts/{theirs}/versions", None),
        ("get", f"/api/artifacts/{theirs}/versions/1", None),
        ("get", f"/api/artifacts/{theirs}/versions/1/content", None),
        ("patch", f"/api/artifacts/{theirs}", {"title": "mine"}),
        ("post", f"/api/artifacts/{theirs}/archive", None),
        ("post", f"/api/artifacts/{theirs}/versions", {"base_version": 1, "content": "x"}),
        ("post", f"/api/artifacts/{theirs}/restore", {"version": 1, "base_version": 1}),
        ("post", f"/api/artifacts/{theirs}/duplicate", {}),
        ("post", f"/api/artifacts/{theirs}/delete", {"confirm_id": theirs, "version_count": 1}),
    ):
        resp = getattr(c, method)(path, **({"json": body} if body is not None else {}))
        assert resp.status_code == 404, (path, resp.status_code)
        assert resp.json() == missing.json(), "another account's artifact must look exactly like a missing one"
    assert theirs not in str(c.get("/api/artifacts").json())
    after = gateway.store.get("someone-else", theirs)
    assert after["title"] == "Note" and after["latest_version"] == 1 and not after["archived"]
    assert gateway.store.list(gateway.user_id)[1] == 0, "a duplicate of their artifact was made"


@pytest.mark.parametrize("bad", ["..%2F..%2Fetc%2Fpasswd", "....", "%2e%2e", "a" * 23, "short", "AAAAAAAAAAAAAAAAAAAA%00"])
def test_malformed_ids_are_404_and_touch_nothing(gateway, bad):
    resp = gateway.client.get(f"/api/artifacts/{bad}/versions/1/content")
    assert resp.status_code == 404


def test_internal_token_and_no_session_are_refused(gateway):
    from fastapi.testclient import TestClient

    from app.gateway.internal_auth import create_internal_auth_headers

    aid = make(gateway)
    resp = gateway.client.get(f"/api/artifacts/{aid}", headers=create_internal_auth_headers())
    assert resp.status_code == 403 and resp.json()["detail"]["code"] == "owner_session_required"
    anon = TestClient(gateway.app)
    for path in ("/api/artifacts", f"/api/artifacts/{aid}", f"/api/artifacts/{aid}/versions/1/content"):
        assert anon.get(path).status_code == 401


def test_writes_need_csrf(gateway):
    aid = make(gateway)
    token = gateway.client.headers.pop("X-CSRF-Token")
    try:
        for method, path, body in (("patch", f"/api/artifacts/{aid}", {"title": "x"}), ("post", f"/api/artifacts/{aid}/archive", None), ("post", f"/api/artifacts/{aid}/versions", {"base_version": 1, "content": "y"})):
            resp = getattr(gateway.client, method)(path, **({"json": body} if body is not None else {}))
            assert resp.status_code == 403, path
    finally:
        gateway.client.headers["X-CSRF-Token"] = token
    after = gateway.store.get(gateway.user_id, aid)
    assert after["title"] == "Note" and not after["archived"] and after["latest_version"] == 1


def test_rename_pin_archive_unarchive(gateway):
    aid = make(gateway)
    c = gateway.client
    assert c.patch(f"/api/artifacts/{aid}", json={"title": "Renamed‮", "pinned": True}).status_code == 200
    s = gateway.store.get(gateway.user_id, aid)
    assert s["title"] == "Renamed" and s["pinned"] and s["latest_version"] == 1
    assert c.post(f"/api/artifacts/{aid}/archive").status_code == 200
    s = gateway.store.get(gateway.user_id, aid)
    assert s["archived"] and not s["pinned"]
    assert c.patch(f"/api/artifacts/{aid}", json={"pinned": True}).json()["detail"]["code"] == "artifact_archived"
    assert aid not in str(c.get("/api/artifacts").json()) and aid in str(c.get("/api/artifacts?archived=true").json())
    c.post(f"/api/artifacts/{aid}/unarchive")
    assert not gateway.store.get(gateway.user_id, aid)["archived"]


def test_owner_edit_restore_and_stale_base(gateway):
    aid = make(gateway, lineage="content")
    c = gateway.client
    resp = c.post(f"/api/artifacts/{aid}/versions", json={"base_version": 1, "content": "# edited"})
    assert resp.status_code == 201
    v2 = gateway.store.versions(gateway.user_id, aid)[0]
    assert v2["n"] == 2 and v2["origin"] == "owner_edit" and v2["lineage"] == "user" and v2["base_version"] == 1
    stale = c.post(f"/api/artifacts/{aid}/versions", json={"base_version": 1, "content": "# lost"})
    assert stale.status_code == 409 and stale.json()["detail"] == {"code": "stale_base_version", "message": stale.json()["detail"]["message"], "current_version": 2}
    assert c.post(f"/api/artifacts/{aid}/restore", json={"version": 1, "base_version": 2}).status_code == 201
    versions = gateway.store.versions(gateway.user_id, aid)
    assert [v["n"] for v in versions] == [3, 2, 1] and versions[0]["content_hash"] == versions[2]["content_hash"] and versions[0]["origin"] == "restore"


def test_owner_edit_refuses_kinds_without_an_editor(gateway):
    aid = make(gateway, "svg", SVG)
    resp = gateway.client.post(f"/api/artifacts/{aid}/versions", json={"base_version": 1, "content": SVG})
    assert resp.status_code == 422 and resp.json()["detail"]["code"] == "not_editable"
    assert gateway.store.get(gateway.user_id, aid)["latest_version"] == 1


def test_owner_edit_validates_content(gateway):
    aid = make(gateway, "mermaid", "graph TD; A-->B")
    resp = gateway.client.post(f"/api/artifacts/{aid}/versions", json={"base_version": 1, "content": '%%{init: {"securityLevel":"loose"}}%%\ngraph TD; A-->B'})
    assert resp.status_code == 422 and resp.json()["detail"]["code"] == "invalid_content"
    assert gateway.store.get(gateway.user_id, aid)["latest_version"] == 1


def test_duplicate_makes_a_new_artifact(gateway):
    aid = make(gateway)
    resp = gateway.client.post(f"/api/artifacts/{aid}/duplicate", json={})
    assert resp.status_code == 201
    copy = gateway.store.get(gateway.user_id, resp.json()["id"])
    assert copy["id"] != aid and copy["title"] == "Note (copy)" and gateway.store.versions(gateway.user_id, copy["id"])[0]["origin"] == "duplicate"
    assert gateway.store.get(gateway.user_id, aid)["latest_version"] == 1


def test_delete_needs_archive_and_the_typed_id(gateway):
    aid = make(gateway)
    c = gateway.client
    assert c.post(f"/api/artifacts/{aid}/delete", json={"confirm_id": aid, "version_count": 1}).json()["detail"]["code"] == "not_archived"
    c.post(f"/api/artifacts/{aid}/archive")
    wrong = c.post(f"/api/artifacts/{aid}/delete", json={"confirm_id": "nope", "version_count": 1})
    assert wrong.status_code == 400 and wrong.json()["detail"]["code"] == "confirmation_mismatch"
    assert c.post(f"/api/artifacts/{aid}/delete", json={"confirm_id": aid, "version_count": 5}).status_code == 400
    assert gateway.store.get(gateway.user_id, aid)["version_count"] == 1
    assert c.post(f"/api/artifacts/{aid}/delete", json={"confirm_id": aid, "version_count": 1}).json() == {"deleted": aid}
    assert c.get(f"/api/artifacts/{aid}").status_code == 404


def test_search_and_filters(gateway):
    a = make(gateway, content="the quarterly roadmap", title="Plan")
    b = make(gateway, "chart", {"type": "pie", "title": "Mix", "x": {"field": "k", "type": "category"}, "series": [{"field": "v", "label": "V"}], "data": [{"k": "a", "v": 1}]}, title="Mix")
    c = gateway.client
    assert [x["id"] for x in c.get("/api/artifacts?q=roadmap").json()["artifacts"]] == [a]
    assert [x["id"] for x in c.get("/api/artifacts?kind=chart").json()["artifacts"]] == [b]
    assert c.get("/api/artifacts?q=100%25").json()["total"] == 0
    assert c.get("/api/artifacts?kind=html").status_code == 422


def test_thread_endpoint_lists_bindings(gateway):
    aid = make(gateway, thread_id="thread-z", tool_call_id="call-77")
    out = gateway.client.get("/api/artifacts/threads/thread-z").json()["artifacts"]
    assert out[0]["id"] == aid and out[0]["versions_in_thread"][0]["tool_call_id"] == "call-77"
    assert gateway.client.get("/api/artifacts/threads/other").json() == {"artifacts": []}


def _outputs(gw, thread_id):
    out = get_paths().sandbox_outputs_dir(thread_id, user_id=gw.user_id)
    out.mkdir(parents=True, exist_ok=True)
    return out


def test_importer_indexes_chat_outputs_once(gateway, monkeypatch):
    from app.gateway.artifacts_store import caps

    monkeypatch.setattr(caps, "BINARY_VERSION_BYTES", 1000)
    out = _outputs(gateway, "thread-old")
    (out / "brief.md").write_text("# old brief")
    (out / "copy.md").write_text("# old brief")
    (out / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)
    (out / "big.bin").write_bytes(b"\x01" * 2000)
    (out / "bad.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>1</script></svg>')
    (out / "sub").mkdir()
    (out / "sub" / "main.py").write_text("print(1)")
    (out / "link.md").symlink_to(gateway.tmp / "config.yaml")
    c = gateway.client
    c.get("/api/artifacts")  # schedules the importer; TestClient runs it before returning
    rows = {a["title"]: a for a in c.get("/api/artifacts").json()["artifacts"]}
    assert set(rows) == {"brief.md", "copy.md", "pic.png", "big.bin", "bad.svg", "main.py"}, "a symlink was followed or a file was missed"
    assert rows["brief.md"]["kind"] == "markdown" and rows["pic.png"]["kind"] == "image" and rows["main.py"]["language"] == "python"
    assert rows["bad.svg"]["kind"] == "file", "an SVG failing the allowlist is kept as a download-only file"
    assert rows["brief.md"]["imported_from"] == "thread-old:/mnt/user-data/outputs/brief.md" and rows["brief.md"]["lineage"] == "content"
    big = gateway.store.versions(gateway.user_id, rows["big.bin"]["id"])[0]
    assert big["stored"] == "chat"
    lives = c.get(f"/api/artifacts/{rows['big.bin']['id']}/versions/1/content")
    assert lives.status_code == 409 and lives.json()["detail"]["path"] == "/mnt/user-data/outputs/big.bin"
    brief_v = gateway.store.versions(gateway.user_id, rows["brief.md"]["id"])[0]
    copy_v = gateway.store.versions(gateway.user_id, rows["copy.md"]["id"])[0]
    assert brief_v["content_hash"] == copy_v["content_hash"], "same bytes, one blob"
    assert len(list(get_paths().user_dir(gateway.user_id).joinpath("artifacts").rglob(brief_v["content_hash"]))) == 1
    assert gateway.store.usage(gateway.user_id) < 1000, "the file over the cap was copied"
    # Idempotent: a second pass (throttle reset) makes nothing new.
    import app.gateway.artifacts_store.service as service

    assert service.run_import(gateway.store, gateway.user_id, thread_id="thread-old") == 0
    # A changed file becomes a new version of its artifact.
    (out / "brief.md").write_text("# new brief")
    assert service.run_import(gateway.store, gateway.user_id, thread_id="thread-old") == 1
    assert gateway.store.get(gateway.user_id, rows["brief.md"]["id"])["latest_version"] == 2
    # A deleted import is not made again.
    aid = rows["copy.md"]["id"]
    gateway.store.set_archived(gateway.user_id, aid, True)
    gateway.store.delete(gateway.user_id, aid, confirm_id=aid, version_count=1)
    monkeypatch.setattr(service, "_LAST_FULL_IMPORT", {})
    service.run_import(gateway.store, gateway.user_id)
    (out / "copy.md").write_text("# changed after the owner deleted it")
    monkeypatch.setattr(service, "_LAST_FULL_IMPORT", {})
    service.run_import(gateway.store, gateway.user_id)
    assert "copy.md" not in {a["title"] for a in c.get("/api/artifacts").json()["artifacts"]}
