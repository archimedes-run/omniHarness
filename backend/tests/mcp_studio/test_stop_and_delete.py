"""Stopping or deleting a built MCP server removes what it left running.

Before: stop only changed the status, so the container (``--restart
unless-stopped``, the owner's secrets in its env) kept running, and delete
left the container and its extensions_config entry behind.

Through the real app; docker is a recorder (no daemon is touched).
"""

from __future__ import annotations

CONTAINER = "omni-mcp-{}"
ENTRY = "github-issue-connector"


def _container(server_id: str) -> str:
    return CONTAINER.format(server_id[:12])


def _deployed_and_connected(studio) -> str:
    server_id = studio.make_server()
    resp = studio.client.post(f"/api/mcp-studio/servers/{server_id}/connect")
    assert resp.status_code == 200, resp.text
    assert ENTRY in studio.config_servers()
    resp = studio.client.put(f"/api/mcp-studio/servers/{server_id}/secrets", json={"secrets": {"GITHUB_TOKEN": "ghp_value_12345"}})
    assert resp.status_code == 200, resp.text
    studio.docker.calls.clear()
    return server_id


def test_stop_stops_and_removes_the_container_and_its_config_entry(studio):
    server_id = _deployed_and_connected(studio)
    resp = studio.client.post(f"/api/mcp-studio/servers/{server_id}/stop")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "stopped"
    name = _container(server_id)
    assert studio.docker.calls == [["docker", "stop", name], ["docker", "rm", name]]
    assert ENTRY not in studio.config_servers()
    assert "hand-written" in studio.config_servers(), "an entry the studio did not write was removed"


def test_undeploy_takes_the_same_path(studio):
    server_id = _deployed_and_connected(studio)
    resp = studio.client.post(f"/api/mcp-studio/servers/{server_id}/undeploy")
    assert resp.status_code == 200, resp.text
    name = _container(server_id)
    assert studio.docker.calls == [["docker", "stop", name], ["docker", "rm", name]]
    assert ENTRY not in studio.config_servers()


def test_delete_removes_container_secrets_config_entry_and_record(studio):
    server_id = _deployed_and_connected(studio)
    assert studio.secret_rows(server_id) == ["GITHUB_TOKEN"]
    resp = studio.client.delete(f"/api/mcp-studio/servers/{server_id}")
    assert resp.status_code == 204, resp.text
    name = _container(server_id)
    assert ["docker", "stop", name] in studio.docker.calls
    assert ["docker", "rm", name] in studio.docker.calls
    assert studio.secret_rows(server_id) == []
    assert ENTRY not in studio.config_servers()
    assert studio.client.get(f"/api/mcp-studio/servers/{server_id}").status_code == 404


def test_a_container_that_is_already_gone_counts_as_removed(studio):
    server_id = _deployed_and_connected(studio)
    studio.docker.results = {verb: (1, "", f"Error response from daemon: No such container: {_container(server_id)}") for verb in ("stop", "rm")}
    assert studio.client.delete(f"/api/mcp-studio/servers/{server_id}").status_code == 204


def test_a_failed_removal_is_reported_and_nothing_is_deleted(studio):
    server_id = _deployed_and_connected(studio)
    studio.docker.results = {"rm": (1, "", "Error response from daemon: permission denied")}

    resp = studio.client.post(f"/api/mcp-studio/servers/{server_id}/stop")
    assert resp.status_code == 502, resp.text
    assert "permission denied" in resp.json()["detail"]
    assert studio.client.get(f"/api/mcp-studio/servers/{server_id}").json()["status"] == "deployed"

    resp = studio.client.delete(f"/api/mcp-studio/servers/{server_id}")
    assert resp.status_code == 502, resp.text
    assert "not deleted" in resp.json()["detail"]
    # Still there, so the delete can be retried: record, secrets, config entry.
    assert studio.client.get(f"/api/mcp-studio/servers/{server_id}").status_code == 200
    assert studio.secret_rows(server_id) == ["GITHUB_TOKEN"]
    assert ENTRY in studio.config_servers()


def test_another_account_cannot_stop_or_delete_the_owners_server(studio):
    from .conftest import OTHER_EMAIL, OTHER_PASSWORD

    server_id = _deployed_and_connected(studio)
    studio.login(OTHER_EMAIL, OTHER_PASSWORD)
    assert studio.client.post(f"/api/mcp-studio/servers/{server_id}/stop").status_code == 404
    assert studio.client.delete(f"/api/mcp-studio/servers/{server_id}").status_code == 404
    assert studio.docker.calls == []
