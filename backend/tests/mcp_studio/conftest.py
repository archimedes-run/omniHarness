"""MCP Studio through the gateway as production builds it.

`create_app()` with its real lifespan and auth ON (login cookies, CSRF), on a
temporary config, database and extensions_config.json, with the MCP builder
enabled. Docker is the one thing faked: the manager's DockerRunner (#59) is
swapped for a recorder that never touches a real daemon.
"""

from __future__ import annotations

import functools
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-mcp-studio-composition-min-32")
EXAMPLE = Path(__file__).resolve().parents[3] / "config.example.yaml"

OWNER_EMAIL = "owner@example.com"
OWNER_PASSWORD = "Str0ng!Pass99"
OTHER_EMAIL = "other@example.com"
OTHER_PASSWORD = "An0ther!Pass77"


class FakeDocker:
    """Records every docker command; answers with a scripted (rc, out, err)."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.results: dict[str, tuple[int, str, str]] = {}

    async def run(self, args: list[str], *, stdin: bytes | None = None, timeout: float = 120.0) -> tuple[int, str, str]:
        self.calls.append(list(args))
        return self.results.get(args[1], (0, "", ""))

    async def run_bytes(self, args: list[str], *, stdin: bytes | None = None, timeout: float = 120.0) -> tuple[int, bytes, str]:
        rc, out, err = await self.run(args, stdin=stdin, timeout=timeout)
        return rc, out.encode(), err


class Studio(SimpleNamespace):
    def login(self, email: str, password: str) -> None:
        self.client.cookies.clear()
        self.client.headers.pop("X-CSRF-Token", None)
        resp = self.client.post("/api/v1/auth/login/local", data={"username": email, "password": password})
        assert resp.status_code == 200, resp.text
        self._csrf()

    def _csrf(self) -> None:
        csrf = self.client.cookies.get("csrf_token")
        if csrf:
            self.client.headers["X-CSRF-Token"] = csrf

    def run(self, fn, /, *args, **kwargs):
        """Run an async app-side call on the app's own event loop."""
        return self.client.portal.call(functools.partial(fn, *args, **kwargs))

    def make_server(self, name: str = "GitHub Issue Connector", *, deployed: bool = True) -> str:
        app = self.client.app
        repo = app.state.mcp_server_repo
        row = self.run(repo.create, name=name, owner_id=self.owner_id, source_code="print('x')\n")
        if deployed:
            # #59: a deployed server is one whose code was approved, by hash.
            sha = row["code_sha256"]
            self.run(repo.set_pending_approval, row["id"], {"code_sha256": sha, "egress_hosts": [], "tool_tiers": {}}, user_id=self.owner_id)
            self.run(repo.commit_approval, row["id"], expected_sha256=sha, user_id=self.owner_id)
            self.run(
                app.state.mcp_server_repo.update_container_info,
                row["id"],
                container_id="c0ffee",
                container_port=18123,
                status="deployed",
                user_id=self.owner_id,
            )
        return row["id"]

    def config_servers(self) -> dict:
        return json.loads(self.extensions.read_text()).get("mcpServers", {})

    def secret_rows(self, server_id: str) -> list[str]:
        from sqlalchemy import select

        from omniharness.persistence.engine import get_session_factory
        from omniharness.persistence.mcp_secrets.model import McpSecretRow

        async def q() -> list[str]:
            async with get_session_factory()() as session:
                return list((await session.execute(select(McpSecretRow.key_name).where(McpSecretRow.server_id == server_id))).scalars())

        return self.run(q)


@pytest.fixture
def studio(tmp_path, monkeypatch):
    from app.gateway.auth.config import AuthConfig, set_auth_config
    from omniharness.config.app_config import reset_app_config
    from omniharness.config.extensions_config import reset_extensions_config

    config = yaml.safe_load(EXAMPLE.read_text())
    config["database"] = {"backend": "sqlite", "sqlite_dir": str(tmp_path / "data")}
    config["policy"] = {"enabled": True, "state_dir": str(tmp_path / "policy")}
    config["trigger_engine"] = {"enabled": False}
    config.setdefault("memory", {})["enabled"] = False
    # #59: the vault key is a 0600 file outside the project; no startup
    # reconcile here (it would look at this machine's real Docker).
    keyfile = tmp_path / "secrets" / "mcp_vault.key"
    keyfile.parent.mkdir()
    keyfile.write_bytes(Fernet.generate_key())
    keyfile.chmod(0o600)
    config["mcp_builder"] = {"enabled": True, "vault_key_file": str(keyfile), "reconcile_on_start": False}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    extensions = tmp_path / "extensions.json"
    extensions.write_text(json.dumps({"mcpServers": {"hand-written": {"enabled": True, "type": "stdio", "command": "echo"}}, "skills": {}}))
    monkeypatch.setenv("OMNI_HARNESS_CONFIG_PATH", str(path))
    monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", str(extensions))
    monkeypatch.chdir(tmp_path)
    reset_app_config()
    reset_extensions_config()
    set_auth_config(AuthConfig(jwt_secret=os.environ["AUTH_JWT_SECRET"]))

    import app.gateway.deps as deps
    from app.gateway.app import create_app

    monkeypatch.setattr(deps, "_cached_local_provider", None)
    monkeypatch.setattr(deps, "_cached_repo", None)

    with TestClient(create_app()) as client:
        docker = FakeDocker()
        manager = client.app.state.mcp_server_manager
        assert manager is not None, "the lifespan did not wire the MCP server manager"
        manager._runner = docker

        s = Studio(client=client, docker=docker, extensions=extensions, tmp=tmp_path)
        resp = client.post("/api/v1/auth/initialize", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD})
        assert resp.status_code in (200, 201), resp.text
        s._csrf()
        s.owner_id = str(client.get("/api/v1/auth/me").json()["id"])

        # Registration is closed once the owner exists (security baseline), so
        # the second account is inserted directly, and the single-owner door is
        # opened so these tests prove the per-server ownership check itself.
        async def _other():
            return await deps.get_local_provider().create_user(email=OTHER_EMAIL, password=OTHER_PASSWORD, system_role="user")

        s.other_id = str(client.portal.call(_other).id)
        monkeypatch.setattr("app.gateway.ownership.admits_additional_accounts", lambda: True)

        s.login(OWNER_EMAIL, OWNER_PASSWORD)
        yield s
    # The lifespan registers a process-wide build controller and does not
    # clear it on shutdown; later tests expect none.
    from omniharness.runtime.mcp.controller import reset_mcp_build_controller

    reset_mcp_build_controller()
    reset_app_config()
    reset_extensions_config()
