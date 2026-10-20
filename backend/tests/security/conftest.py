"""The production gateway, an owner, and a second account (security baseline).

`create_app()` with its real lifespan, auth ON, real cookies from
/api/v1/auth/login/local. Every test here goes through HTTP; none calls a
handler. Reusable by the gated branches for their cross-user tests:

    def test_mine(sec):
        sec.admit_second()                 # open the door (see below)
        other = sec.login_second()
        assert other.get(f"/api/my-records/{rid}").status_code == 404

`admit_second()` flips the single seam `ownership.admits_additional_accounts`.
With the door closed (the shipped state) a second account never gets past the
middleware, so a cross-user check would pass for the wrong reason. Opening it
proves the ownership check holds on its own.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from _security_helpers import OWNER, SECOND, _with_csrf, login
from fastapi.testclient import TestClient

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-security-baseline-min-32")
EXAMPLE = Path(__file__).resolve().parents[3] / "config.example.yaml"


@pytest.fixture
def make_gateway(tmp_path, monkeypatch):
    """Build the gateway; `initialize=False` leaves it a fresh install."""
    from app.gateway.auth.config import AuthConfig, set_auth_config
    from omniharness.config.app_config import reset_app_config
    from omniharness.config.extensions_config import reset_extensions_config

    contexts = []

    def _make(*, initialize: bool = True):
        config = yaml.safe_load(EXAMPLE.read_text())
        config["database"] = {"backend": "sqlite", "sqlite_dir": str(tmp_path / "data")}
        config["policy"] = {"enabled": True, "state_dir": str(tmp_path / "policy")}
        config["trigger_engine"] = {"enabled": False}
        config["agents_api"] = {"enabled": True}
        config.setdefault("memory", {})["enabled"] = False
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
        import omniharness.config.paths as paths_mod
        from app.gateway.app import create_app
        from app.gateway.routers import auth as auth_router

        monkeypatch.setattr(deps, "_cached_local_provider", None)
        monkeypatch.setattr(deps, "_cached_repo", None)
        monkeypatch.setattr(paths_mod, "_paths", paths_mod.Paths(tmp_path / "home"))
        monkeypatch.setattr(auth_router, "_login_attempts", {})

        app = create_app()
        client = TestClient(app)
        client.__enter__()
        contexts.append(client)
        if initialize:
            resp = client.post("/api/v1/auth/initialize", json={"email": OWNER[0], "password": OWNER[1]})
            assert resp.status_code == 201, resp.text
            _with_csrf(client)
        return app, client

    yield _make
    for client in contexts:
        client.__exit__(None, None, None)
    reset_app_config()
    reset_extensions_config()


@pytest.fixture
def sec(make_gateway, monkeypatch):
    """The owner signed in, and a second account inserted directly (registration
    is closed, so the database is the only way one can exist)."""
    from app.gateway.deps import get_local_provider

    app, owner = make_gateway()
    owner_id = owner.get("/api/v1/auth/me").json()["id"]
    # On the app's own event loop: the database engine belongs to it.
    second = owner.portal.call(_create_second)
    assert get_local_provider() is not None

    def admit_second() -> None:
        monkeypatch.setattr("app.gateway.ownership.admits_additional_accounts", lambda: True)

    def login_second() -> TestClient:
        client, resp = login(app, *SECOND)
        assert resp.status_code == 200, resp.text
        return client

    return SimpleNamespace(app=app, owner=owner, owner_id=owner_id, second_id=str(second.id), admit_second=admit_second, login_second=login_second)


async def _create_second():
    from app.gateway.deps import get_local_provider

    return await get_local_provider().create_user(email=SECOND[0], password=SECOND[1], system_role="user")
