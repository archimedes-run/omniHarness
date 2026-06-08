"""Regression tests for docker sandbox mode detection logic."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from shutil import which

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "docker.sh"
BASH_CANDIDATES = [
    Path(r"C:\Program Files\Git\bin\bash.exe"),
    Path(which("bash")) if which("bash") else None,
]
BASH_EXECUTABLE = next(
    (str(path) for path in BASH_CANDIDATES if path is not None and path.exists() and "WindowsApps" not in str(path)),
    None,
)

if BASH_EXECUTABLE is None:
    pytestmark = pytest.mark.skip(reason="bash is required for docker.sh detection tests")


def _detect_mode_with_config(config_content: str) -> str:
    """Write config content into a temp project root and execute detect_sandbox_mode."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        (tmp_root / "config.yaml").write_text(config_content, encoding="utf-8")

        command = f"source '{SCRIPT_PATH}' && PROJECT_ROOT='{tmp_root}' && detect_sandbox_mode"

        output = subprocess.check_output(
            [BASH_EXECUTABLE, "-lc", command],
            text=True,
            encoding="utf-8",
        ).strip()

        return output


def _detect_image_with_config(config_content: str, *, env_image: str | None = None) -> str:
    """Write config content into a temp project root and execute detect_sandbox_image."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        (tmp_root / "config.yaml").write_text(config_content, encoding="utf-8")

        env_prefix = f"SANDBOX_IMAGE='{env_image}' " if env_image else ""
        command = f"source '{SCRIPT_PATH}' && PROJECT_ROOT='{tmp_root}' && {env_prefix}detect_sandbox_image"

        output = subprocess.check_output(
            [BASH_EXECUTABLE, "-lc", command],
            text=True,
            encoding="utf-8",
        ).strip()

        return output


def _detect_image_without_config() -> str:
    """Execute detect_sandbox_image in a temp project without config.yaml."""
    with tempfile.TemporaryDirectory() as tmpdir:
        command = f"source '{SCRIPT_PATH}' && PROJECT_ROOT='{tmpdir}' && detect_sandbox_image"
        output = subprocess.check_output(
            [BASH_EXECUTABLE, "-lc", command],
            text=True,
            encoding="utf-8",
        ).strip()

        return output


def test_detect_mode_defaults_to_local_when_config_missing():
    """No config file should default to local mode."""
    with tempfile.TemporaryDirectory() as tmpdir:
        command = f"source '{SCRIPT_PATH}' && PROJECT_ROOT='{tmpdir}' && detect_sandbox_mode"
        output = subprocess.check_output(
            [BASH_EXECUTABLE, "-lc", command],
            text=True,
            encoding="utf-8",
        ).strip()

    assert output == "local"


def test_detect_mode_local_provider():
    """Local sandbox provider should map to local mode."""
    config = """
sandbox:
  use: omniharness.sandbox.local:LocalSandboxProvider
""".strip()

    assert _detect_mode_with_config(config) == "local"


def test_detect_sandbox_image_reads_configured_aio_image():
    """A configured sandbox.image should be used by docker-init."""
    config = """
sandbox:
  use: omniharness.community.aio_sandbox:AioSandboxProvider
  image: omni-harness-sandbox:latest
""".strip()

    assert _detect_image_with_config(config) == "omni-harness-sandbox:latest"


def test_detect_sandbox_image_env_overrides_config():
    """SANDBOX_IMAGE should keep highest precedence for custom mirrors."""
    config = """
sandbox:
  use: omniharness.community.aio_sandbox:AioSandboxProvider
  image: omni-harness-sandbox:latest
""".strip()

    assert _detect_image_with_config(config, env_image="registry.example/sandbox:test") == "registry.example/sandbox:test"


def test_detect_sandbox_image_defaults_when_missing():
    """Missing sandbox.image should fall back to the repository default image."""
    config = """
sandbox:
  use: omniharness.community.aio_sandbox:AioSandboxProvider
""".strip()

    assert _detect_image_with_config(config) == "ghcr.io/archimedes-run/omni-harness-sandbox:latest"


def test_detect_sandbox_image_defaults_without_config():
    """No config file should use the repository default image."""
    assert _detect_image_without_config() == "ghcr.io/archimedes-run/omni-harness-sandbox:latest"


def test_detect_sandbox_image_ignores_commented_image():
    """Commented image lines should not be treated as configuration."""
    config = """
sandbox:
  use: omniharness.community.aio_sandbox:AioSandboxProvider
  # image: omni-harness-sandbox:latest
""".strip()

    assert _detect_image_with_config(config) == "ghcr.io/archimedes-run/omni-harness-sandbox:latest"


def test_detect_mode_aio_without_provisioner_url():
    """AIO sandbox without provisioner_url should map to aio mode."""
    config = """
sandbox:
  use: omniharness.community.aio_sandbox:AioSandboxProvider
""".strip()

    assert _detect_mode_with_config(config) == "aio"


def test_detect_mode_provisioner_with_url():
    """AIO sandbox with provisioner_url should map to provisioner mode."""
    config = """
sandbox:
  use: omniharness.community.aio_sandbox:AioSandboxProvider
  provisioner_url: http://provisioner:8002
""".strip()

    assert _detect_mode_with_config(config) == "provisioner"


def test_detect_mode_ignores_commented_provisioner_url():
    """Commented provisioner_url should not activate provisioner mode."""
    config = """
sandbox:
  use: omniharness.community.aio_sandbox:AioSandboxProvider
  # provisioner_url: http://provisioner:8002
""".strip()

    assert _detect_mode_with_config(config) == "aio"


def test_detect_mode_unknown_provider_falls_back_to_local():
    """Unknown sandbox provider should default to local mode."""
    config = """
sandbox:
  use: custom.module:UnknownProvider
""".strip()

    assert _detect_mode_with_config(config) == "local"
