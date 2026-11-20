"""Deploy, register and connect need the owner's approval of the current code.

An approval records the SHA-256 of the exact source it approves. Deploy,
register and connect answer 403 unless that hash is the hash of the source
stored now; new source ends the approval and stops and disconnects the server
built from the old source. Undeploy, stop and delete work for any server.

Through the real app; docker is a recorder (no daemon is touched).
"""

from __future__ import annotations

import asyncio

from omniharness.persistence.mcp_server.approval import code_sha256

ENTRY = "github-issue-connector"
V1 = "print('v1')\n"
V2 = "print('v2')\n"


def _container(server_id: str) -> str:
    return f"omni-mcp-{server_id[:12]}"


def _repo(studio):
    return studio.client.app.state.mcp_server_repo


def _manager(studio):
    return studio.client.app.state.mcp_server_manager


def _row(studio, server_id: str) -> dict:
    return studio.run(_repo(studio).get, server_id, user_id=studio.owner_id)


def _verified(studio, server_id: str) -> None:
    """The phase approve requires (the sandbox test that reaches it is not on main)."""
    from app.gateway.mcp_server_manager import MCPBuildRecord

    _manager(studio)._records[server_id] = MCPBuildRecord(server_id=server_id, phase="verified", owner_id=studio.owner_id)


def _wait_for_deploy(studio, server_id: str) -> str:
    for _ in range(200):
        phase = _manager(studio)._records[server_id].phase
        if phase != "deploying":
            return phase
        studio.run(asyncio.sleep, 0.01)
    raise AssertionError("the deploy did not finish")


def _docker_verbs(studio) -> list[str]:
    return [call[1] for call in studio.docker.calls]


def _allow_scans(monkeypatch) -> None:
    import app.gateway.mcp_server_manager as mgr
    from omniharness.skills.code_scanner import ScanResult

    async def _allow(*a, **k):
        return ScanResult("allow", "fine")

    monkeypatch.setattr(mgr, "scan_python_code", _allow)


# -- refused without an approval of the current code ---------------------------


def test_deploy_register_and_connect_refuse_without_an_approval(studio):
    server_id = studio.make_server(deployed=False, approved=False, source=V1)
    for verb in ("deploy", "register", "connect"):
        resp = studio.client.post(f"/api/mcp-studio/servers/{server_id}/{verb}")
        assert resp.status_code == 403, (verb, resp.text)
        assert "approve" in resp.json()["detail"].lower()
    assert studio.docker.calls == []
    assert ENTRY not in studio.config_servers()
    assert _row(studio, server_id)["approved"] is False


def test_an_approval_of_older_code_does_not_count(studio):
    server_id = studio.make_server(deployed=False, approved=True, source=V1)
    studio.run(_repo(studio).update_source_code, server_id, V2, user_id=studio.owner_id)
    row = _row(studio, server_id)
    assert row["approved"] is False and row["approved_code_sha256"] is None
    for verb in ("deploy", "register", "connect"):
        assert studio.client.post(f"/api/mcp-studio/servers/{server_id}/{verb}").status_code == 403, verb
    assert studio.docker.calls == []


def test_a_stale_approval_hash_is_never_read_as_approved(studio):
    """Even an approval record left pointing at other code (no clearing write)."""
    from sqlalchemy import update

    from omniharness.persistence.engine import get_session_factory
    from omniharness.persistence.mcp_server.model import McpServerRow

    server_id = studio.make_server(deployed=False, approved=False, source=V2)

    async def _stale():
        async with get_session_factory()() as session:
            await session.execute(update(McpServerRow).where(McpServerRow.id == server_id).values(approved=True, approved_code_sha256=code_sha256(V1)))
            await session.commit()

    studio.run(_stale)
    assert _row(studio, server_id)["approved"] is False
    assert studio.client.post(f"/api/mcp-studio/servers/{server_id}/deploy").status_code == 403


def test_connect_refuses_a_container_built_from_other_code(studio):
    server_id = studio.make_server(deployed=True, source=V1)
    # The owner approves new code; the running container is still the old code.
    studio.run(_repo(studio).update_source_code, server_id, V2, user_id=studio.owner_id)
    assert studio.run(_repo(studio).record_approval, server_id, code_sha256_approved=code_sha256(V2), approved_by=studio.owner_id, user_id=studio.owner_id)
    resp = studio.client.post(f"/api/mcp-studio/servers/{server_id}/connect")
    assert resp.status_code == 403, resp.text
    assert ENTRY not in studio.config_servers()


# -- approve -----------------------------------------------------------------------


def test_approve_records_the_hash_of_the_current_code_and_who(studio):
    server_id = studio.make_server(deployed=False, approved=False, source=V1)
    _verified(studio, server_id)
    resp = studio.client.post(f"/api/mcp-studio/servers/{server_id}/approve", json={"code_sha256": code_sha256(V1)})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["approved"] is True and body["approved_code_sha256"] == code_sha256(V1) == body["code_sha256"]
    row = _row(studio, server_id)
    assert row["approved_by"] == studio.owner_id and row["approved_at"]

    # A second click changes nothing.
    first_at = row["approved_at"]
    _verified(studio, server_id)
    assert studio.client.post(f"/api/mcp-studio/servers/{server_id}/approve").status_code == 200
    assert _row(studio, server_id)["approved_at"] == first_at


def test_approve_refuses_when_the_code_changed_since_it_was_shown(studio):
    server_id = studio.make_server(deployed=False, approved=False, source=V2)
    _verified(studio, server_id)
    resp = studio.client.post(f"/api/mcp-studio/servers/{server_id}/approve", json={"code_sha256": code_sha256(V1)})
    assert resp.status_code == 409, resp.text
    assert _row(studio, server_id)["approved"] is False


def test_approve_still_requires_a_verified_test(studio):
    server_id = studio.make_server(deployed=False, approved=False, source=V1)
    assert studio.client.post(f"/api/mcp-studio/servers/{server_id}/approve").status_code == 404
    assert _row(studio, server_id)["approved"] is False


# -- deploy ---------------------------------------------------------------------------


def test_deploy_runs_the_approved_code_and_never_approves_by_itself(studio):
    server_id = studio.make_server(deployed=False, approved=True, source=V1)
    studio.docker.results = {"run": (0, "abc123container\n", "")}
    resp = studio.client.post(f"/api/mcp-studio/servers/{server_id}/deploy")
    assert resp.status_code == 200, resp.text
    assert _wait_for_deploy(studio, server_id) == "deployed"
    row = _row(studio, server_id)
    assert row["deployed_code_sha256"] == code_sha256(V1)
    assert row["approved_by"] == studio.owner_id, "deploy rewrote the approval"
    assert studio.client.get(f"/api/mcp-studio/servers/{server_id}").json()["deployed_code_current"] is True

    resp = studio.client.post(f"/api/mcp-studio/servers/{server_id}/connect")
    assert resp.status_code == 200, resp.text
    assert ENTRY in studio.config_servers()


def test_an_unapproved_deploy_leaves_the_server_unapproved(studio):
    server_id = studio.make_server(deployed=False, approved=False, source=V1)
    assert studio.client.post(f"/api/mcp-studio/servers/{server_id}/deploy").status_code == 403
    row = _row(studio, server_id)
    assert row["approved"] is False and row["approved_code_sha256"] is None and row["approved_by"] is None
    assert row["container_id"] is None and studio.docker.calls == []


def test_a_second_deploy_click_starts_no_second_build(studio):
    server_id = studio.make_server(deployed=False, approved=True, source=V1)
    gate = asyncio.Event()
    recorder = studio.docker

    async def _slow(args, *, timeout=120.0, cwd=None):
        if args[1] == "build":
            await gate.wait()
        return await recorder(args, timeout=timeout, cwd=cwd)

    _manager(studio)._docker_run = _slow
    assert studio.client.post(f"/api/mcp-studio/servers/{server_id}/deploy").status_code == 200
    assert studio.client.post(f"/api/mcp-studio/servers/{server_id}/deploy").status_code == 200
    studio.run(gate.set)
    assert _wait_for_deploy(studio, server_id) == "deployed"
    assert _docker_verbs(studio).count("build") == 1


def test_code_changed_during_a_deploy_removes_the_new_container(studio):
    server_id = studio.make_server(deployed=False, approved=True, source=V1)
    recorder = studio.docker
    repo = _repo(studio)

    async def _change_mid_build(args, *, timeout=120.0, cwd=None):
        if args[1] == "build":
            await repo.update_source_code(server_id, V2, user_id=studio.owner_id)
        return await recorder(args, timeout=timeout, cwd=cwd)

    _manager(studio)._docker_run = _change_mid_build
    assert studio.client.post(f"/api/mcp-studio/servers/{server_id}/deploy").status_code == 200
    assert _wait_for_deploy(studio, server_id) == "failed"
    verbs = _docker_verbs(studio)
    assert "run" in verbs and verbs[-2:] == ["stop", "rm"], verbs
    row = _row(studio, server_id)
    assert row["container_id"] is None and row["deployed_code_sha256"] is None


# -- new code stops what ran the old code ----------------------------------------------


def test_new_code_stops_and_disconnects_the_running_server(studio, monkeypatch):
    _allow_scans(monkeypatch)
    server_id = studio.make_server(deployed=True, source=V1)
    assert studio.client.post(f"/api/mcp-studio/servers/{server_id}/connect").status_code == 200
    assert ENTRY in studio.config_servers()
    studio.docker.calls.clear()

    studio.run(_manager(studio).submit_source_and_test, server_id=server_id, user_id=studio.owner_id, source_code=V2)

    name = _container(server_id)
    assert ["docker", "stop", name] in studio.docker.calls and ["docker", "rm", name] in studio.docker.calls
    assert ENTRY not in studio.config_servers()
    assert "hand-written" in studio.config_servers()
    row = _row(studio, server_id)
    assert row["approved"] is False and row["container_id"] is None and row["status"] != "deployed"
    assert studio.client.post(f"/api/mcp-studio/servers/{server_id}/connect").status_code == 403


def test_new_code_is_not_saved_when_the_old_server_cannot_be_stopped(studio, monkeypatch):
    _allow_scans(monkeypatch)
    server_id = studio.make_server(deployed=True, source=V1)
    studio.docker.results = {"rm": (1, "", "Error response from daemon: permission denied")}
    import pytest

    from app.gateway.mcp_server_manager import McpTeardownError

    with pytest.raises(McpTeardownError):
        studio.run(_manager(studio).submit_source_and_test, server_id=server_id, user_id=studio.owner_id, source_code=V2)
    row = _row(studio, server_id)
    assert row["source_code"] == V1 and row["approved"] is True


def test_identical_code_keeps_the_approval(studio, monkeypatch):
    _allow_scans(monkeypatch)
    server_id = studio.make_server(deployed=True, source=V1)
    studio.docker.calls.clear()
    studio.run(_manager(studio).submit_source_and_test, server_id=server_id, user_id=studio.owner_id, source_code=V1)
    assert _row(studio, server_id)["approved"] is True
    assert studio.docker.calls == []


def test_a_restart_resurrects_no_approval_or_connection_for_changed_code(studio):
    server_id = studio.make_server(deployed=True, source=V1)
    studio.run(_repo(studio).update_source_code, server_id, V2, user_id=studio.owner_id)
    # A restart: the in-memory build records are gone; only the database is left.
    _manager(studio)._records.clear()
    detail = studio.client.get(f"/api/mcp-studio/servers/{server_id}").json()
    assert detail["approved"] is False and detail["deployed_code_current"] is False
    for verb in ("connect", "deploy", "register"):
        assert studio.client.post(f"/api/mcp-studio/servers/{server_id}/{verb}").status_code == 403, verb


def test_an_approval_and_deployment_survive_a_restart(studio):
    server_id = studio.make_server(deployed=True, source=V1)
    _manager(studio)._records.clear()
    assert studio.client.get(f"/api/mcp-studio/servers/{server_id}").json()["approved"] is True
    assert studio.client.post(f"/api/mcp-studio/servers/{server_id}/connect").status_code == 200


# -- teardown works for any server -------------------------------------------------------


def test_stop_undeploy_and_delete_work_for_an_unapproved_server(studio):
    for verb in ("stop", "undeploy"):
        server_id = studio.make_server(deployed=True, approved=False, source=V1)
        assert studio.client.post(f"/api/mcp-studio/servers/{server_id}/{verb}").status_code == 200, verb
    server_id = studio.make_server(deployed=True, approved=False, source=V1)
    assert studio.client.delete(f"/api/mcp-studio/servers/{server_id}").status_code == 204


# -- connect writes the config atomically -------------------------------------------------


def test_a_crash_between_write_and_rename_leaves_the_config_whole(studio):
    from unittest.mock import patch

    server_id = studio.make_server(deployed=True, source=V1)
    before = studio.extensions.read_text()
    written: list[str] = []

    def _crash(src, dst):
        written.append(open(src).read())  # the new file was written in full
        raise OSError("simulated crash before rename")

    with patch("omniharness.config.extensions_config.os.replace", _crash):
        resp = studio.client.post(f"/api/mcp-studio/servers/{server_id}/connect")
    assert resp.status_code == 500
    assert written and ENTRY in written[0]
    assert studio.extensions.read_text() == before
    assert [p.name for p in studio.extensions.parent.iterdir() if p.name.startswith(f".{studio.extensions.name}.")] == []

    assert studio.client.post(f"/api/mcp-studio/servers/{server_id}/connect").status_code == 200
    assert ENTRY in studio.config_servers() and "hand-written" in studio.config_servers()


def test_connect_twice_is_one_entry(studio):
    server_id = studio.make_server(deployed=True, source=V1)
    assert studio.client.post(f"/api/mcp-studio/servers/{server_id}/connect").status_code == 200
    assert studio.client.post(f"/api/mcp-studio/servers/{server_id}/connect").status_code == 200
    assert list(studio.config_servers()).count(ENTRY) == 1


def test_connect_leaves_an_entry_it_did_not_write(studio):
    import json

    data = json.loads(studio.extensions.read_text())
    data["mcpServers"][ENTRY] = {"enabled": True, "type": "stdio", "command": "echo"}
    studio.extensions.write_text(json.dumps(data))
    server_id = studio.make_server(deployed=True, source=V1)
    resp = studio.client.post(f"/api/mcp-studio/servers/{server_id}/connect")
    assert resp.status_code == 400, resp.text
    assert studio.config_servers()[ENTRY]["type"] == "stdio"
