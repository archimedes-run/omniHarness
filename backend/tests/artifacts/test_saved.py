"""The save model (owner decision 2026-11-14): artifacts the assistant makes are
unsaved and live with their chat; the owner's Save puts one in the store;
Download gives a file; "Save to artifacts" saves a chat's output. State is
read back from the store after every call."""

from __future__ import annotations

import io
import os
import zipfile
from urllib.parse import unquote

import pytest

from app.gateway.artifacts_store import caps
from app.gateway.artifacts_store.kinds import canonical, canonical_image
from omniharness.config.paths import get_paths

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def make(gw, kind="markdown", content="# hello", title="Note", owner=None, thread="thread-a", **kw):
    language = kw.pop("language", None)
    canon = canonical_image(content) if kind == "image" else canonical(kind, content, language=language)
    summary, _ = gw.store.create(owner or gw.user_id, kind=kind, title=title, canon=canon, lineage="user", lineage_source=None, origin="tool", thread_id=thread, **kw)
    return summary["id"]


def ids(resp) -> list[str]:
    return [a["id"] for a in resp.json()["artifacts"]]


# -- saved / unsaved -----------------------------------------------------------------


def test_made_artifacts_are_unsaved_and_out_of_the_default_listing(gateway):
    aid = make(gateway)
    c = gateway.client
    assert gateway.store.get(gateway.user_id, aid)["saved"] is False
    assert ids(c.get("/api/artifacts")) == [], "the store's default view lists saved artifacts only"
    assert ids(c.get("/api/artifacts?saved=false")) == [aid]
    assert ids(c.get("/api/artifacts?saved=all")) == [aid]
    assert [a["id"] for a in c.get("/api/artifacts/threads/thread-a").json()["artifacts"]] == [aid], "the chat still has it"


def test_save_and_unsave(gateway):
    aid = make(gateway)
    c = gateway.client
    resp = c.post(f"/api/artifacts/{aid}/save")
    assert resp.status_code == 200
    state = gateway.store.get(gateway.user_id, aid)
    assert state["saved"] is True and state["saved_at"]
    assert ids(c.get("/api/artifacts")) == [aid]
    c.patch(f"/api/artifacts/{aid}", json={"pinned": True})
    c.post(f"/api/artifacts/{aid}/unsave")
    state = gateway.store.get(gateway.user_id, aid)
    assert state["saved"] is False and state["saved_at"] is None and state["pinned"] is False, "unsave also unpins"
    assert ids(c.get("/api/artifacts")) == []


def test_pinning_saves(gateway):
    aid = make(gateway)
    gateway.client.patch(f"/api/artifacts/{aid}", json={"pinned": True})
    assert gateway.store.get(gateway.user_id, aid)["saved"] is True


def test_an_archived_artifact_is_not_saved(gateway):
    aid = make(gateway)
    gateway.client.post(f"/api/artifacts/{aid}/archive")
    resp = gateway.client.post(f"/api/artifacts/{aid}/save")
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "artifact_archived"
    assert gateway.store.get(gateway.user_id, aid)["saved"] is False


def test_save_needs_the_owners_session_and_csrf(gateway):
    from app.gateway.internal_auth import create_internal_auth_headers

    aid = make(gateway)
    theirs = make(gateway, owner="someone-else")
    c = gateway.client
    assert c.post(f"/api/artifacts/{aid}/save", headers=create_internal_auth_headers()).status_code == 403
    assert c.post(f"/api/artifacts/{theirs}/save").json() == c.post("/api/artifacts/AAAAAAAAAAAAAAAAAAAAAA/save").json()
    token = c.headers.pop("X-CSRF-Token")
    try:
        assert c.post(f"/api/artifacts/{aid}/save").status_code == 403
    finally:
        c.headers["X-CSRF-Token"] = token
    assert gateway.store.get(gateway.user_id, aid)["saved"] is False
    assert gateway.store.get("someone-else", theirs)["saved"] is False


def test_deleting_a_chat_removes_its_unsaved_artifacts_only(gateway):
    c = gateway.client
    thread_id = c.post("/api/threads", json={}).json()["thread_id"]
    kept = make(gateway, thread=thread_id, content="# keep")
    gone = make(gateway, thread=thread_id, content="# gone")
    other = make(gateway, thread="another-chat", content="# other")
    c.post(f"/api/artifacts/{kept}/save")
    gone_hash = gateway.store.versions(gateway.user_id, gone)[0]["content_hash"]
    assert c.delete(f"/api/threads/{thread_id}").status_code == 200
    rows = {a["id"] for a in gateway.store.list(gateway.user_id, saved="all")[0]}
    assert rows == {kept, other}
    from app.gateway.artifacts_store import blobs

    assert not blobs.path_for(gateway.user_id, gone_hash).exists()


def test_the_sweep_is_off_by_default_and_never_touches_saved_pinned_or_archived(gateway):
    from types import SimpleNamespace

    import yaml

    from app.gateway.artifacts_store.service import prune_after_days, sweep_once

    example = yaml.safe_load((gateway.tmp / "config.yaml").read_text())
    assert example["artifacts"]["prune_unsaved_after_days"] is None, "the tracked default must be off"
    assert prune_after_days(SimpleNamespace(artifacts=example["artifacts"])) is None
    assert prune_after_days(SimpleNamespace()) is None
    assert prune_after_days(SimpleNamespace(artifacts={"prune_unsaved_after_days": True})) is None
    old = {name: make(gateway, content=f"# {name}") for name in ("unsaved", "saved", "pinned", "archived")}
    gateway.store.set_saved(gateway.user_id, old["saved"], True)
    gateway.store.patch(gateway.user_id, old["pinned"], pinned=True)
    gateway.store.set_saved(gateway.user_id, old["pinned"], True)
    gateway.store.set_archived(gateway.user_id, old["archived"], True)
    assert gateway.store.prune_unsaved(gateway.user_id, older_than_days=30) == 0, "nothing is old yet"
    import time

    future = time.time() + 31 * 86400
    removed = gateway.store.prune_unsaved(gateway.user_id, older_than_days=30, now=future)
    left = {a["id"] for a in gateway.store.list(gateway.user_id, saved="all", archived="all")[0]}
    assert removed == 1 and left == {old["saved"], old["pinned"], old["archived"]}
    assert sweep_once(gateway.store, 10_000) == 0


# -- download ------------------------------------------------------------------------------


def _name(resp) -> str:
    cd = resp.headers["content-disposition"]
    assert cd.startswith("attachment; ")
    return unquote(cd.split("filename*=UTF-8''", 1)[1])


@pytest.mark.parametrize(
    "kind,content,title,lang,expected",
    [
        ("markdown", "# x", "Project brief", None, "Project brief.md"),
        ("markdown", "# x", "notes.md", None, "notes.md"),
        ("code", "print(1)", "script", "python", "script.py"),
        ("code", "x", "thing", "brainfuck", "thing.txt"),
        ("svg", '<svg xmlns="http://www.w3.org/2000/svg"/>', "logo", None, "logo.svg"),
        ("mermaid", "graph TD; A-->B", "flow", None, "flow.mmd"),
        ("image", PNG, "photo.jpg", None, "photo.jpg.png"),
        ("markdown", "# x", "../../etc/passwd", None, "etc_passwd.md"),
        ("markdown", "# x", "evil‮gnp.exe", None, "evilgnp.exe.md"),
        ("markdown", "# x", 'a"b\\c:d*e?f<g>h|i', None, "a_b_c_d_e_f_g_h_i.md"),
        ("markdown", "# x", "...", None, "artifact.md"),
        ("markdown", "# x", "x" * 300, None, "x" * 100 + ".md"),
        ("markdown", "# x", "résumé — draft", None, "résumé — draft.md"),
    ],
)
def test_download_names_and_headers(gateway, kind, content, title, lang, expected):
    aid = make(gateway, kind, content, title=title, language=lang)
    resp = gateway.client.get(f"/api/artifacts/{aid}/versions/1/download")
    assert resp.status_code == 200
    assert _name(resp) == expected
    ascii_part = resp.headers["content-disposition"].split('filename="', 1)[1].split('"', 1)[0]
    assert ascii_part.isascii() and "/" not in ascii_part and "\\" not in ascii_part
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["cache-control"] == "private, no-store"
    assert resp.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert resp.headers["content-type"] == "application/octet-stream"
    if kind == "code":
        assert resp.content == content.encode()


def test_download_of_another_accounts_artifact_is_404(gateway):
    theirs = make(gateway, owner="someone-else")
    assert gateway.client.get(f"/api/artifacts/{theirs}/versions/1/download").status_code == 404


# -- "Save to artifacts" on a chat's output -------------------------------------------------


@pytest.fixture
def chat(gateway):
    thread_id = gateway.client.post("/api/threads", json={}).json()["thread_id"]
    out = get_paths().sandbox_outputs_dir(thread_id, user_id=gateway.user_id)
    out.mkdir(parents=True, exist_ok=True)
    return thread_id, out


def _import(gw, thread_id, path):
    return gw.client.post("/api/artifacts/import", json={"thread_id": thread_id, "path": path})


def test_saving_a_chat_file_makes_a_saved_artifact(gateway, chat):
    thread_id, out = chat
    (out / "brief.md").write_text("# brief")
    (out / "notes.log").write_text("plain notes")
    (out / "data.bin").write_bytes(b"\x00\x01binary")
    resp = _import(gateway, thread_id, "/mnt/user-data/outputs/brief.md")
    assert resp.status_code == 201
    art = gateway.store.get(gateway.user_id, resp.json()["artifact"]["id"])
    assert art["saved"] is True and art["kind"] == "markdown" and art["lineage"] == "import" and art["imported_from"] == f"{thread_id}:/mnt/user-data/outputs/brief.md"
    text = _import(gateway, thread_id, "notes.log").json()["artifact"]
    assert text["kind"] == "file" and gateway.store.versions(gateway.user_id, text["id"])[0]["render"] == "text"
    content = gateway.client.get(f"/api/artifacts/{text['id']}/versions/1/content")
    assert content.headers["content-type"].startswith("text/plain") and content.text == "plain notes"
    binary = _import(gateway, thread_id, "data.bin").json()["artifact"]
    assert gateway.store.versions(gateway.user_id, binary["id"])[0]["render"] == "download"
    again = _import(gateway, thread_id, "brief.md")
    assert again.status_code == 200 and again.json()["created"] is False and again.json()["artifact"]["id"] == art["id"]
    assert len(gateway.store.list(gateway.user_id, saved="all")[0]) == 3


def test_saving_needs_the_owners_chat_and_a_plain_path(gateway, chat, tmp_path):
    thread_id, out = chat
    (tmp_path / "secret.md").write_text("# secret")
    (out / "link.md").symlink_to(tmp_path / "secret.md")
    os.mkfifo(out / "pipe")
    for path in ("../../../secret.md", "/mnt/user-data/outputs/../workspace/x", "link.md", "pipe", "/etc/passwd", "a/../../b", "", "missing.md"):
        resp = _import(gateway, thread_id, path)
        assert resp.status_code in (404, 422), (path, resp.status_code)
    assert _import(gateway, "not-my-chat", "brief.md").json()["detail"]["code"] == "artifact_not_found"
    from app.gateway.internal_auth import create_internal_auth_headers

    assert gateway.client.post("/api/artifacts/import", json={"thread_id": thread_id, "path": "x"}, headers=create_internal_auth_headers()).status_code == 403
    assert gateway.store.list(gateway.user_id, saved="all")[1] == 0


def test_saving_a_web_app_directory_makes_one_webapp(gateway, chat, tmp_path):
    thread_id, out = chat
    site = out / "site"
    (site / "assets").mkdir(parents=True)
    (site / "index.html").write_text('<!doctype html><script src="assets/app.js"></script>')
    (site / "assets" / "app.js").write_text("document.title='x'")
    (site / ".env").write_text("SECRET=1")
    (tmp_path / "outside.js").write_text("leak")
    (site / "assets" / "linked.js").symlink_to(tmp_path / "outside.js")
    resp = _import(gateway, thread_id, "/mnt/user-data/outputs/site")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert sorted(body["skipped"]) == [".env", "assets/linked.js"]
    aid = body["artifact"]["id"]
    assert body["artifact"]["kind"] == "webapp" and body["artifact"]["saved"] is True
    version = gateway.client.get(f"/api/artifacts/{aid}/versions/1").json()
    assert version["render"] == "frame" and version["entry"] == "index.html"
    assert [f["path"] for f in version["files"]] == ["assets/app.js", "index.html"]
    content = gateway.client.get(f"/api/artifacts/{aid}/versions/1/content")
    assert content.headers["content-type"] == "application/json", "a web app is never served as a page here"
    dl = gateway.client.get(f"/api/artifacts/{aid}/versions/1/download")
    names = zipfile.ZipFile(io.BytesIO(dl.content)).namelist()
    assert sorted(names) == ["assets/app.js", "index.html"] and _name(dl) == "site.zip"


def test_web_app_caps_and_entry(gateway, chat, monkeypatch):
    thread_id, out = chat
    (out / "noentry").mkdir()
    (out / "noentry" / "app.js").write_text("x")
    assert _import(gateway, thread_id, "noentry").status_code == 422
    big = out / "big"
    big.mkdir()
    (big / "index.html").write_text("<p>x</p>")
    for i in range(5):
        (big / f"f{i}.js").write_text("y" * 100)
    monkeypatch.setattr(caps, "WEBAPP_FILES", 3)
    assert _import(gateway, thread_id, "big").status_code == 413
    monkeypatch.setattr(caps, "WEBAPP_FILES", 500)
    monkeypatch.setattr(caps, "WEBAPP_BYTES", 300)
    assert _import(gateway, thread_id, "big").status_code == 413
    assert gateway.store.list(gateway.user_id, saved="all")[1] == 0


def test_webapp_bundle_blobs_are_kept_while_any_artifact_uses_them(gateway, chat):
    """A bundle file shared with another artifact's content survives that
    artifact's delete (the reference check counts bundle files)."""
    thread_id, out = chat
    (out / "app").mkdir()
    (out / "app" / "index.html").write_text("# shared bytes")
    aid = _import(gateway, thread_id, "app").json()["artifact"]["id"]
    other = make(gateway, content="# shared bytes")
    gateway.store.set_archived(gateway.user_id, other, True)
    gateway.store.delete(gateway.user_id, other, confirm_id=other, version_count=1)
    dl = gateway.client.get(f"/api/artifacts/{aid}/versions/1/download")
    assert zipfile.ZipFile(io.BytesIO(dl.content)).read("index.html") == b"# shared bytes"


# -- migration -----------------------------------------------------------------------------


def test_existing_artifacts_are_saved_only_where_the_owner_showed_intent(tmp_path):
    from sqlalchemy import create_engine, text

    from omniharness.persistence.engine import migrate_artifacts_saved

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE artifacts (id VARCHAR PRIMARY KEY, owner_id VARCHAR, pinned BOOLEAN, archived_at FLOAT, updated_at FLOAT)"))
        conn.execute(text("CREATE TABLE artifact_versions (artifact_id VARCHAR, origin VARCHAR, created_at FLOAT)"))
        rows = {"plain": (0, None, 10, [("tool", 10)]), "import": (0, None, 10, [("import", 10)]), "pinned": (1, None, 10, [("tool", 10)]), "edited": (0, None, 20, [("tool", 10), ("owner_edit", 20)]),
                "restored": (0, None, 20, [("tool", 10), ("restore", 20)]), "renamed": (0, None, 50, [("tool", 10)]), "archived": (1, 99, 99, [("tool", 10)])}  # fmt: skip
        for aid, (pinned, archived, updated, versions) in rows.items():
            conn.execute(text("INSERT INTO artifacts VALUES (:i, 'o', :p, :a, :u)"), {"i": aid, "p": pinned, "a": archived, "u": updated})
            for origin, created in versions:
                conn.execute(text("INSERT INTO artifact_versions VALUES (:i, :o, :c)"), {"i": aid, "o": origin, "c": created})
    with engine.begin() as conn:
        assert migrate_artifacts_saved(conn, "sqlite") is True
    with engine.begin() as conn:
        saved = {r[0] for r in conn.execute(text("SELECT id FROM artifacts WHERE saved"))}
        assert migrate_artifacts_saved(conn, "sqlite") is False, "runs once"
    assert saved == {"pinned", "edited", "restored", "renamed"}
