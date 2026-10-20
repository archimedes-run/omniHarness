"""The images built MCP servers run in (Feature 006, #59).

* The **runtime image** (``omni-mcp-runtime:<version>``): ``python:3.12-slim``
  pinned by image ID, plus ``mcp``/``httpx`` and their closure copied from an
  environment ``uv`` installed from ``uv.lock`` (each file checked against its
  ``RECORD`` hash; no pip download), plus the launcher. Built once; its image
  ID is recorded, and before every use the tag must still name that ID with
  the expected label, or the build refuses (someone retagged it).
* One **code image** per code hash (``omni-mcp-built:<full sha256>``): ``FROM``
  the runtime image ID, ``COPY server.py``, a label with the hash. No ``RUN``,
  so the generated code never executes during a build. After the build its
  label is read back from the image ID, and containers run that ID, never the
  tag.

Builds use the classic builder (``DOCKER_BUILDKIT=0``, set by the runner),
``--pull=false`` and ``--network none``: probed on Docker 29.5.3, BuildKit
tried to resolve a local image ID on docker.io.
"""

from __future__ import annotations

import asyncio
import io
import json
import secrets
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path

from app.gateway.mcp_docker import DockerRunner
from app.gateway.mcp_runtime import ASSEMBLER, LAUNCHER

RUNTIME_VERSION = "1"
#: python:3.12-slim, linux/arm64, already in the local image store
#: (RepoDigest python@sha256:d764629c…). Override with mcp_builder.runtime_base_image.
DEFAULT_BASE_IMAGE = "sha256:d764629ce0ddd8c71fd371e9901efb324a95789d2315a47db7e4d27e78f1b0e9"
#: Where the packages come from when the gateway itself is not a Linux 3.12
#: environment (a bare-host gateway on macOS, the tests): the gateway image.
DEFAULT_PACKAGES_IMAGE = "omni-harness-dev-gateway:latest"
DEFAULT_PACKAGES_PYTHON = "/app/backend/.venv/bin/python"


class RuntimeImageError(RuntimeError):
    pass


def _tar(files: dict[str, bytes], extra: bytes | None = None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        if extra:
            with tarfile.open(fileobj=io.BytesIO(extra), mode="r") as src:
                for member in src.getmembers():
                    if not member.isfile() or member.name.startswith("/") or ".." in member.name.split("/"):
                        raise RuntimeImageError(f"unexpected entry in the packages tar: {member.name!r}")
                    data = src.extractfile(member)
                    tar.addfile(member, data)
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@dataclass
class RuntimeImages:
    runner: DockerRunner
    state_dir: Path
    base_image: str = DEFAULT_BASE_IMAGE
    packages_image: str = DEFAULT_PACKAGES_IMAGE
    packages_python: str = DEFAULT_PACKAGES_PYTHON
    #: Tag prefix; tests use their own so they never touch the real images.
    prefix: str = "omni-mcp-"
    #: Extra labels on every image built (tests mark theirs).
    labels: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        self._lock = asyncio.Lock()

    @property
    def runtime_tag(self) -> str:
        return f"{self.prefix}runtime:{RUNTIME_VERSION}"

    def code_tag(self, sha: str) -> str:
        return f"{self.prefix}built:{sha}"

    @property
    def _record_path(self) -> Path:
        return self.state_dir / f"{self.prefix}runtime.json"

    def _label_args(self, labels: dict[str, str]) -> list[str]:
        out: list[str] = []
        for k, v in [*labels.items(), *self.labels]:
            out += ["--label", f"{k}={v}"]
        return out

    async def _inspect(self, ref: str) -> dict | None:
        rc, out, _ = await self.runner.run(["docker", "image", "inspect", ref, "--format", "{{json .}}"], timeout=30.0)
        if rc != 0 or not out.strip():
            return None
        try:
            return json.loads(out)
        except ValueError:
            return None

    async def _packages_tar(self) -> bytes:
        """The verified packages tar, from this process if it is a Linux 3.12
        environment with the packages, else from a throwaway container."""
        if sys.platform.startswith("linux") and sys.version_info[:2] == (3, 12):
            try:
                from app.gateway.mcp_runtime import assemble_packages

                data, _ = assemble_packages.assemble()
                return data
            except ModuleNotFoundError:
                pass
        name = f"{self.prefix}pkgs-{secrets.token_hex(4)}"
        args = ["docker", "run", "--rm", "-i", "--name", name, "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges"]
        args += self._label_args({"omni.mcp.role": "packages"})
        args += [self.packages_image, self.packages_python, "-I", "-"]
        rc, out, err = await self.runner.run_bytes(args, stdin=ASSEMBLER.read_bytes(), timeout=180.0)
        if rc != 0:
            raise RuntimeImageError(f"could not read the runtime packages from {self.packages_image}: {err.strip()[:300]}")
        return out

    async def runtime_image_id(self) -> str:
        """The verified runtime image ID, building it the first time."""
        async with self._lock:
            record = None
            if self._record_path.exists():
                try:
                    record = json.loads(self._record_path.read_text())
                except ValueError:
                    record = None
            if record and record.get("version") == RUNTIME_VERSION:
                found = await self._inspect(self.runtime_tag)
                labels = ((found or {}).get("Config") or {}).get("Labels") or {}
                if found is None:
                    raise RuntimeImageError(f"the runtime image {self.runtime_tag} recorded as {record['image_id'][:19]} is gone; rebuild it deliberately")
                if found.get("Id") != record.get("image_id") or labels.get("omni.runtime_version") != RUNTIME_VERSION:
                    raise RuntimeImageError(f"{self.runtime_tag} no longer names the image recorded when it was built (retagged?); refusing to build on it")
                return record["image_id"]
            return await self._build_runtime()

    async def _build_runtime(self) -> str:
        packages = await self._packages_tar()
        try:
            with tarfile.open(fileobj=io.BytesIO(packages), mode="r") as t:
                manifest = json.loads(t.extractfile("packages.json").read())  # type: ignore[union-attr]
        except Exception as exc:
            raise RuntimeImageError(f"the packages tar has no manifest: {exc}") from exc
        if manifest.get("python") != "3.12":
            raise RuntimeImageError(f"the packages were read from Python {manifest.get('python')}, not 3.12")
        versions = manifest.get("packages") or {}
        dockerfile = (
            f"FROM {self.base_image}\n"
            "COPY site-packages/ /usr/local/lib/python3.12/site-packages/\n"
            "COPY launch.py /opt/omni/launch.py\n"
            f'LABEL omni.runtime_version="{RUNTIME_VERSION}" omni.base="{self.base_image}" '
            f'omni.packages="mcp=={versions.get("mcp", "?")} httpx=={versions.get("httpx", "?")}"\n'
        )
        context = _tar({"Dockerfile": dockerfile.encode(), "launch.py": LAUNCHER.read_bytes()}, extra=packages)
        args = ["docker", "build", "--pull=false", "--network", "none", "-t", self.runtime_tag, *self._label_args({}), "-"]
        rc, _, err = await self.runner.run(args, stdin=context, timeout=600.0)
        if rc != 0:
            raise RuntimeImageError(f"building the runtime image failed: {err.strip()[-400:]}")
        found = await self._inspect(self.runtime_tag)
        if not found:
            raise RuntimeImageError("the runtime image was built but can't be inspected")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._record_path.write_text(json.dumps({"version": RUNTIME_VERSION, "image_id": found["Id"], "base": self.base_image, "packages": versions}, indent=2))
        return found["Id"]

    async def code_image_id(self, source: str, sha: str) -> str:
        """Build (or reuse) the image for exactly this code; returns its image
        ID after checking the ID's label is *sha*."""
        import hashlib

        if hashlib.sha256(source.encode("utf-8")).hexdigest() != sha:
            raise RuntimeImageError("the code does not hash to the approved hash")
        runtime_id = await self.runtime_image_id()
        dockerfile = f'FROM {runtime_id}\nCOPY server.py /app/server.py\nLABEL omni.code_sha256="{sha}" omni.runtime_id="{runtime_id}"\n'
        context = _tar({"Dockerfile": dockerfile.encode(), "server.py": source.encode("utf-8")})
        tag = self.code_tag(sha)
        args = ["docker", "build", "--pull=false", "--network", "none", "-t", tag, *self._label_args({}), "-"]
        rc, _, err = await self.runner.run(args, stdin=context, timeout=300.0)
        if rc != 0:
            raise RuntimeImageError(f"building the server image failed: {err.strip()[-400:]}")
        found = await self._inspect(tag)
        labels = ((found or {}).get("Config") or {}).get("Labels") or {}
        if not found or labels.get("omni.code_sha256") != sha:
            raise RuntimeImageError("the built image does not carry the approved code hash")
        image_id = found["Id"]
        # Read back by ID, not tag: what runs is exactly this image.
        again = await self._inspect(image_id)
        if not again or ((again.get("Config") or {}).get("Labels") or {}).get("omni.code_sha256") != sha:
            raise RuntimeImageError("the image ID does not carry the approved code hash")
        return image_id
