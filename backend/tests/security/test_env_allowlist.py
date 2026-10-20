"""The gateway container receives only the env keys its features read.

No compose service loads the repo .env wholesale (env_file: ../.env); the
gateway's `environment:` names exactly secret_usage.GATEWAY_ENV_KEYS, as bare
names (passed only when set, never as ""). `make env-check` names .env keys
that reach no container.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
COMPOSES = ("docker/docker-compose.yaml", "docker/docker-compose-dev.yaml", "docker/docker-compose-daily.yaml")


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_multi_constructor(
    "!", lambda loader, suffix, node: loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode) else loader.construct_mapping(node) if isinstance(node, yaml.MappingNode) else loader.construct_scalar(node)
)


def _services(compose: str) -> dict:
    return (yaml.load((REPO / compose).read_text(), Loader=_Loader) or {}).get("services") or {}  # noqa: S506


@pytest.mark.parametrize("compose", COMPOSES)
def test_no_service_loads_the_repo_env_file(compose) -> None:
    for name, svc in _services(compose).items():
        files = (svc or {}).get("env_file") or []
        files = [files] if isinstance(files, str) else files
        for f in files:
            path = f.get("path") if isinstance(f, dict) else f
            assert not re.fullmatch(r"(\.\./)?\.env", str(path)), f"{compose}: {name} loads the whole repo .env ({path})"


@pytest.mark.parametrize("compose", COMPOSES[:2])
def test_the_gateway_passes_exactly_the_registry(compose) -> None:
    from app.gateway.secret_usage import GATEWAY_ENV_KEYS

    env = _services(compose)["gateway"]["environment"]
    bare = {entry for entry in env if isinstance(entry, str) and "=" not in entry}
    assert bare == set(GATEWAY_ENV_KEYS), {"missing": sorted(set(GATEWAY_ENV_KEYS) - bare), "extra": sorted(bare - set(GATEWAY_ENV_KEYS))}


def test_rendered_gateway_environment_never_contains_an_unlisted_key(tmp_path) -> None:
    """`docker compose config` (read-only) on a temp .env with a dummy key."""
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker CLI not installed: the rendered environment is NOT checked")
    (tmp_path / "docker").mkdir()
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / ".env").write_text("")
    shutil.copy(REPO / "docker/docker-compose.yaml", tmp_path / "docker/docker-compose.yaml")
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-dummy-listed\nDUMMY_UNLISTED_KEY=dummy-unlisted-value\n")
    import os

    # The real HOME and PATH (the compose CLI plugin lives under ~/.docker), and
    # nothing else of this process's environment.
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", str(tmp_path)),
        "OMNI_HARNESS_CONFIG_PATH": "/x/c.yaml",
        "OMNI_HARNESS_EXTENSIONS_CONFIG_PATH": "/x/e.json",
        "OMNI_HARNESS_HOME": "/x/h",
        "OMNI_HARNESS_DOCKER_SOCKET": "/var/run/docker.sock",
    }
    try:
        out = subprocess.run([docker, "compose", "--env-file", str(tmp_path / ".env"), "-f", "docker-compose.yaml", "config", "--format", "json"], cwd=tmp_path / "docker", env=env, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"docker compose not usable ({exc}): the rendered environment is NOT checked")
    if out.returncode != 0:
        pytest.skip(f"docker compose config failed ({out.stderr.strip()[:160]}): the rendered environment is NOT checked")
    gateway_env = json.loads(out.stdout)["services"]["gateway"]["environment"]
    assert "DUMMY_UNLISTED_KEY" not in gateway_env
    assert "dummy-unlisted-value" not in json.dumps(gateway_env)
    assert gateway_env.get("OPENAI_API_KEY") == "sk-dummy-listed"


def test_make_env_check_names_keys_no_container_gets(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=sk-listed-value\nDUMMY_UNLISTED_KEY=never-print-this-value\nBETTER_AUTH_SECRET=frontend-value\n")
    out = subprocess.run([sys.executable, "-m", "app.gateway.secret_usage", str(env_file)], cwd=BACKEND, env={"PYTHONPATH": str(BACKEND), "PATH": "/usr/bin:/bin"}, capture_output=True, text=True, timeout=60)
    assert "DUMMY_UNLISTED_KEY" in out.stdout, out.stdout + out.stderr
    assert "OPENAI_API_KEY" not in out.stdout and "BETTER_AUTH_SECRET" not in out.stdout
    assert "never-print-this-value" not in out.stdout + out.stderr
