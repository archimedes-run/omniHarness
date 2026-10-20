"""Feature 006 app pages (MCP Suite, Settings): the gateway as production
builds it. `gateway` is the ledger suite's fixture; `builder_gateway` is the
same, with the MCP builder switched on (its vault, repo and manager wired by
the real lifespan)."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient
from ledger.conftest import gateway  # noqa: F401  (the fixture, re-exported)
from mcp_build_helpers import built  # noqa: F401  (the fixture, re-exported)

EXAMPLE = Path(__file__).resolve().parents[3] / "config.example.yaml"


def _builder_config(tmp_path, monkeypatch, *, sandbox: dict | None = None, mcp_builder_extra: dict | None = None):
    """Write the builder gateway's config (and environment) for create_app()."""
    from cryptography.fernet import Fernet

    from app.gateway.auth.config import AuthConfig, set_auth_config
    from omniharness.config.app_config import reset_app_config
    from omniharness.config.extensions_config import reset_extensions_config

    os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-ledger-composition-min-32")
    config = yaml.safe_load(EXAMPLE.read_text())
    config["database"] = {"backend": "sqlite", "sqlite_dir": str(tmp_path / "data")}
    config["policy"] = {"enabled": True, "state_dir": str(tmp_path / "policy")}
    config["trigger_engine"] = {"enabled": False}
    config.setdefault("memory", {})["enabled"] = False
    # #59: the vault key is a 0600 file outside the project; the startup
    # reconcile is off here (it would look at this machine's real Docker).
    keyfile = tmp_path / "secrets" / "mcp_vault.key"
    keyfile.parent.mkdir()
    keyfile.write_bytes(Fernet.generate_key())
    keyfile.chmod(0o600)
    config["mcp_builder"] = {"enabled": True, "vault_key_file": str(keyfile), "reconcile_on_start": False, **(mcp_builder_extra or {})}
    if sandbox:
        config.setdefault("sandbox", {}).update(sandbox)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    extensions = tmp_path / "extensions.json"
    extensions.write_text('{"mcpServers": {}, "skills": {}}')
    monkeypatch.setenv("OMNI_HARNESS_CONFIG_PATH", str(path))
    monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", str(extensions))
    monkeypatch.chdir(tmp_path)
    reset_app_config()
    reset_extensions_config()
    set_auth_config(AuthConfig(jwt_secret=os.environ["AUTH_JWT_SECRET"]))

    import app.gateway.deps as deps

    monkeypatch.setattr(deps, "_cached_local_provider", None)
    monkeypatch.setattr(deps, "_cached_repo", None)
    return extensions


@pytest.fixture
def builder_gateway_factory(tmp_path, monkeypatch):
    """Start (and stop) a builder gateway with config overrides; startup
    errors propagate, so a refusal to start can be asserted."""
    from fastapi.testclient import TestClient as _Client

    from app.gateway.app import create_app
    from omniharness.config.app_config import reset_app_config
    from omniharness.config.extensions_config import reset_extensions_config

    def start(**overrides):
        _builder_config(tmp_path, monkeypatch, **overrides)
        try:
            with _Client(create_app()):
                pass
        finally:
            from omniharness.runtime.mcp.controller import set_mcp_build_controller

            set_mcp_build_controller(None)
            reset_app_config()
            reset_extensions_config()

    return start


@pytest.fixture
def builder_gateway(tmp_path, monkeypatch):
    from app.gateway.app import create_app
    from omniharness.config.app_config import reset_app_config
    from omniharness.config.extensions_config import reset_extensions_config

    extensions = _builder_config(tmp_path, monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        resp = client.post("/api/v1/auth/initialize", json={"email": "owner@example.com", "password": "Str0ng!Pass99"})
        assert resp.status_code in (200, 201), resp.text
        csrf = client.cookies.get("csrf_token")
        if csrf:
            client.headers["X-CSRF-Token"] = csrf
        me = client.get("/api/v1/auth/me").json()
        assert app.state.mcp_server_manager is not None, "the lifespan did not wire the MCP builder"
        yield SimpleNamespace(client=client, app=app, user_id=str(me.get("id") or me.get("user", {}).get("id")), tmp=tmp_path, extensions=extensions)
    from omniharness.runtime.mcp.controller import set_mcp_build_controller

    # The lifespan registers a process-wide controller; leave none behind.
    set_mcp_build_controller(None)
    reset_app_config()
    reset_extensions_config()


# ---------------------------------------------------------------------------
# Docker (#59): throwaway, labelled, no mounts, removed, and listed.
# ---------------------------------------------------------------------------

_LEDGER = None


@pytest.fixture(scope="session")
def docker_ledger():
    from docker_ledger import LedgerRunner, docker_available

    global _LEDGER
    if not docker_available():
        pytest.skip("Docker is not available here: the container tests did not run (skipped, not passed)")
    _LEDGER = LedgerRunner()
    yield _LEDGER
    leftovers = _LEDGER.cleanup()
    _LEDGER.report()
    assert not leftovers, f"Docker resources were left behind (now removed): {leftovers}"
    assert not _LEDGER.mount_problems, f"a test container had mounts: {_LEDGER.mount_problems}"


@pytest.fixture(scope="session")
def runtime_images(docker_ledger, tmp_path_factory):
    from docker_ledger import LABEL, PREFIX

    from app.gateway.mcp_runtime_image import RuntimeImages

    return RuntimeImages(docker_ledger, state_dir=tmp_path_factory.mktemp("mcp-runtime"), prefix=PREFIX, labels=(LABEL,))


def pytest_terminal_summary(terminalreporter):
    if _LEDGER is None:
        return
    rows = _LEDGER.report()
    terminalreporter.section("Docker resources created by the MCP build tests (#59)")
    for r in rows:
        terminalreporter.write_line(f"{r['kind']:9} {r['name']:70} mounts={r['mounts']} created={r['created']} removed={r['removed']}")
    terminalreporter.write_line(f"{len(rows)} resource(s); leftovers removed and failed; mount problems: {len(_LEDGER.mount_problems)}")
