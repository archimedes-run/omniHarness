"""Fifth-pass adversarial review of #53: each test asserts the SAFE outcome.

A: grants hand-written into an agent's config.yaml (outside the versioned
store) never go live, not even after an unrelated versioned edit.
"""

from __future__ import annotations

from test_grants import _call, _run, _task, _tasks


def _granted(studio, agent: str) -> list[str]:
    return [k["id"] for k in studio.client.get(f"/api/studio/agents/{agent}/autonomy").json()["classes"] if k["granted"]]


def test_unversioned_disk_grants_stay_off_after_an_unrelated_edit(studio) -> None:
    """config.yaml written outside the store carries `autonomy`. The first
    versioned write of ANY field (here a description) must not adopt those
    grants as its baseline and keep them: grants come only from the Autonomy
    action, so a scheduled run still waits instead of writing on its own."""
    from omniharness.config.paths import get_paths

    c = studio.client
    assert c.post("/api/ledger/projects", json={"name": "Launch"}).status_code == 201
    d = get_paths().user_agent_dir(studio.user_id, "wrap-up")
    d.mkdir(parents=True)
    (d / "config.yaml").write_text("name: wrap-up\nautonomy: [tasks, notes, archive]\n")
    (d / "SOUL.md").write_text("s")
    assert _granted(studio, "wrap-up") == []

    v = c.get("/api/agents/wrap-up").json()["version"]
    r = c.put("/api/agents/wrap-up", json={"description": "just a description edit", "base_version": v})
    assert r.status_code == 200, r.text

    assert _granted(studio, "wrap-up") == [], "grants adopted from disk by an unrelated edit"
    _run(studio, [_call([_task("Ran on its own")], "c1")], scheduled=True)
    assert "Ran on its own" not in _tasks(studio)
    # The edit itself landed, and no version, the baseline included, carries
    # the hand-written grants.
    assert c.get("/api/agents/wrap-up").json()["description"] == "just a description edit"
    from omniharness.config import config_versions

    history = config_versions.agent_history(studio.user_id, "wrap-up")
    assert [v.source for v in history][0] == "existing"
    for version in history:
        assert "autonomy" not in ((version.snapshot or {}).get("config") or {}), version
