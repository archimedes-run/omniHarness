"""The deploy as argv (#59), through `create_app()`, Docker faked by the
recording runner: T9 (no secret on any argv, no port but 127.0.0.1, the
production configs keep their protections), T12 (delete removes what runs),
T16 (secret names that would steer the proxy or interpreter are refused),
T19 (unapproved code never gets real secrets), and T17u (the renderer).
"""

from __future__ import annotations

import asyncio
import json

import pytest
from mcp_build_helpers import CODE_V2, enable, server, submit, wait_for

from app.gateway.mcp_egress_config import EgressConfigError, allowlist_hosts, render_dnsmasq, render_squid

SECRET = "ghp_THEREALVALUE0123456789abcdefXYZ"


def _store(gw, sid):
    r = gw.client.put(f"/api/mcp-studio/servers/{sid}/secrets", json={"secrets": {"GITHUB_TOKEN": SECRET}})
    assert r.status_code == 200, r.text


def test_t9_no_secret_on_argv_and_only_127_0_0_1(built) -> None:
    gw, sid, runner, _ = built
    _store(gw, sid)
    assert enable(gw, sid).status_code == 200
    assert wait_for(gw, sid, {"enabled", "turn_on_failed"})["state"] == "enabled"
    argv = [" ".join(c.args) for c in runner.calls]
    assert not any(SECRET in a for a in argv), "a secret reached a docker argument"
    assert not any("-e GITHUB_TOKEN" in a or "--env-file" in a for a in argv)
    server_run = next(c.args for c in runner.calls if c.args[1] == "run" and "omni.mcp.role=server" in c.args)
    assert "-p" not in server_run and "--network" in server_run
    assert server_run[server_run.index("--network") + 1].startswith("omni-mcp-net-")
    sidecar = next(c.args for c in runner.calls if c.args[1] == "create")
    published = [sidecar[i + 1] for i, a in enumerate(sidecar) if a == "-p"]
    assert published and all(p.startswith("127.0.0.1:") for p in published), published
    # The values went over stdin, into files; the production configs keep their protections.
    files = {c.args[-1].rsplit("/", 1)[-1]: (c.stdin or b"").decode() for c in runner.calls if c.args[1] == "exec" and c.stdin}
    assert SECRET in files["secrets"] and "HTTPS_PROXY=http://mcp:" in files["secrets"]
    assert "stop-dns-rebind" in files["dnsmasq.conf"] and "server=127.0.0.11" in files["dnsmasq.conf"]
    assert "http_access deny fwd private_dst" in files["squid.conf"]
    # The endpoint token is in the vault and the squid.conf, never in the config file.
    token = gw.client.portal.call(lambda: gw.app.state.mcp_server_manager.inbound_token(sid))
    assert token and token in files["squid.conf"]
    assert token not in gw.extensions.read_text()
    entry = json.loads(gw.extensions.read_text())["mcpServers"][f"built__{server(gw, sid)['name']}"]
    assert entry["auth"] == "built-server-token" and entry["url"].startswith("http://127.0.0.1:")


def test_t12_delete_removes_containers_networks_and_entry(built) -> None:
    gw, sid, runner, _ = built
    assert enable(gw, sid).status_code == 200
    s = wait_for(gw, sid, {"enabled"})
    key = f"built__{s['name']}"
    assert key in json.loads(gw.extensions.read_text())["mcpServers"]
    runner.calls.clear()
    assert gw.client.delete(f"/api/mcp-studio/servers/{sid}").status_code == 204
    removed = [" ".join(c.args[1:]) for c in runner.calls]
    for name in (f"rm -f omni-mcp-{sid[:12]}", f"rm -f omni-mcp-egress-{sid[:12]}", f"network rm omni-mcp-net-{sid[:12]}", f"network rm omni-mcp-pub-{sid[:12]}"):
        assert name in removed, (name, removed)
    assert key not in json.loads(gw.extensions.read_text())["mcpServers"]


@pytest.mark.parametrize("name", ["HTTPS_PROXY", "LD_PRELOAD", "MCP_PORT", "__INBOUND_TOKEN", "PYTHONPATH", "bad name"])
def test_t16_reserved_secret_names_are_refused(built, name) -> None:
    gw, sid, _, _ = built
    r = gw.client.put(f"/api/mcp-studio/servers/{sid}/secrets", json={"secrets": {name: "x"}})
    assert r.status_code == 400, r.text


def test_t16_a_value_with_a_line_break_is_refused(built) -> None:
    gw, sid, _, _ = built
    r = gw.client.put(f"/api/mcp-studio/servers/{sid}/secrets", json={"secrets": {"GITHUB_TOKEN": "a\nHTTPS_PROXY=http://evil"}})
    assert r.status_code == 400, r.text


def test_t19_unapproved_code_never_gets_real_secrets(built) -> None:
    gw, sid, runner, manager = built
    _store(gw, sid)
    assert enable(gw, sid).status_code == 200
    wait_for(gw, sid, {"enabled"})
    old_runs = len(runner.ran())
    submit(gw, sid, CODE_V2)  # the agent changes the code
    s = server(gw, sid)
    assert s["state"] == "awaiting_approval" and s["approved"] is False
    assert s["state_reason"] == "New code is waiting for your approval; the approved version is still on"
    row = gw.client.portal.call(lambda: gw.app.state.mcp_server_repo.get(sid, user_id=gw.user_id))
    with pytest.raises(PermissionError, match="only for approved code"):
        gw.client.portal.call(lambda: manager._secrets_for_deploy(row, gw.user_id, row["code_sha256"]))
    assert gw.client.post(f"/api/mcp-studio/servers/{sid}/deploy").status_code == 403
    assert len(runner.ran()) == old_runs, "nothing new ran"
    # The approved version may still get them (e.g. after a restart).
    values = gw.client.portal.call(lambda: manager._secrets_for_deploy(row, gw.user_id, row["approved_code_sha256"]))
    assert values == {"GITHUB_TOKEN": SECRET}


def test_t17u_the_renderer_refuses_what_it_cannot_promise() -> None:
    assert allowlist_hosts(["API.GitHub.com.", "api.github.com"]) == ["api.github.com"]
    for bad in ["*.github.com", "1.2.3.4", "::1", "api.github.com:443", "аpi.github.com", "user@x.com", "localhost", "2130706433"]:
        with pytest.raises(EgressConfigError):
            allowlist_hosts([bad])
    with pytest.raises(EgressConfigError):
        render_squid(hosts=["a.com"], internal_ip="10.0.0.2", upstream_ip="10.0.0.3", token="not hex!")
    conf = render_squid(hosts=["a.com"], internal_ip="10.0.0.2", upstream_ip="10.0.0.3", token="ab" * 24)
    assert "acl allowed dstdomain -n a.com" in conf and "ssl_bump terminate all" in conf
    assert "stop-dns-rebind" in render_dnsmasq()
    _ = asyncio  # (kept: the suite's other files share this import pattern)
