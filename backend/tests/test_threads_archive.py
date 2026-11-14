"""Archive and folders for chats: PATCH validation, owner scoping, search filters.

A chat is archived and filed through the existing ``PATCH /api/threads/{id}``
(metadata ``archived`` and ``folder``); ``POST /api/threads/search`` hides
archived chats unless asked (``archived: true`` or ``"all"``) and filters by
``folder``. State is read back from the store, not inferred from status codes.
"""

import asyncio
from uuid import UUID

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient
from langgraph.store.memory import InMemoryStore

from app.gateway.auth.models import User
from app.gateway.routers import threads
from omniharness.persistence.thread_meta.memory import THREADS_NS, MemoryThreadMetaStore

OWNER = UUID("00000000-0000-0000-0000-00000000000a")
OTHER = UUID("00000000-0000-0000-0000-00000000000b")


class _Store(MemoryThreadMetaStore):
    """Reads and writes without the request contextvar (the stub auth sets
    none), but keeps the real ``check_access``: the route's owner check is
    what these tests exercise."""

    async def _get_owned_record(self, thread_id, user_id, method_name):  # type: ignore[override]
        item = await self._store.aget(THREADS_NS, thread_id)
        return dict(item.value) if item is not None else None

    async def search(self, *, metadata=None, status=None, limit=100, offset=0, user_id=None):  # type: ignore[override]
        return await super().search(metadata=metadata, status=status, limit=limit, offset=offset, user_id=None)


def _app(current: dict):
    def user() -> User:
        return User(email="o@example.com", password_hash="x", system_role="user", id=current["id"])

    app = make_authed_test_app(user_factory=user)
    store = InMemoryStore()
    app.state.store = store
    app.state.thread_store = _Store(store)
    app.include_router(threads.router)
    return app, store


def _seed(store, thread_id: str, owner: UUID, metadata: dict, updated: str) -> None:
    record = {
        "thread_id": thread_id,
        "user_id": str(owner),
        "status": "idle",
        "created_at": updated,
        "updated_at": updated,
        "metadata": metadata,
    }
    asyncio.run(store.aput(THREADS_NS, thread_id, record))


def _meta(store, thread_id: str) -> dict:
    item = asyncio.run(store.aget(THREADS_NS, thread_id))
    return dict(item.value.get("metadata") or {})


def test_patch_archives_into_a_folder_and_back():
    app, store = _app({"id": OWNER})
    _seed(store, "t1", OWNER, {"k": "v"}, "2026-11-13T10:00:00+00:00")
    with TestClient(app) as client:
        r = client.patch("/api/threads/t1", json={"metadata": {"archived": True, "folder": "Tests"}})
        assert r.status_code == 200, r.text
        assert _meta(store, "t1") == {"k": "v", "archived": True, "folder": "Tests"}
        r = client.patch("/api/threads/t1", json={"metadata": {"archived": False, "folder": None}})
        assert r.status_code == 200, r.text
    assert _meta(store, "t1") == {"k": "v", "archived": False, "folder": None}


def test_patch_refuses_bad_archive_and_folder_values():
    app, store = _app({"id": OWNER})
    _seed(store, "t1", OWNER, {}, "2026-11-13T10:00:00+00:00")
    with TestClient(app) as client:
        for bad in [
            {"archived": "yes"},
            {"archived": 1},
            {"folder": ""},
            {"folder": " Tests"},
            {"folder": "a" * 41},
            {"folder": "../etc"},
            {"folder": "<b>x</b>"},
            {"folder": 7},
        ]:
            r = client.patch("/api/threads/t1", json={"metadata": bad})
            assert r.status_code == 422, (bad, r.text)
    assert _meta(store, "t1") == {}


def test_patch_still_strips_server_owned_keys():
    app, store = _app({"id": OWNER})
    _seed(store, "t1", OWNER, {}, "2026-11-13T10:00:00+00:00")
    with TestClient(app) as client:
        r = client.patch("/api/threads/t1", json={"metadata": {"archived": True, "user_id": "someone", "turn_provenance": "x"}})
        assert r.status_code == 200, r.text
    assert _meta(store, "t1") == {"archived": True}


def test_another_account_cannot_archive_or_file_the_chat():
    current = {"id": OWNER}
    app, store = _app(current)
    _seed(store, "t1", OWNER, {}, "2026-11-13T10:00:00+00:00")
    current["id"] = OTHER
    with TestClient(app) as client:
        r = client.patch("/api/threads/t1", json={"metadata": {"archived": True, "folder": "Tests"}})
    assert r.status_code in (403, 404), r.text
    assert _meta(store, "t1") == {}


def _search(client, **body) -> list[str]:
    r = client.post("/api/threads/search", json={"limit": 50, **body})
    assert r.status_code == 200, r.text
    return [t["thread_id"] for t in r.json()]


def test_search_hides_archived_by_default_and_filters_on_request():
    app, store = _app({"id": OWNER})
    _seed(store, "live", OWNER, {}, "2026-11-13T10:03:00+00:00")
    _seed(store, "old", OWNER, {"archived": True}, "2026-11-13T10:02:00+00:00")
    _seed(store, "test", OWNER, {"archived": True, "folder": "Tests"}, "2026-11-13T10:01:00+00:00")
    _seed(store, "filed", OWNER, {"folder": "Tests"}, "2026-11-13T10:00:00+00:00")
    with TestClient(app) as client:
        assert sorted(_search(client)) == ["filed", "live"]
        assert sorted(_search(client, archived=True)) == ["old", "test"]
        assert sorted(_search(client, archived="all")) == ["filed", "live", "old", "test"]
        assert sorted(_search(client, archived=True, folder="Tests")) == ["test"]
        assert sorted(_search(client, folder="Tests")) == ["filed"]
        assert sorted(_search(client, archived="all", folder="Tests")) == ["filed", "test"]
        r = client.post("/api/threads/search", json={"archived": "some"})
        assert r.status_code == 422
        r = client.post("/api/threads/search", json={"folder": "../x"})
        assert r.status_code == 422


def test_default_search_pages_count_visible_chats_only():
    app, store = _app({"id": OWNER})
    for i in range(6):
        _seed(store, f"a{i}", OWNER, {"archived": True}, f"2026-11-13T10:0{i}:00+00:00")
    for i in range(3):
        _seed(store, f"v{i}", OWNER, {}, f"2026-11-13T09:0{i}:00+00:00")
    with TestClient(app) as client:
        first = client.post("/api/threads/search", json={"limit": 2}).json()
        second = client.post("/api/threads/search", json={"limit": 2, "offset": 2}).json()
    ids = [t["thread_id"] for t in first + second]
    assert len(first) == 2 and len(second) == 1
    assert sorted(ids) == ["v0", "v1", "v2"]
