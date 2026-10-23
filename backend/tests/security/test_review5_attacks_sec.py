"""Fifth review: sandbox -> host-loopback lateral movement (uncommitted).

On Docker Desktop every container resolves ``host.docker.internal`` to the
host, and traffic to it reaches ports the host publishes on 127.0.0.1. The
sandbox network (``omni-harness-dev-sandboxes``) is a plain, non-internal
bridge and ``docker run`` for a sandbox does not override that name, so code
running in a sandbox reaches every loopback-published OmniHarness service:
the session-watcher (127.0.0.1:18101), nginx (127.0.0.1:2026) and every
MCP-Studio-built server (127.0.0.1:<port>), each of which ALLOWS the Host
``host.docker.internal`` and sends no Origin from a non-browser client.

These tests assert the SAFE behaviour and fail on 85f59ef.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent


def _sandbox_run_cmd(monkeypatch) -> list[str]:
    from omniharness.community.aio_sandbox import local_backend as lb

    captured: dict = {}

    class _R:
        stdout = "cid\n"
        returncode = 0
        stderr = ""

    def fake_run(cmd, *a, **k):
        captured["cmd"] = cmd
        return _R()

    monkeypatch.setenv("OMNI_HARNESS_SANDBOX_NETWORK", "omni-harness-dev-sandboxes")
    monkeypatch.setattr(lb.LocalContainerBackend, "_detect_runtime", lambda self: "docker")
    monkeypatch.setattr(lb.subprocess, "run", fake_run)
    backend = lb.LocalContainerBackend(image="img", base_port=8080, container_prefix="omni-harness-sandbox", config_mounts=[], environment={})
    backend.create("t1", "sb1")
    return captured["cmd"]


def test_sandbox_cannot_reach_host_loopback_via_host_docker_internal(monkeypatch) -> None:
    """HIGH (conditional): the sandbox network must not route to the host.

    Either the network is ``internal: true`` (Docker Desktop then gives no
    host.docker.internal route) or the sandbox's run command pins the name
    away (and blocks the raw host-gateway IP). Neither holds today.
    """
    compose = yaml.safe_load((REPO / "docker" / "docker-compose-dev.yaml").read_text())
    net = compose["networks"]["omni-harness-dev-sandboxes"]
    cmd = _sandbox_run_cmd(monkeypatch)
    pinned = any("host.docker.internal" in arg for arg in cmd)
    assert net.get("internal") is True or pinned, f"sandbox network {net} is routable to the host; docker run: {cmd}"


@pytest.fixture
def watcher(tmp_path):
    sys.path.insert(0, str(BACKEND / "packages" / "session_watcher"))
    from session_watcher.server import build_app, build_service

    (tmp_path / "projects").mkdir()
    return TestClient(build_app(build_service(tmp_path / "projects", None), token=None), base_url="http://host.docker.internal:18101")


def test_watcher_without_token_refuses_container_callers(watcher) -> None:
    """With OMNI_HARNESS_WATCHER_TOKEN unset (the user's first-boot state) a
    sandbox's ``curl http://host.docker.internal:18101/...`` is served: Host is
    allowed, no Origin is sent, no token is required. It should fail closed
    for any non-loopback Host when no token is configured."""
    r = watcher.get("/health")
    assert r.status_code in (401, 403, 421), f"served to a container caller without a token: {r.status_code} {r.text[:200]}"
    # And the MCP message route is past the guard too (400 = guard passed, missing session).
    m = watcher.post("/messages/?session_id=" + "0" * 32, json={})
    assert m.status_code in (401, 403, 421), m.status_code


@pytest.mark.xfail(strict=True, reason="[author's edit] fixed by #59 (per-server bearer token, nothing published); mcp_builder is off live")
def test_built_mcp_servers_require_a_token_from_container_callers() -> None:
    """MCP-Studio-built servers run with vault secrets as env and publish
    127.0.0.1:<port>; their patched __main__ allows Host host.docker.internal
    and has no auth. A sandbox can therefore open /sse and call their tools
    directly, outside the policy gate (no Tier 3 confirmation)."""
    from app.gateway import mcp_server_manager as m

    main = m._DOCKER_MAIN_NEW
    assert "host.docker.internal" not in main or any(w in main.lower() for w in ("token", "authorization", "bearer")), main
