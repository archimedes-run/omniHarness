#!/usr/bin/env python3

"""Runtime pre-flight checks for OmniHarness.

This is intentionally dependency-agnostic: it verifies that the local files/env
needed to boot the platform and connect services exist and look coherent.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def is_truthy_env(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def read_file_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def parse_sandbox_image_from_config(config_yaml: Path) -> str | None:
    # Very small heuristic: look for `image:` under `sandbox:` section.
    # We avoid pulling in PyYAML here.
    text = read_file_text(config_yaml)
    lines = text.splitlines()
    in_sandbox = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("sandbox:"):
            in_sandbox = True
            continue
        if in_sandbox and (stripped and not stripped.startswith("#") and not line.startswith(" ") and not line.startswith("\t")):
            # left the sandbox top-level section (non-indented root key)
            in_sandbox = False

        if not in_sandbox:
            continue

        if stripped.startswith("image:"):
            value = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            return value or None
    return None


def parse_sandbox_provider_from_config(config_yaml: Path) -> str | None:
    text = read_file_text(config_yaml)
    lines = text.splitlines()
    in_sandbox = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("sandbox:"):
            in_sandbox = True
            continue
        if in_sandbox and (stripped and not stripped.startswith("#") and not line.startswith(" ") and not line.startswith("\t")):
            in_sandbox = False
        if not in_sandbox:
            continue
        if stripped.startswith("use:"):
            value = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            return value or None
    return None


def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        subprocess.run(["docker", "info"], check=True, capture_output=True, text=True)
        return True
    except Exception:
        return False


def docker_image_exists(image: str) -> bool:
    try:
        res = subprocess.run(
            ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return False
    return image in {line.strip() for line in (res.stdout or "").splitlines() if line.strip()}


def python_import_check() -> tuple[bool, str]:
    try:
        # We just ensure the gateway can import and the omniharness package can be imported.
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import backend.app.gateway.app as a; print('ok')",
            ],
            check=True,
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        return True, "Imports OK"
    except Exception as e:
        return False, str(e)


def main() -> int:
    root = Path(__file__).resolve().parents[1]

    required_paths = [
        root / "config.yaml",
        root / ".env",
        root / "frontend" / ".env",
        root / "frontend" / "package.json",
        root / "extensions_config.json",
        root / "frontend" / "src",
    ]

    ok = True

    print("==========================================")
    print("  OmniHarness runtime-check")
    print("==========================================")
    print()

    for p in required_paths:
        if p.exists():
            print(f"  OK  {p.relative_to(root)}")
        else:
            print(f"  FAIL missing {p.relative_to(root)}")
            ok = False

    config_yaml = root / "config.yaml"
    if config_yaml.exists():
        provider = parse_sandbox_provider_from_config(config_yaml)
        image = parse_sandbox_image_from_config(config_yaml)

        if provider:
            print(f"  Sandbox provider: {provider}")
        else:
            print("  FAIL sandbox.use not found in config.yaml")
            ok = False

        sandbox_mode = "local"
        if provider and "AioSandboxProvider" in provider:
            sandbox_mode = "aio"
        elif provider and "provisioner" in provider:
            sandbox_mode = "provisioner"

        if sandbox_mode in {"aio", "provisioner"}:
            if image:
                print(f"  Sandbox image: {image}")
            else:
                print("  FAIL sandbox.image not found in config.yaml")
                ok = False

            if not docker_available():
                print("  FAIL Docker is required but not available/reachable")
                ok = False
            else:
                if image and not docker_image_exists(image):
                    print("  FAIL sandbox image not found locally (run make docker-init)")
                    ok = False

    else:
        provider = None

    # Basic gateway import sanity (does not start server).
    import_ok, import_msg = python_import_check()
    if import_ok:
        print(f"  OK  gateway import: {import_msg}")
    else:
        print(f"  FAIL gateway import: {import_msg}")
        ok = False

    logs_dir = root / "logs"
    if logs_dir.exists():
        print(f"  OK  {logs_dir.relative_to(root)}")
    else:
        print("  FAIL logs/ directory missing")
        ok = False

    print()
    if ok:
        print("==========================================")
        print("  OK Runtime pre-flight checks passed")
        print("==========================================")
        return 0

    print("==========================================")
    print("  FAIL Runtime pre-flight checks failed")
    print("==========================================")
    return 1


if __name__ == "__main__":
    sys.exit(main())
