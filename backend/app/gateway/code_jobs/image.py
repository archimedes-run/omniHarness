"""Whether the configured sandbox image can run coding jobs.

The image built from docker/sandbox carries the managed OpenCode setup and
says so in a label (`omni.opencode_version`). An older or different image
lacks it: then `code_job` is not offered and the lead keeps working with its
other tools. The answer is cached per image name and checked again after a
few minutes (a rebuilt or newly pulled image is picked up without a restart).
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time

logger = logging.getLogger(__name__)

LABEL = "omni.opencode_version"
RECHECK_SECONDS = 300.0

_lock = threading.Lock()
_cache: dict[str, tuple[float, str | None]] = {}


def configured_image() -> str:
    from omniharness.community.aio_sandbox.aio_sandbox_provider import DEFAULT_IMAGE
    from omniharness.config import get_app_config

    sandbox = getattr(get_app_config(), "sandbox", None)
    return (getattr(sandbox, "image", None) or DEFAULT_IMAGE).strip()


def _inspect(image: str) -> str | None:
    """The image's OpenCode label, or None (no such label, image or Docker)."""
    if not image or image.startswith("-"):
        return None
    try:
        out = subprocess.run(["docker", "image", "inspect", image, "--format", "{{json .Config.Labels}}"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("code jobs: cannot inspect the sandbox image %s: %s", image, exc)
        return None
    if out.returncode != 0:
        return None
    import json

    try:
        labels = json.loads(out.stdout or "null") or {}
    except json.JSONDecodeError:
        return None
    value = labels.get(LABEL) if isinstance(labels, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def opencode_version(image: str, *, now: float | None = None) -> str | None:
    now = time.monotonic() if now is None else now
    with _lock:
        hit = _cache.get(image)
        if hit and now - hit[0] < RECHECK_SECONDS:
            return hit[1]
    version = _inspect(image)
    with _lock:
        _cache[image] = (now, version)
    return version


def unsupported_reason() -> str | None:
    """None when the configured sandbox image has the managed OpenCode setup."""
    image = configured_image()
    if opencode_version(image) is None:
        return f"the sandbox image ({image}) does not have the coding worker; build it with `make sandbox-image` and set sandbox.image"
    return None


def clear_cache() -> None:
    with _lock:
        _cache.clear()
