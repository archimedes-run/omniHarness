"""The dev gateway does not restart when the agent writes into its data directory.

Every hot-reloading launcher watches ``backend/``, and the agent's outputs, uploads
and custom-agent configs live in ``backend/.omni-harness``. A coding task that
wrote ``outputs/script.py`` restarted the gateway mid-run: new requests hung until
the run's stream closed. watchfiles reports absolute paths, so the exclude has to
be the absolute data directory; a relative one never matches.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest
import yaml
from uvicorn.config import Config
from uvicorn.supervisors.watchfilesreload import FileFilter

REPO = Path(__file__).resolve().parents[2]


def _compose_flags() -> tuple[str, str]:
    gateway = yaml.safe_load((REPO / "docker/docker-compose-dev.yaml").read_text())["services"]["gateway"]
    return re.search(r"uvicorn [^;]*", gateway["command"]).group(0), "/app/backend"


def _serve_flags() -> tuple[str, str]:
    text = (REPO / "scripts/serve.sh").read_text()
    return re.search(r'GATEWAY_EXTRA_FLAGS="(--reload [^"]*)"', text).group(1), "$REPO_ROOT/backend"


def _makefile_flags() -> tuple[str, str]:
    text = (REPO / "backend/Makefile").read_text()
    return re.search(r"^dev:\n\t(.*)$", text, re.M).group(1), "$(CURDIR)"


def _reload_filter(command: str, backend_root: str, backend: Path) -> FileFilter:
    args = shlex.split(command.replace(backend_root, str(backend)))
    includes = [a.split("=", 1)[1] for a in args if a.startswith("--reload-include=")]
    excludes = [a.split("=", 1)[1] for a in args if a.startswith("--reload-exclude=")]
    assert "--reload" in args, command
    return FileFilter(Config(app="app.gateway.app:app", reload=True, reload_dirs=[str(backend)], reload_includes=includes, reload_excludes=excludes))


@pytest.mark.parametrize("launcher", [_compose_flags, _serve_flags, _makefile_flags], ids=["compose-dev", "serve.sh", "backend-Makefile"])
def test_agent_writes_under_the_data_dir_do_not_reload(launcher, tmp_path, monkeypatch) -> None:
    backend = tmp_path / "backend"
    data = backend / ".omni-harness"
    data.mkdir(parents=True)  # every launcher creates it before uvicorn starts
    monkeypatch.chdir(backend)
    command, backend_root = launcher()
    reload_filter = _reload_filter(command, backend_root, backend)

    thread = data / "users/owner/threads/t1/user-data"
    for written in (thread / "outputs/first_10_primes.py", thread / "workspace/app/main.py", data / "users/owner/agents/code-reviewer/config.yaml"):
        assert not reload_filter(written), f"{launcher.__name__}: writing {written.relative_to(backend)} restarts the gateway"

    assert reload_filter(backend / "app/gateway/app.py"), "code changes must still reload"
