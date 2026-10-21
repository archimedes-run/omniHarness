"""Every HTTP service we run on loopback refuses a foreign Host (DNS rebinding).

A web page can point its own name at 127.0.0.1 and then talk to anything on
loopback as same-origin. Each service therefore answers only the Host names
it is actually reached by, refuses any browser Origin, and (session-watcher)
requires the shared token when one is configured.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture
def watcher(tmp_path):
    sys.path.insert(0, str(BACKEND / "packages" / "session_watcher"))
    from session_watcher.server import build_app, build_service

    (tmp_path / "projects").mkdir()

    def make(token="watcher-secret-123", host="127.0.0.1:18101"):
        client = TestClient(build_app(build_service(tmp_path / "projects", None), token=token), base_url=f"http://{host}")
        if token:
            client.headers["X-OmniHarness-Watcher-Token"] = token
        return client

    return make


@pytest.mark.parametrize("host", ["127.0.0.1:18101", "localhost:18101", "host.docker.internal:18101", "session-watcher:18101"])
def test_the_watcher_answers_its_own_hosts(watcher, host) -> None:
    assert watcher(host=host).get("/health").status_code == 200


@pytest.mark.parametrize("path,method", [("/health", "get"), ("/sse", "get"), ("/messages/?session_id=" + "0" * 32, "post")])
def test_the_watcher_refuses_a_rebound_host_and_any_origin(watcher, path, method) -> None:
    assert getattr(watcher(host="evil-rebind.example:18101"), method)(path).status_code == 421
    assert getattr(watcher(), method)(path, headers={"Origin": "http://127.0.0.1:18101"}).status_code == 403


def test_the_watcher_requires_the_shared_token(watcher) -> None:
    client = watcher(token="watcher-secret-123")
    client.headers.pop("X-OmniHarness-Watcher-Token")
    assert client.get("/health").status_code == 401
    assert client.get("/health", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/health", headers={"X-OmniHarness-Watcher-Token": "watcher-secret-123"}).status_code == 200
    assert client.get("/health", headers={"Authorization": "Bearer watcher-secret-123"}).status_code == 200


def test_the_gateway_refuses_a_foreign_host(make_gateway, monkeypatch) -> None:
    app, owner = make_gateway()
    evil = TestClient(app, base_url="http://evil-rebind.example:2026")
    assert evil.get("/health").status_code == 421
    assert evil.post("/api/v1/auth/login/local", data={"username": "x", "password": "y"}).status_code == 421
    for host in ("localhost:2026", "127.0.0.1:8001", "gateway:8001"):
        assert TestClient(app, base_url=f"http://{host}").get("/health").status_code == 200, host


def test_a_lan_name_is_served_only_when_configured() -> None:
    from app.gateway.config import allowed_hosts

    assert "my-mac.lan" not in allowed_hosts({})
    assert "my-mac.lan" in allowed_hosts({"GATEWAY_ALLOWED_HOSTS": "my-mac.lan"})


def test_built_mcp_servers_keep_rebinding_protection() -> None:
    from app.gateway.mcp_server_manager import _DOCKER_MAIN_NEW

    assert "transport_security = None" not in _DOCKER_MAIN_NEW
    assert "enable_dns_rebinding_protection=True" in _DOCKER_MAIN_NEW
    assert "allowed_origins=[]" in _DOCKER_MAIN_NEW
    ns: dict = {}
    exec(compile(_DOCKER_MAIN_NEW.replace('if __name__ == "__main__":', "if False:"), "<main>", "exec"), ns)  # it parses


def test_the_composio_stdio_server_gets_no_gateway_secrets(monkeypatch) -> None:
    from omniharness.tools.connector_tools import _build_stdio_spec

    monkeypatch.setenv("OMNI_HARNESS_INTERNAL_AUTH_TOKEN", "internal-xyz")
    monkeypatch.setenv("AUTH_JWT_SECRET", "jwt-xyz")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-xyz")
    env = _build_stdio_spec("gmail", "acct", "user", "composio-key")["env"]
    assert env["COMPOSIO_API_KEY"] == "composio-key" and env["COMPOSIO_TOOLKIT"] == "GMAIL"
    for leaked in ("OMNI_HARNESS_INTERNAL_AUTH_TOKEN", "AUTH_JWT_SECRET", "OPENAI_API_KEY"):
        assert leaked not in env
    assert "PATH" in env


def test_no_subprocess_environment_is_copied_whole() -> None:
    """Only the scrubber itself may start from the full environment."""
    import re

    allowed = {"packages/harness/omniharness/utils/safe_env.py", "app/tools/openclaude.py"}
    found = set()
    for root in ("app", "packages"):
        for path in (BACKEND / root).rglob("*.py"):
            if "tests" in path.parts:
                continue
            if re.search(r"\*\*os\.environ|dict\(os\.environ|os\.environ\.copy\(\)", path.read_text(errors="ignore")):
                found.add(path.relative_to(BACKEND).as_posix())
    assert found <= allowed, sorted(found - allowed)


def test_a_watcher_with_no_token_refuses_everything(watcher) -> None:
    """There is no unauthenticated mode: no token configured, every request 401."""
    client = watcher(token=None)
    assert client.get("/health").status_code == 401
    assert client.get("/health", headers={"X-OmniHarness-Watcher-Token": "anything"}).status_code == 401


def test_the_gateway_sends_the_token_to_the_watcher_from_the_mounted_file(tmp_path, monkeypatch) -> None:
    from omniharness.config.extensions_config import McpServerConfig
    from omniharness.mcp.client import build_server_params
    from omniharness.mcp.watcher_token import ensure_watcher_token

    token_file = tmp_path / "secrets" / "watcher.token"
    monkeypatch.setenv("OMNI_HARNESS_WATCHER_TOKEN_FILE", str(token_file))
    token = ensure_watcher_token()
    assert oct(token_file.stat().st_mode & 0o777) == "0o600" and oct(token_file.parent.stat().st_mode & 0o777) == "0o700"
    params = build_server_params("session-watcher", McpServerConfig(enabled=True, type="sse", url="http://host.docker.internal:18101/sse"))
    assert params["headers"]["X-OmniHarness-Watcher-Token"] == token
    other = build_server_params("github", McpServerConfig(enabled=True, type="sse", url="http://example/sse"))
    assert "X-OmniHarness-Watcher-Token" not in (other.get("headers") or {})


def test_the_token_file_is_created_once_private_and_mounted_read_only(tmp_path) -> None:
    import subprocess

    import yaml

    repo = BACKEND.parent
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "OMNI_HARNESS_SECRETS_DIR": str(tmp_path / "s")}
    subprocess.run(["sh", str(repo / "scripts/ensure-watcher-token.sh")], env=env, check=True, timeout=30)
    token_file = tmp_path / "s" / "watcher.token"
    first = token_file.read_text()
    assert len(first.strip()) >= 40
    assert oct(token_file.stat().st_mode & 0o777) == "0o600" and oct(token_file.parent.stat().st_mode & 0o777) == "0o700"
    subprocess.run(["sh", str(repo / "scripts/ensure-watcher-token.sh")], env=env, check=True, timeout=30)
    assert token_file.read_text() == first, "an existing token is kept"
    for compose in ("docker/docker-compose.yaml", "docker/docker-compose-dev.yaml"):
        services = yaml.safe_load((repo / compose).read_text())["services"]
        for name in ("session-watcher", "gateway"):
            svc = services[name]
            assert any(str(v).endswith("watcher.token:/run/secrets/watcher.token:ro") for v in svc["volumes"]), (compose, name)
            assert "OMNI_HARNESS_WATCHER_TOKEN_FILE=/run/secrets/watcher.token" in svc["environment"], (compose, name)
    for script in ("Makefile", "scripts/deploy.sh", "scripts/docker.sh", "scripts/serve.sh"):
        assert "ensure-watcher-token.sh" in (repo / script).read_text(), script


def test_sandboxes_have_no_route_to_the_host() -> None:
    """Two layers, each checked: the network is internal, and Docker Desktop's
    host names are pinned away inside every sandbox."""
    import yaml

    repo = BACKEND.parent
    for compose, net in (("docker/docker-compose.yaml", "omni-harness-sandboxes"), ("docker/docker-compose-dev.yaml", "omni-harness-dev-sandboxes")):
        assert yaml.safe_load((repo / compose).read_text())["networks"][net].get("internal") is True, compose


def test_sandbox_runs_pin_the_host_names_away(monkeypatch) -> None:
    from types import SimpleNamespace

    from omniharness.community.aio_sandbox import local_backend as lb

    calls = []
    monkeypatch.setattr(lb.subprocess, "run", lambda cmd, **k: calls.append(cmd) or SimpleNamespace(stdout="cid\n", stderr="", returncode=0))
    backend = lb.LocalContainerBackend(image="img", base_port=8080, container_prefix="omni-harness-sandbox", config_mounts=[], environment={})
    backend._runtime = "docker"
    backend._start_container("omni-harness-sandbox-x", "omni-harness-sandboxes")
    cmd = calls[-1]
    pins = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--add-host"]
    assert "host.docker.internal:0.0.0.0" in pins and "gateway.docker.internal:0.0.0.0" in pins, cmd
