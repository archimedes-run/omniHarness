"""The run history through create_app() and its lifespan: opened under the
data dir at startup, read, retention set, and deleted only when confirmed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


def test_startup_opens_the_history_under_the_data_dir(gateway) -> None:
    client, home = gateway
    settings = client.get("/api/run-history/settings").json()
    assert settings == {"retention_days": 30, "runs": 0, "location": str((home / "run-history").resolve()), "used_bytes": 0, "cap_bytes": 512 * 1024 * 1024, "warning": None}
    assert (home / "run-history" / "runs.sqlite3").exists()


def test_runs_are_read_and_retention_is_set(gateway) -> None:
    client, _ = gateway
    history = client.app.state.run_history
    old = history.record(kind="automation", source_id="brief", body={"reply": "old"}, status="completed", started_at=datetime.now(UTC) - timedelta(days=10))
    new = history.record(kind="automation", source_id="brief", body={"reply": "new"}, status="completed")

    listed = client.get("/api/run-history/runs", params={"kind": "automation", "source_id": "brief"}).json()
    assert [r["id"] for r in listed] == [new, old]
    assert client.get(f"/api/run-history/runs/{new}").json()["body"] == {"reply": "new"}

    resp = client.put("/api/run-history/settings", json={"retention_days": 7})
    assert resp.status_code == 200 and resp.json()["retention_days"] == 7
    assert resp.json()["runs"] == 1, "a shorter retention did not purge now"
    assert client.get(f"/api/run-history/runs/{old}").status_code == 404
    assert client.put("/api/run-history/settings", json={"retention_days": 0}).status_code == 422


def test_deleting_the_history_needs_confirmation(gateway) -> None:
    client, _ = gateway
    client.app.state.run_history.record(kind="automation", source_id="brief", body={}, status="completed")

    assert client.delete("/api/run-history/runs", params={"confirm": "yes"}).status_code == 422
    assert client.app.state.run_history.count() == 1
    resp = client.delete("/api/run-history/runs", params={"confirm": "delete-all"})
    assert resp.status_code == 200 and resp.json() == {"deleted": 1, "threads_deleted": 0, "threads_failed": []}
    assert client.get("/api/run-history/settings").json()["runs"] == 0


def test_the_routes_need_a_signed_in_user(gateway) -> None:
    client, _ = gateway
    client.cookies.clear()
    assert client.get("/api/run-history/settings").status_code == 401


@pytest.mark.asyncio
async def test_the_purge_job_purges_on_its_schedule(tmp_path) -> None:
    import asyncio

    from app.run_history.lifespan import purge_forever
    from app.run_history.store import RunHistory

    history = RunHistory(tmp_path)
    history.record(kind="automation", source_id="r", body={}, status="completed", started_at=datetime.now(UTC) - timedelta(days=40))
    task = asyncio.create_task(purge_forever(history, interval=0.01))
    for _ in range(100):
        await asyncio.sleep(0.02)
        if history.count() == 0:
            break
    task.cancel()
    assert history.count() == 0, "the scheduled purge never ran"


def test_settings_show_the_cap_warning(gateway) -> None:
    client, _ = gateway
    history = client.app.state.run_history
    history.total_max_bytes = 1_000
    history.record(kind="automation", source_id="r", body={"note": "a" * 2_000}, status="completed")

    settings = client.get("/api/run-history/settings").json()
    assert settings["cap_bytes"] == 1_000
    assert "recorded without its content" in settings["warning"]


def test_a_run_whose_blob_is_gone_reads_as_withheld_over_http(gateway) -> None:
    client, home = gateway
    history = client.app.state.run_history
    run_id = history.record(kind="automation", source_id="r", body={"big": "m" * (70 * 1024)}, status="completed")
    (history.blobs / f"{run_id}.json").unlink()

    resp = client.get(f"/api/run-history/runs/{run_id}")
    assert resp.status_code == 200
    assert "Withheld" in resp.json()["body"]["withheld"]
