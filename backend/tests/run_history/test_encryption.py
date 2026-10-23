"""Encryption at rest (app/run_history/crypto.py): per-run data keys wrapped by
a master key, both in a key directory outside the run database, the project,
the data dir and every agent mount. Crypto-shredding on delete, expiry and
delete-all. Fake values only."""

from __future__ import annotations

import base64
import os
import shutil
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.run_history.crypto import KEY_STORE_NAME, KeyRefused, StoreKey
from app.run_history.store import UNREADABLE, RunHistory

MARKER = "MAIL-BODY-MARKER-7f3a9c"


def everything(*roots: Path) -> bytes:
    return b"".join(p.read_bytes() for root in roots for p in root.rglob("*") if p.is_file())


def assert_no_marker(data: bytes, marker: str = MARKER) -> None:
    for form in (marker.encode(), base64.b64encode(marker.encode()), base64.b64encode(b"x" + marker.encode())[4:20]):
        assert form not in data, f"{form[:12]!r}… is readable on disk"


def history(root: Path, key_dir: Path) -> RunHistory:
    return RunHistory(root, redact=lambda t: (t, True), key=StoreKey(key_dir / "run_store.key", forbidden=[]))


def record(h: RunHistory, text: str, *, big: bool = False, **kw) -> str:
    body = {"messages": [{"type": "tool", "content": text + (" pad" * 20_000 if big else "")}]}
    return h.record(kind="automation", source_id="r", status="completed", body=body, error=f"failed near {text}", **kw)


@pytest.fixture
def dirs(tmp_path):
    return tmp_path / "db", tmp_path / "keys"


def test_content_is_never_on_disk_in_the_clear(dirs) -> None:
    db, keys = dirs
    h = history(db, keys)
    inline, blob = record(h, MARKER), record(h, MARKER + "-B", big=True)
    assert_no_marker(everything(db, keys))
    assert MARKER in h.get(inline)["body"]["messages"][0]["content"]
    assert MARKER in h.get(blob)["body"]["messages"][0]["content"] and MARKER in h.get(blob)["error"]


def test_deleting_one_run_shreds_it_even_in_an_old_copy(dirs, tmp_path) -> None:
    """A copy of the database taken BEFORE the delete, opened with the current
    master key and the current key store: the deleted run cannot be opened,
    the others still can."""
    db, keys = dirs
    h = history(db, keys)
    gone, kept = record(h, MARKER), record(h, "kept-run")
    shutil.copytree(db, tmp_path / "old-copy")

    assert h.delete_run(gone)

    old = history(tmp_path / "old-copy", keys)
    assert old.get(gone)["body"] == {"withheld": UNREADABLE}, "a deleted run opens from an old copy of the database"
    assert old.get(gone)["error"] == UNREADABLE
    assert "kept-run" in old.get(kept)["body"]["messages"][0]["content"], "the other runs must still open"


def test_expiry_destroys_the_expired_runs_keys(dirs, tmp_path) -> None:
    db, keys = dirs
    h = history(db, keys)
    expired = record(h, MARKER, started_at=datetime.now(UTC) - timedelta(days=40))
    kept = record(h, "recent-run")
    shutil.copytree(db, tmp_path / "old-copy")

    assert h.purge() == 1

    assert expired not in h.key.key_ids() and kept in h.key.key_ids()
    old = history(tmp_path / "old-copy", keys)
    assert old.get(expired)["body"] == {"withheld": UNREADABLE}
    assert "recent-run" in old.get(kept)["body"]["messages"][0]["content"]


def test_delete_all_rotates_the_master_key(dirs, tmp_path) -> None:
    db, keys = dirs
    h = history(db, keys)
    ids = [record(h, MARKER), record(h, MARKER + "-B", big=True)]
    shutil.copytree(db, tmp_path / "old-copy")
    old_master = (keys / "run_store.key").read_bytes()

    h.delete_all()

    assert (keys / "run_store.key").read_bytes() != old_master, "the master key was not rotated"
    assert h.key.key_ids() == set(), "data keys survived delete-all"
    assert_no_marker(everything(db, keys))
    old = history(tmp_path / "old-copy", keys)
    for rid in ids:
        assert old.get(rid)["body"] == {"withheld": UNREADABLE}, "an old copy opens with the new keys"


def test_unsafe_key_files_are_refused(tmp_path) -> None:
    keys = tmp_path / "keys"
    StoreKey(keys / "run_store.key", forbidden=[]).key()
    os.chmod(keys / "run_store.key", 0o644)
    with pytest.raises(KeyRefused, match="0600"):
        StoreKey(keys / "run_store.key", forbidden=[]).key()
    os.chmod(keys / "run_store.key", 0o600)
    os.chmod(keys / KEY_STORE_NAME, 0o644)
    with pytest.raises(KeyRefused, match="0600"):
        StoreKey(keys / "run_store.key", forbidden=[]).key()
    with pytest.raises(KeyRefused, match="must not be inside"):
        StoreKey(tmp_path / "proj" / "keys" / "run_store.key", forbidden=[tmp_path / "proj"])


def test_the_key_files_are_created_owner_only(tmp_path) -> None:
    keys = tmp_path / "keys"
    StoreKey(keys / "run_store.key", forbidden=[]).key()
    assert stat.S_IMODE(keys.stat().st_mode) == 0o700
    for f in (keys / "run_store.key", keys / KEY_STORE_NAME):
        assert stat.S_IMODE(f.stat().st_mode) == 0o600


def test_the_master_key_is_a_known_secret(dirs) -> None:
    from omniharness.utils.known_secrets import KNOWN_SECRETS

    db, keys = dirs
    history(db, keys)
    raw = (keys / "run_store.key").read_text().strip()
    out, _ = KNOWN_SECRETS.redact(f"key={raw}")
    assert raw not in out


# -- where the keys live --------------------------------------------------------------


def test_the_default_key_dir_is_outside_the_project_and_the_data_dir(monkeypatch, tmp_path) -> None:
    """So no copy of the project or of backend/.omni-harness (where a backup of
    the database would sit) can ever include the keys."""
    from app.run_history.crypto import default_key_path, forbidden_roots

    monkeypatch.delenv("OMNI_HARNESS_RUN_STORE_KEY_FILE")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    path = default_key_path().resolve()
    repo = Path(__file__).resolve().parents[3]
    assert repo not in path.parents and (repo / "backend" / ".omni-harness") not in path.parents
    for root in forbidden_roots():
        assert root not in path.parents


def test_a_sandbox_mount_over_the_key_dir_is_refused(tmp_path) -> None:
    keys = tmp_path / "secrets"
    with pytest.raises(KeyRefused):
        StoreKey(keys / "run_store.key", forbidden=[tmp_path])


def test_no_agent_file_tool_mapping_reaches_the_key_dir(gateway) -> None:
    """The local sandbox's path mappings (what read_file/bash can reach), as the
    gateway builds them, never cover the key directory."""
    from app.run_history.crypto import default_key_path
    from omniharness.config.paths import get_paths
    from omniharness.sandbox.local.local_sandbox_provider import LocalSandboxProvider

    key_dir = default_key_path().resolve().parent
    reachable = [Path(m.local_path).resolve() for m in LocalSandboxProvider()._path_mappings] + [get_paths().base_dir.resolve()]
    for local in reachable:
        assert local != key_dir and local not in key_dir.parents, f"{local} exposes the key dir to agents"


def test_no_backup_script_copies_the_keys_with_the_database() -> None:
    """Rule: the key directory is never backed up together with the run
    database. No backup routine exists today; any script that names the
    database must not name the key files."""
    repo = Path(__file__).resolve().parents[3]
    scripts = [p for d in (repo / "scripts", repo / "backend" / "scripts") if d.exists() for p in d.rglob("*") if p.is_file() and p.suffix in {".py", ".sh", ""}]
    for path in scripts + [repo / "Makefile", repo / "backend" / "Makefile"]:
        if not path.exists():
            continue
        text = path.read_text(errors="ignore")
        if "runs.sqlite3" in text or "run-history" in text or "omniharness.db" in text:
            for key_ref in ("run_store.key", "run_store_keys", ".omni-harness-secrets", "OMNI_HARNESS_RUN_STORE_KEY_FILE"):
                assert key_ref not in text, f"{path.relative_to(repo)} handles the database AND {key_ref}"


def test_delete_all_over_http_leaves_no_readable_content(gateway) -> None:
    from app.run_history.crypto import default_key_path

    client, home = gateway
    h = client.app.state.run_history
    record(h, MARKER)
    record(h, MARKER + "-B", big=True)
    assert client.delete("/api/run-history/runs", params={"confirm": "delete-all"}).status_code == 200
    assert_no_marker(everything(home / "run-history", default_key_path().parent))


def test_an_unsafe_key_file_keeps_the_history_closed(make_gateway) -> None:
    """Startup refuses a world-readable key: the run history is unavailable
    (503, said in words), never opened with content in the clear."""
    from app.run_history.crypto import default_key_path

    path = default_key_path()
    StoreKey(path, forbidden=[]).key()
    os.chmod(path, 0o644)
    with make_gateway() as (client, _):
        assert client.app.state.run_history is None
        resp = client.get("/api/run-history/settings")
        assert resp.status_code == 503 and "not available" in resp.json()["detail"]


def test_deleting_one_run_over_http_destroys_its_key(gateway) -> None:
    client, _ = gateway
    h = client.app.state.run_history
    gone, kept = record(h, MARKER), record(h, "kept-run")
    assert client.delete(f"/api/run-history/runs/{gone}").status_code == 204
    assert client.get(f"/api/run-history/runs/{gone}").status_code == 404
    assert gone not in h.key.key_ids() and kept in h.key.key_ids()
    assert client.delete(f"/api/run-history/runs/{gone}").status_code == 404


def test_the_key_files_have_their_own_subdirectory_and_touch_nothing_else(tmp_path, monkeypatch) -> None:
    """~/.omni-harness-secrets also holds watcher.token: the run store's files
    live in run-store/, and creating, rotating and purging leave every other
    file of the secrets dir as it was."""
    from app.run_history.crypto import default_key_path

    monkeypatch.delenv("OMNI_HARNESS_RUN_STORE_KEY_FILE")
    monkeypatch.setenv("HOME", str(tmp_path))
    secrets_dir = tmp_path / ".omni-harness-secrets"
    secrets_dir.mkdir(mode=0o700)
    (secrets_dir / "watcher.token").write_text("FAKE-WATCHER-TOKEN")
    os.chmod(secrets_dir / "watcher.token", 0o600)
    before = {p.name: (p.read_bytes(), stat.S_IMODE(p.stat().st_mode)) for p in secrets_dir.iterdir()}

    path = default_key_path()
    assert path.parent == secrets_dir / "run-store"
    h = RunHistory(tmp_path / "db", redact=lambda t: (t, True), key=StoreKey(path, forbidden=[]))
    record(h, MARKER, started_at=datetime.now(UTC) - timedelta(days=40))
    h.purge()
    h.delete_all()

    after = {p.name: (p.read_bytes(), stat.S_IMODE(p.stat().st_mode)) for p in secrets_dir.iterdir() if p.name != "run-store"}
    assert after == before, "the run store touched another file of the secrets dir"
