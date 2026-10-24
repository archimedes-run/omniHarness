"""The `studio` gateway's setup, importable by name (a test cannot import
from `conftest`: every test directory has one, and the first one loaded wins).
Used by conftest.studio and by tests that restart the gateway on the same data
(test_lead_automations_owner.py)."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-studio-composition-min-32")
EXAMPLE = Path(__file__).resolve().parents[3] / "config.example.yaml"


def configure_studio(tmp_path, monkeypatch) -> None:
    """The temporary config, database, home and skills directory `studio`
    runs on. Separate so a test can start the gateway more than once on the
    same data (a restart: see test_lead_automations_owner.py)."""
    from app.gateway.auth.config import AuthConfig, set_auth_config
    from omniharness.config.app_config import reset_app_config
    from omniharness.config.extensions_config import reset_extensions_config

    config = yaml.safe_load(EXAMPLE.read_text())
    config["database"] = {"backend": "sqlite", "sqlite_dir": str(tmp_path / "data")}
    config["policy"] = {"enabled": True, "state_dir": str(tmp_path / "policy")}
    config["trigger_engine"] = {"enabled": False, "rules_path": str(tmp_path / "rules.json"), "state_dir": str(tmp_path / "triggers")}
    config["agents_api"] = {"enabled": True}
    config.setdefault("memory", {})["enabled"] = False
    config.setdefault("skills", {})["path"] = str(tmp_path / "skills")
    (tmp_path / "skills" / "public").mkdir(parents=True)
    (tmp_path / "skills" / "custom").mkdir(parents=True)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    extensions = tmp_path / "extensions.json"
    extensions.write_text('{"mcpServers": {}, "skills": {}}')
    monkeypatch.setenv("OMNI_HARNESS_CONFIG_PATH", str(path))
    monkeypatch.setenv("OMNI_HARNESS_EXTENSIONS_CONFIG_PATH", str(extensions))
    monkeypatch.setenv("OMNI_HARNESS_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    reset_app_config()
    reset_extensions_config()
    set_auth_config(AuthConfig(jwt_secret=os.environ["AUTH_JWT_SECRET"]))


def fresh_app():
    """A new `create_app()`, with the cached auth singletons dropped (they
    hold the previous app's database engine)."""
    import app.gateway.deps as deps
    from app.gateway.app import create_app

    deps._cached_local_provider = None
    deps._cached_repo = None
    return create_app()
