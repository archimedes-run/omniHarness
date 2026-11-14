"""Files from a chat's outputs are read without check-then-open races, and blobs
survive concurrent deletes (Spec 012 FR-028, FR-036, FR-037; review M2 and lows).
State is read back from the store and the blob directory."""

from __future__ import annotations

import os

import pytest

import app.gateway.artifacts_store.service as service
from app.gateway.artifacts_store import blobs, caps, safe_open
from app.gateway.artifacts_store.kinds import canonical
from app.gateway.artifacts_store.service import GatewayArtifactController, run_import
from app.policy.lineage import user_turn
from omniharness.config.paths import get_paths
from omniharness.runtime.artifacts.controller import MESSAGES_KEY

OWNER = "owner-1"
THREAD = "thread-a"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture
def outputs(store):
    out = get_paths().sandbox_outputs_dir(THREAD, user_id=OWNER)
    out.mkdir(parents=True)
    return out


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(service, "_LAST_FULL_IMPORT", {})
    monkeypatch.setattr(safe_open, "BEFORE_OPEN", None)


def _titles(store) -> set[str]:
    return {a["title"] for a in store.list(OWNER, archived="all", limit=200)[0]}


def _image(store, source="/mnt/user-data/outputs/pic.png"):
    tools = GatewayArtifactController(lambda: store)
    ctx = {"user_id": OWNER, "thread_id": THREAD, MESSAGES_KEY: [user_turn("x")]}
    return tools.create(ctx, kind="image", title="pic", content=None, language=None, source_path=source, note=None)


def _swap_to_symlink(target):
    def hook(root, rel):
        path = root / rel
        path.unlink()
        path.symlink_to(target)

    return hook


def test_a_file_swapped_for_a_symlink_after_the_check_is_not_read(store, outputs, tmp_path, monkeypatch):
    secret = tmp_path / "secret.md"
    secret.write_text("# owner's private notes")
    (outputs / "notes.md").write_text("# fine")
    monkeypatch.setattr(safe_open, "BEFORE_OPEN", _swap_to_symlink(secret))
    run_import(store, OWNER, thread_id=THREAD)
    assert _titles(store) == set(), "a symlink swapped in after the listing was followed"
    (outputs / "notes.md").unlink()
    (outputs / "pic.png").write_bytes(PNG)
    secret_png = tmp_path / "secret.png"
    secret_png.write_bytes(PNG)
    monkeypatch.setattr(safe_open, "BEFORE_OPEN", _swap_to_symlink(secret_png))
    text, card = _image(store)
    assert card is None and store.list(OWNER)[1] == 0


def test_a_parent_directory_swapped_for_a_symlink_is_not_followed(store, outputs, tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "a.md").write_text("# outside the outputs")
    (outputs / "sub").mkdir()
    (outputs / "sub" / "a.md").write_text("# inside")

    def swap_parent(root, rel):
        (root / "sub" / "a.md").unlink()
        (root / "sub").rmdir()
        (root / "sub").symlink_to(elsewhere)

    monkeypatch.setattr(safe_open, "BEFORE_OPEN", swap_parent)
    run_import(store, OWNER, thread_id=THREAD)
    assert _titles(store) == set()


def test_a_fifo_is_never_opened_and_never_blocks(store, outputs, monkeypatch):
    os.mkfifo(outputs / "pipe.md")
    run_import(store, OWNER, thread_id=THREAD)  # would hang on a blocking open
    assert _titles(store) == set()
    (outputs / "pic.png").write_bytes(PNG)

    def to_fifo(root, rel):
        (root / rel).unlink()
        os.mkfifo(root / rel)

    monkeypatch.setattr(safe_open, "BEFORE_OPEN", to_fifo)
    text, card = _image(store)
    assert card is None and store.list(OWNER)[1] == 0


def test_a_file_growing_past_the_cap_after_the_check_is_refused(store, outputs, monkeypatch):
    monkeypatch.setattr(caps, "BINARY_VERSION_BYTES", 100)
    (outputs / "grow.md").write_text("# small")

    def grow(root, rel):
        with open(root / rel, "ab") as handle:
            handle.write(b"x" * 200)

    monkeypatch.setattr(safe_open, "BEFORE_OPEN", grow)
    run_import(store, OWNER, thread_id=THREAD)
    assert _titles(store) == set()
    (outputs / "pic.png").write_bytes(PNG)
    text, card = _image(store)
    assert card is None and store.list(OWNER)[1] == 0


def test_reads_stop_at_the_cap_plus_one_byte(tmp_path, monkeypatch):
    (tmp_path / "f").write_bytes(b"x" * 50)
    reads: list[int] = []
    real = os.read

    def counting(fd, n):
        chunk = real(fd, n)
        reads.append(len(chunk))
        return chunk

    monkeypatch.setattr(os, "read", counting)
    assert safe_open.read_under(tmp_path, "f", 60) == b"x" * 50
    (tmp_path / "huge").write_bytes(b"x" * 10_000)
    reads.clear()
    with pytest.raises(safe_open.Refused):
        safe_open.read_under(tmp_path, "huge", 60)
    assert sum(reads) == 0, "a file already over the cap was read"
    for bad in ("../f", "/f", "a//f", ".", ""):
        with pytest.raises(safe_open.Refused):
            safe_open.read_under(tmp_path, bad, 60)


def test_an_unchanged_file_is_not_read_again_and_a_big_one_never(store, outputs, monkeypatch):
    monkeypatch.setattr(caps, "BINARY_VERSION_BYTES", 100)
    (outputs / "a.md").write_text("# a")
    (outputs / "big.bin").write_bytes(b"\x01" * 500)
    opened: list[str] = []
    real = safe_open.read_under
    monkeypatch.setattr(safe_open, "read_under", lambda root, rel, cap, **kw: (opened.append(rel), real(root, rel, cap, **kw))[1])
    run_import(store, OWNER, thread_id=THREAD)
    assert opened == ["a.md"], "the file over the cap was read"
    big = next(a for a in store.list(OWNER)[0] if a["title"] == "big.bin")
    assert store.versions(OWNER, big["id"])[0]["stored"] == "chat"
    opened.clear()
    assert run_import(store, OWNER, thread_id=THREAD) == 0
    assert opened == [], "an unchanged file (same size and mtime) was read again"


def test_one_pass_has_a_budget_across_chats(store, monkeypatch):
    monkeypatch.setattr(service, "MAX_FILES_PER_PASS", 3)
    for t in ("t1", "t2"):
        out = get_paths().sandbox_outputs_dir(t, user_id=OWNER)
        out.mkdir(parents=True)
        for i in range(3):
            (out / f"{t}-{i}.md").write_text(f"# {t} {i}")
    run_import(store, OWNER)
    assert len(_titles(store)) == 3


def test_a_changed_file_never_lands_on_the_owners_own_work(store, outputs):
    """A changed chat file becomes a NEW artifact when the owner edited, restored
    or pinned the one it made; otherwise a new version of it."""
    (outputs / "plan.md").write_text("# v1")
    run_import(store, OWNER, thread_id=THREAD)
    [first] = store.list(OWNER)[0]
    store.add_version(OWNER, first["id"], base_version=1, canon=canonical("markdown", "# owner's words"), lineage="user", lineage_source=None, origin="owner_edit")
    os.utime(outputs / "plan.md", ns=(1, 1))
    (outputs / "plan.md").write_text("# worker v2")
    run_import(store, OWNER, thread_id=THREAD)
    rows = store.list(OWNER)[0]
    assert len(rows) == 2 and store.get(OWNER, first["id"])["latest_version"] == 2, "the owner's edit was buried under the worker's file"
    # Untouched by the owner: a new version.
    other = next(r for r in rows if r["id"] != first["id"])
    (outputs / "plan.md").write_text("# worker v3, longer")
    run_import(store, OWNER, thread_id=THREAD)
    assert store.get(OWNER, other["id"])["latest_version"] == 2
    # Pinned: left alone again.
    store.patch(OWNER, other["id"], pinned=True)
    (outputs / "plan.md").write_text("# worker v4, longer still")
    run_import(store, OWNER, thread_id=THREAD)
    assert store.get(OWNER, other["id"])["latest_version"] == 2 and store.list(OWNER)[1] == 3


def test_a_blob_unlinked_between_write_and_commit_is_restored(store, monkeypatch):
    """Another worker's delete may unlink a blob after this write stored it and
    before this write committed; after the commit the blob must exist."""
    real_write = blobs.write
    lost: list[str] = []

    def write_then_lose(owner_id, data):
        content_hash = real_write(owner_id, data)
        if not lost:  # the other worker's unlink, once, in the window
            blobs.delete(owner_id, content_hash)
            lost.append(content_hash)
        return content_hash

    monkeypatch.setattr(blobs, "write", write_then_lose)
    summary, version = store.create(OWNER, kind="markdown", title="x", canon=canonical("markdown", "same bytes"), lineage="user", lineage_source=None, origin="tool")
    monkeypatch.setattr(blobs, "write", real_write)
    _, _, row = store.version(OWNER, summary["id"], 1)
    assert store.content(OWNER, row) == b"same bytes"


def test_delete_in_one_worker_keeps_a_blob_another_worker_committed(store, tmp_path):
    from sqlalchemy import create_engine

    from app.gateway.artifacts_store.store import ArtifactStore

    other_worker = ArtifactStore(create_engine(f"sqlite:///{tmp_path / 'artifacts.db'}", connect_args={"check_same_thread": False}))
    a, _ = store.create(OWNER, kind="markdown", title="a", canon=canonical("markdown", "shared"), lineage="user", lineage_source=None, origin="tool")
    store.set_archived(OWNER, a["id"], True)
    b, _ = other_worker.create(OWNER, kind="markdown", title="b", canon=canonical("markdown", "shared"), lineage="user", lineage_source=None, origin="tool")
    store.delete(OWNER, a["id"], confirm_id=a["id"], version_count=1)
    _, _, row = other_worker.version(OWNER, b["id"], 1)
    assert other_worker.content(OWNER, row) == b"shared"


def test_restore_keeps_the_restored_versions_lineage(store):
    a, _ = store.create(OWNER, kind="markdown", title="a", canon=canonical("markdown", "from a page"), lineage="content", lineage_source="web_fetch", origin="tool")
    store.add_version(OWNER, a["id"], base_version=1, canon=canonical("markdown", "typed"), lineage="user", lineage_source=None, origin="owner_edit")
    store.restore(OWNER, a["id"], version=1, base_version=2)
    v3 = store.versions(OWNER, a["id"])[0]
    assert v3["origin"] == "restore" and v3["lineage"] == "content" and v3["lineage_source"] == "web_fetch"
