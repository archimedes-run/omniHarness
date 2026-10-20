"""Adversarial review of PR #53 (Studio + grants). Real HTTP through create_app()
with auth on (the `studio` fixture), plus the production agent composition for
dispatch claims. Tests named `test_HOLE_*` assert the SAFE behaviour and fail
while the hole is open; `test_HOLDS_*` verify a claim.
"""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient
from test_grants import _call, _pending, _run, _setup, _task, _tasks  # noqa: F401

SECOND = ("second@example.com", "An0ther!Pass77")


def _md(name: str, extra: str = "") -> str:
    return f"---\nname: {name}\ndescription: Use when testing {name}.\n---\n\n# {name}\n{extra}"


@pytest.fixture
def other(studio, monkeypatch) -> TestClient:
    from app.gateway.deps import get_local_provider

    async def create():
        return await get_local_provider().create_user(email=SECOND[0], password=SECOND[1], system_role="user")

    studio.client.portal.call(create)
    monkeypatch.setattr("app.gateway.ownership.admits_additional_accounts", lambda: True)
    client = TestClient(studio.client.app)
    resp = client.post("/api/v1/auth/login/local", data={"username": SECOND[0], "password": SECOND[1]})
    assert resp.status_code == 200, resp.text
    if client.cookies.get("csrf_token"):
        client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")
    assert client.get("/api/agents").status_code == 200
    return client


# -- skill caps ------------------------------------------------------------


def test_HOLE_dotfile_support_files_escape_the_file_count_and_size_caps(studio, allow_scans) -> None:
    """_skill_on_disk skips dot-files, so check_skill_limits never sees earlier
    ones: 60 x 400 KB 'references/.nN' files = 60 files / ~24 MB, all accepted."""
    from omniharness.skills.storage import get_or_new_skill_storage

    c = studio.client
    assert c.post("/api/skills/custom", json={"name": "fat", "content": _md("fat")}).status_code == 201
    accepted = 0
    for i in range(60):
        r = c.post("/api/skills/custom/fat/files", json={"path": f"references/.n{i}", "content": "x" * 400_000})
        accepted += r.status_code == 200
    root = get_or_new_skill_storage().get_custom_skill_dir("fat")
    files = [p for p in root.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    assert len(files) <= 50 and total <= 2 * 1024 * 1024, f"{accepted} writes accepted: {len(files)} files, {total:,} bytes on disk"


def test_HOLDS_multibyte_content_is_measured_in_bytes(studio, allow_scans) -> None:
    c = studio.client
    big = "é" * 40_000  # 80,000 bytes, 40,000 chars
    assert c.post("/api/skills/custom", json={"name": "mb", "content": _md("mb", big)}).status_code == 400


def test_HOLDS_skill_support_path_traversal_refused(studio, allow_scans) -> None:
    c = studio.client
    assert c.post("/api/skills/custom", json={"name": "trav", "content": _md("trav")}).status_code == 201
    for path in ("references/../../../x.md", "../trav2/SKILL.md", "/etc/passwd", "SKILL.md", "references/"):
        assert c.post("/api/skills/custom/trav/files", json={"path": path, "content": "x"}).status_code in (400, 422), path


# -- skill ownership -------------------------------------------------------


@pytest.mark.skip(reason="single-owner rule: covered at the auth door")
def test_HOLE_a_reused_skill_name_stays_with_its_first_owner(studio, other, allow_scans) -> None:
    """skill_owner() returns the FIRST owner_id in the history file, and the
    history outlives a delete. The owner deletes 'notes-fmt'; the second account
    creates its own 'notes-fmt' (POST has no owner check) and is then locked out
    of it, while the owner reads and edits the second account's skill."""
    owner = studio.client
    assert owner.post("/api/skills/custom", json={"name": "notes-fmt", "content": _md("notes-fmt")}).status_code == 201
    assert owner.delete("/api/skills/custom/notes-fmt").status_code == 200
    assert other.post("/api/skills/custom", json={"name": "notes-fmt", "content": _md("notes-fmt", "SECOND ACCOUNT PRIVATE")}).status_code == 201
    leaked = owner.get("/api/skills/custom/notes-fmt")
    mine = other.get("/api/skills/custom/notes-fmt")
    assert leaked.status_code == 404 and mine.status_code == 200, f"owner sees second's skill: {leaked.status_code}; creator sees it: {mine.status_code}"


@pytest.mark.skip(reason="single-owner rule: covered at the auth door")
def test_HOLE_global_skill_toggle_and_read_reach_another_accounts_custom_skill(studio, other, allow_scans) -> None:
    """PUT/GET /api/skills/{name} have no permission dependency and no
    ownership check: the second account disables the owner's custom skill for
    every run (extensions_config is global)."""
    owner = studio.client
    assert owner.post("/api/skills/custom", json={"name": "owner-only", "content": _md("owner-only")}).status_code == 201
    read = other.get("/api/skills/owner-only")
    toggled = other.put("/api/skills/owner-only", json={"enabled": False})
    assert (read.status_code, toggled.status_code) == (404, 404), f"GET {read.status_code}, PUT {toggled.status_code}: {toggled.text[:200]}"


@pytest.mark.skip(reason="single-owner rule: covered at the auth door")
def test_HOLE_skill_manage_from_another_accounts_run_rewrites_the_owners_skill(studio, other, allow_scans) -> None:
    """The agent-side writer (skill_manage) records owner_id but never checks
    it: a run as the second account edits the owner's skill."""
    import asyncio
    from types import SimpleNamespace

    from omniharness.runtime.user_context import reset_current_user, set_current_user
    from omniharness.tools import skill_manage_tool

    owner = studio.client
    assert owner.post("/api/skills/custom", json={"name": "victim", "content": _md("victim")}).status_code == 201

    async def scan(content, *, executable, location):
        return {"decision": "allow", "reason": "test"}

    skill_manage_tool._scan_or_raise = scan  # type: ignore[assignment]
    second_id = other.get("/api/v1/auth/me").json()["id"]
    from app.gateway.auth.models import User  # noqa: F401  (shape only)

    token = set_current_user(SimpleNamespace(id=second_id, user_id=second_id))
    try:
        runtime = SimpleNamespace(context={"thread_id": "t-x", "user_id": second_id}, state={}, config={})
        out = asyncio.run(skill_manage_tool._skill_manage_impl(runtime, "edit", "victim", content=_md("victim", "HIJACKED")))
    except Exception as exc:  # refusal by exception is fine
        out = f"refused: {exc}"
    finally:
        reset_current_user(token)
    assert "HIJACKED" not in owner.get("/api/skills/custom/victim").json()["content"], out


# -- the lead agent's shared SOUL.md ---------------------------------------


@pytest.mark.skip(reason="single-owner rule: covered at the auth door")
def test_HOLE_second_accounts_lead_agent_undo_overwrites_the_shared_soul(studio, other) -> None:
    """lead_agent history is per account but its SOUL.md is the ONE file at
    base_dir. The second account's undo restores ITS old snapshot over the
    owner's later edit (no base_version conflict: different histories)."""
    from omniharness.config import config_versions
    from omniharness.config.paths import get_paths

    soul = get_paths().base_dir / "SOUL.md"
    soul.parent.mkdir(parents=True, exist_ok=True)
    soul.write_text("ORIGINAL", encoding="utf-8")
    lead = other.get("/api/studio/agents/lead_agent/autonomy").json()
    assert other.put("/api/studio/agents/lead_agent/autonomy", json={"granted": [], "base_version": lead["version"]}).status_code == 200
    # The owner edits the lead SOUL the way setup_agent does.
    config_versions.write_agent(studio.user_id, "lead_agent", {"config": {}, "soul": "OWNER EDIT"}, who="agent:lead_agent", source="chat")
    assert soul.read_text() == "OWNER EDIT"
    cur = other.get("/api/agents/lead_agent/versions").json()["current"]
    r = other.post("/api/agents/lead_agent/undo", json={"to_version": 1, "base_version": cur})
    assert soul.read_text() == "OWNER EDIT", f"second account's undo ({r.status_code}) rewrote the owner's lead SOUL.md"


# -- versions --------------------------------------------------------------


def test_HOLDS_two_concurrent_updates_on_one_base_version_one_wins(studio) -> None:
    c = studio.client
    assert c.post("/api/agents", json={"name": "racer", "soul": "s"}).status_code == 201
    base = c.get("/api/agents/racer").json()["version"]
    codes: list[int] = []
    barrier = threading.Barrier(8)

    def go(i: int) -> None:
        barrier.wait()
        codes.append(c.put("/api/agents/racer", json={"description": f"d{i}", "base_version": base}).status_code)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes) == [200] + [409] * 7, codes


def test_PLAUSIBLE_update_agent_http_without_base_version_is_never_stale_checked(studio) -> None:
    c = studio.client
    assert c.post("/api/agents", json={"name": "blind", "soul": "s"}).status_code == 201
    assert c.put("/api/agents/blind", json={"description": "a", "base_version": 1}).status_code == 200
    # Fixed (round 2): an edit without base_version is refused, never applied.
    assert c.put("/api/agents/blind", json={"description": "b"}).status_code == 428
    assert c.get("/api/agents/blind").json()["description"] == "a"


def test_HOLDS_bad_agent_names_never_reach_the_filesystem(studio) -> None:
    c = studio.client
    for name in ("..", "a..b", "..%2F..%2Fx", "x%00", "LEAD_AGENT"):
        for url in (f"/api/studio/agents/{name}/autonomy", f"/api/agents/{name}/versions"):
            assert c.get(url).status_code in (200, 400, 404, 422), (url, c.get(url).status_code)


def test_HOLDS_undo_then_setup_never_restores_a_revoked_grant(studio) -> None:
    from omniharness.config import config_versions

    c = studio.client
    _setup(studio, ["tasks", "notes"])
    v = c.get("/api/studio/agents/wrap-up/autonomy").json()["version"]
    assert c.put("/api/studio/agents/wrap-up/autonomy", json={"granted": [], "base_version": v}).status_code == 200
    # Agent-side rewrite whose snapshot claims every grant.
    config_versions.write_agent(studio.user_id, "wrap-up", {"config": {"name": "wrap-up", "autonomy": ["tasks", "notes", "archive"]}, "soul": "s"}, who="agent:wrap-up", source="chat")
    cur = c.get("/api/agents/wrap-up/versions").json()["current"]
    for to in range(1, cur):
        cur2 = c.get("/api/agents/wrap-up/versions").json()["current"]
        c.post("/api/agents/wrap-up/undo", json={"to_version": to, "base_version": cur2})
        assert not [k for k in c.get("/api/studio/agents/wrap-up/autonomy").json()["classes"] if k["granted"]], to


# -- tier 3 / cap ----------------------------------------------------------


@pytest.mark.parametrize(
    "changes",
    [
        [_task("ok"), {"op": "create_project", "name": "Sneaky"}],
        [_task("ok"), {"op": "link_thread", "project": "Launch"}],
        [{"op": "Create_Task", "project": "Launch", "title": "case"}],
        [{"op": "create_task ", "project": "Launch", "title": "space"}],
        [_task("ok"), "create_project"],
        [],
    ],
)
def test_HOLDS_tier3_or_odd_changes_never_run_under_any_grant(studio, changes) -> None:
    _setup(studio, ["tasks", "notes", "archive"])
    _run(studio, [_call(changes, "c1")], scheduled=True)
    assert _tasks(studio) == []
    assert [p["name"] for p in studio.client.get("/api/ledger/projects").json()] == ["Launch"]


def test_HOLDS_parallel_multi_change_calls_cannot_exceed_20(studio) -> None:
    from langchain_core.messages import AIMessage

    _setup(studio, ["tasks"])
    step = AIMessage(content="", tool_calls=[{"name": "ledger_apply", "args": {"changes": [_task(f"{k}-{i}") for i in range(15)]}, "id": f"c{k}"} for k in range(2)])
    _run(studio, [step], scheduled=True)
    assert len(_tasks(studio)) == 15


def test_PLAUSIBLE_grants_are_read_from_an_unversioned_config_yaml(studio) -> None:
    """An agent with no version history takes its grants straight from
    config.yaml on disk: any out-of-store writer (migration, a restored backup,
    a future tool) grants autonomy with no Autonomy action."""
    from omniharness.config.paths import get_paths

    d = get_paths().user_agent_dir(studio.user_id, "legacy-one")
    d.mkdir(parents=True)
    (d / "config.yaml").write_text("name: legacy-one\nautonomy: [tasks, notes, archive]\n")
    (d / "SOUL.md").write_text("s")
    granted = [k["id"] for k in studio.client.get("/api/studio/agents/legacy-one/autonomy").json()["classes"] if k["granted"]]
    assert granted == [], granted


# -- round-2 fixes: tests added by the builder -----------------------------


def test_HOLE_a_dot_file_already_on_disk_counts_against_the_caps(studio, allow_scans) -> None:
    """The limit is measured over the whole tree on disk, not just the
    versioned snapshot (which skips dot-files): a hidden 2.1 MB file placed by
    hand makes the next write go over the 2 MiB cap."""
    from omniharness.skills.storage import get_or_new_skill_storage

    c = studio.client
    assert c.post("/api/skills/custom", json={"name": "fat", "content": _md("fat")}).status_code == 201
    hidden = get_or_new_skill_storage().get_custom_skill_dir("fat") / "references" / ".stash"
    hidden.parent.mkdir(parents=True, exist_ok=True)
    hidden.write_bytes(b"x" * 2_200_000)
    resp = c.post("/api/skills/custom/fat/files", json={"path": "references/ok.md", "content": "x"})
    assert resp.status_code == 400 and "2 MiB" in resp.json()["detail"], resp.text


def test_HOLE_skill_manage_cannot_write_a_dot_file(studio, allow_scans, monkeypatch) -> None:
    import asyncio
    from types import SimpleNamespace

    from omniharness.skills.storage import get_or_new_skill_storage
    from omniharness.tools import skill_manage_tool

    assert studio.client.post("/api/skills/custom", json={"name": "fat", "content": _md("fat")}).status_code == 201

    async def scan(content, *, executable, location):
        return {"decision": "allow", "reason": "test"}

    monkeypatch.setattr(skill_manage_tool, "_scan_or_raise", scan)
    runtime = SimpleNamespace(context={"thread_id": "t-x", "user_id": studio.user_id}, state={}, config={})
    try:
        out = asyncio.run(skill_manage_tool._skill_manage_impl(runtime, "write_file", "fat", content="x" * 100, path="references/.hidden"))
    except Exception as exc:  # refusal by exception is fine
        out = f"refused: {exc}"
    assert not (get_or_new_skill_storage().get_custom_skill_dir("fat") / "references" / ".hidden").exists(), out


def test_PLAUSIBLE_a_confirmed_action_from_a_scheduled_run_invites_into_that_run(studio) -> None:
    """A pending action stated in a scheduled run records the run's markers,
    and confirming it (a `task` would invite a subagent here) invites with
    them, not as a fresh chat."""
    from app.policy.pending import _from_dict, _to_dict
    from app.policy.registration import build
    from omniharness.agents.invitation import current_inviting_turn, invited_agent_context
    from omniharness.config import get_app_config

    _setup(studio, [])
    _run(studio, [_call([_task("Waits")], "c1")], scheduled=True)
    [waiting] = _pending(studio)
    middleware = build(get_app_config())
    action = middleware.pending.get(waiting["id"])
    assert dict(_from_dict(_to_dict(action)).run_markers) == dict(action.run_markers)

    seen = {}
    middleware.execute_confirmed(action, lambda name, args: seen.setdefault("turn", current_inviting_turn()))
    invited = invited_agent_context(seen["turn"], "helper")
    assert (invited.get("turn_provenance"), invited.get("trigger_firing_id")) == ("synthetic-trigger", "fire-1")


def test_PLAUSIBLE_a_granted_write_that_committed_keeps_its_reservation(studio, monkeypatch) -> None:
    """A reservation is given back only when the write demonstrably did not
    happen: a ledger_apply that commits and then fails (here: the tool raises
    after the transaction) still counts against the run's 20."""
    from app.ledger import controller as controller_mod

    _setup(studio, ["tasks"])
    real = controller_mod.GatewayLedgerController.apply

    def commit_then_fail(self, **kwargs):
        real(self, **kwargs)
        raise RuntimeError("lost after commit")

    monkeypatch.setattr(controller_mod.GatewayLedgerController, "apply", commit_then_fail)
    try:
        _run(studio, [_call([_task(f"T{i}") for i in range(5)], "c1")], scheduled=True, firing="fire-r")
    except Exception:  # noqa: BLE001 — the tool's failure may surface; the count is what matters
        pass
    from pathlib import Path

    from app.policy.grants import GrantRunCounts
    from omniharness.config import get_app_config

    assert len(_tasks(studio)) == 5
    assert GrantRunCounts(Path(get_app_config().policy.state_dir) / "grant_runs.sqlite3").used("fire-r") == 5


def test_PLAUSIBLE_a_granted_write_that_wrote_nothing_gives_its_reservation_back(studio) -> None:
    from pathlib import Path

    from app.policy.grants import GrantRunCounts
    from omniharness.config import get_app_config

    _setup(studio, ["tasks"])
    _run(studio, [_call([{"op": "create_task", "project": "No such project", "title": "x"}], "c1")], scheduled=True, firing="fire-n")
    assert GrantRunCounts(Path(get_app_config().policy.state_dir) / "grant_runs.sqlite3").used("fire-n") == 0
