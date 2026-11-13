"""Local container backend for sandbox provisioning.

Manages sandbox containers using Docker or Apple Container on the local machine.
Handles container lifecycle, port allocation, and cross-process container discovery.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
from datetime import datetime

from .backend import SandboxBackend, wait_for_sandbox_ready
from .sandbox_auth import CONTAINER_ENV as SANDBOX_KEY_ENV
from .sandbox_auth import auth_headers, sandbox_api_key
from .sandbox_info import SandboxInfo

logger = logging.getLogger(__name__)


def _parse_docker_timestamp(raw: str) -> float:
    """Parse Docker's ISO 8601 timestamp into a Unix epoch float.

    Docker returns timestamps with nanosecond precision and a trailing ``Z``
    (e.g. ``2026-04-08T01:22:50.123456789Z``).  Python's ``fromisoformat``
    accepts at most microseconds and (pre-3.11) does not accept ``Z``, so the
    string is normalized before parsing.  Returns ``0.0`` on empty input or
    parse failure so callers can use ``0.0`` as a sentinel for "unknown age".
    """
    if not raw:
        return 0.0
    try:
        s = raw.strip()
        if "." in s:
            dot_pos = s.index(".")
            tz_start = dot_pos + 1
            while tz_start < len(s) and s[tz_start].isdigit():
                tz_start += 1
            frac = s[dot_pos + 1 : tz_start][:6]  # truncate to microseconds
            tz_suffix = s[tz_start:]
            s = s[: dot_pos + 1] + frac + tz_suffix
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).timestamp()
    except (ValueError, TypeError) as e:
        logger.debug(f"Could not parse docker timestamp {raw!r}: {e}")
        return 0.0


def _extract_host_port(inspect_entry: dict, container_port: int) -> int | None:
    """Extract the host port mapped to ``container_port/tcp`` from a docker inspect entry.

    Returns None if the container has no port mapping for that port.
    """
    try:
        ports = (inspect_entry.get("NetworkSettings") or {}).get("Ports") or {}
        bindings = ports.get(f"{container_port}/tcp") or []
        if bindings:
            host_port = bindings[0].get("HostPort")
            if host_port:
                return int(host_port)
    except (ValueError, TypeError, AttributeError):
        pass
    return None


def _format_container_mount(runtime: str, host_path: str, container_path: str, read_only: bool) -> list[str]:
    """Format a bind-mount argument for the selected runtime.

    Docker's ``-v host:container`` syntax is ambiguous for Windows drive-letter
    paths like ``D:/...`` because ``:`` is both the drive separator and the
    volume separator. Use ``--mount type=bind,...`` for Docker to avoid that
    parsing ambiguity. Apple Container keeps using ``-v``.
    """
    if runtime == "docker":
        mount_spec = f"type=bind,src={host_path},dst={container_path}"
        if read_only:
            mount_spec += ",readonly"
        return ["--mount", mount_spec]

    mount_spec = f"{host_path}:{container_path}"
    if read_only:
        mount_spec += ":ro"
    return ["-v", mount_spec]


def _redact_container_command_for_log(cmd: list[str]) -> list[str]:
    """Return a Docker/Container command with environment values redacted."""
    redacted: list[str] = []
    redact_next_env = False

    for arg in cmd:
        if redact_next_env:
            if "=" in arg:
                key = arg.split("=", 1)[0]
                redacted.append(f"{key}=<redacted>" if key else "<redacted>")
            else:
                redacted.append(arg)
            redact_next_env = False
            continue

        if arg in {"-e", "--env"}:
            redacted.append(arg)
            redact_next_env = True
            continue

        if arg.startswith("--env="):
            value = arg.removeprefix("--env=")
            if "=" in value:
                key = value.split("=", 1)[0]
                redacted.append(f"--env={key}=<redacted>" if key else "--env=<redacted>")
            else:
                redacted.append(arg)
            continue

        redacted.append(arg)

    return redacted


def _format_container_command_for_log(cmd: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(cmd)
    return shlex.join(cmd)


#: The user-defined Docker network the sandboxes share with the gateway
#: (docker compose sets it). Sandboxes publish NO host port: the gateway reaches
#: them as http://<container-name>:8080 on this network, and nothing on the host
#: or in a browser can reach their shell-exec API at all.
SANDBOX_NETWORK_ENV = "OMNI_HARNESS_SANDBOX_NETWORK"
SANDBOX_API_PORT = 8080

#: The sandboxes' only way out (docker/sandbox-egress): package registries,
#: GET/HEAD, port 443. Compose sets both; without them a sandbox has no egress.
SANDBOX_EGRESS_PROXY_ENV = "OMNI_HARNESS_SANDBOX_EGRESS_PROXY"
SANDBOX_EGRESS_CA_VOLUME_ENV = "OMNI_HARNESS_SANDBOX_EGRESS_CA_VOLUME"
SANDBOX_EGRESS_CA_DIR = "/etc/omni-egress"


def sandbox_egress() -> tuple[str, str] | None:
    proxy = os.environ.get(SANDBOX_EGRESS_PROXY_ENV, "").strip()
    volume = os.environ.get(SANDBOX_EGRESS_CA_VOLUME_ENV, "").strip()
    return (proxy, volume) if proxy and volume else None


def _egress_args(egress: tuple[str, str] | None) -> list[str]:
    if egress is None:
        return []
    proxy, volume = egress
    ca = f"{SANDBOX_EGRESS_CA_DIR}/ca.crt"
    env = {
        "HTTPS_PROXY": proxy,
        "HTTP_PROXY": proxy,
        "https_proxy": proxy,
        "http_proxy": proxy,
        "NO_PROXY": "localhost,127.0.0.1",
        "no_proxy": "localhost,127.0.0.1",
        # The proxy terminates TLS with its own name-constrained CA.
        "NODE_EXTRA_CA_CERTS": ca,
        "PIP_CERT": ca,
    }
    args: list[str] = []
    for key, value in env.items():
        args += ["-e", f"{key}={value}"]
    return [*args, "--mount", f"type=volume,src={volume},dst={SANDBOX_EGRESS_CA_DIR},readonly"]


def _is_hardened(entry: dict, container_name: str) -> bool:
    """A container this gateway may adopt: keyed with this gateway's key for
    its name (#98), not seccomp-unconfined or privileged (#99), and started
    with no-new-privileges (spec 009). One started
    before those changes (or by anything else) is not adopted."""
    env = (entry.get("Config") or {}).get("Env") or []
    try:
        expected = f"{SANDBOX_KEY_ENV}={sandbox_api_key(container_name)}"
    except RuntimeError:
        return False
    keyed = [e for e in env if e.startswith(f"{SANDBOX_KEY_ENV}=")]
    host = entry.get("HostConfig") or {}
    opts = [str(opt) for opt in host.get("SecurityOpt") or []]
    unconfined = any("unconfined" in opt for opt in opts)
    # spec 009 FR-017: started with no-new-privileges (no sudo, no setuid
    # escalation). One started before that is replaced, not adopted.
    no_new_privileges = any(opt.replace("=", ":") in ("no-new-privileges", "no-new-privileges:true") for opt in opts)
    caps_dropped = [str(c).upper() for c in host.get("CapDrop") or []] in (["ALL"], ["CAP_ALL"])
    return keyed == [expected] and not unconfined and no_new_privileges and caps_dropped and not host.get("Privileged")


#: Capabilities a sandbox keeps (everything else is dropped, spec 009 review).
SANDBOX_CAPS = ("CHOWN", "DAC_OVERRIDE", "FOWNER", "SETUID", "SETGID", "KILL", "AUDIT_WRITE")


SANDBOX_REFUSED_WITHOUT_NETWORK = (
    "Refusing to start a sandbox container: its API runs shell commands and must not be reachable from the host. "
    "Sandboxes run only on a Docker network shared with the gateway (set by docker compose: OMNI_HARNESS_SANDBOX_NETWORK); "
    "a gateway running on the host has no such network, and a token-checking proxy does not exist yet."
)
SANDBOX_REFUSED_APPLE = "Refusing to start a sandbox with the Apple container runtime: it cannot share a private network with the gateway, so its shell-exec API would be reachable from the host. Use Docker (the compose stack)."


def sandbox_network() -> str | None:
    value = os.environ.get(SANDBOX_NETWORK_ENV, "").strip()
    return value or None


class LocalContainerBackend(SandboxBackend):
    """Backend that manages sandbox containers locally using Docker or Apple Container.

    On macOS, automatically prefers Apple Container if available, otherwise falls back to Docker.
    On other platforms, uses Docker.

    Features:
    - Deterministic container naming for cross-process discovery
    - Port allocation with thread-safe utilities
    - Container lifecycle management (start/stop with --rm)
    - Support for volume mounts and environment variables
    """

    def __init__(
        self,
        *,
        image: str,
        base_port: int,
        container_prefix: str,
        config_mounts: list,
        environment: dict[str, str],
    ):
        """Initialize the local container backend.

        Args:
            image: Container image to use.
            base_port: Base port number to start searching for free ports.
            container_prefix: Prefix for container names (e.g., "omni-harness-sandbox").
            config_mounts: Volume mount configurations from config (list of VolumeMountConfig).
            environment: Environment variables to inject into containers.
        """
        self._image = image
        self._base_port = base_port
        self._container_prefix = container_prefix
        self._config_mounts = config_mounts
        self._environment = environment
        self._runtime = self._detect_runtime()

    @property
    def runtime(self) -> str:
        """The detected container runtime ("docker" or "container")."""
        return self._runtime

    def _detect_runtime(self) -> str:
        """Detect which container runtime to use.

        On macOS, prefer Apple Container if available, otherwise fall back to Docker.
        On other platforms, use Docker.

        Returns:
            "container" for Apple Container, "docker" for Docker.
        """
        import platform

        if platform.system() == "Darwin":
            try:
                result = subprocess.run(
                    ["container", "--version"],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=5,
                )
                logger.info(f"Detected Apple Container: {result.stdout.strip()}")
                return "container"
            except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                logger.info("Apple Container not available, falling back to Docker")

        return "docker"

    # ── SandboxBackend interface ──────────────────────────────────────────

    def _require_private_network(self) -> str:
        """The shared network, or a refusal (fail closed)."""
        if self._runtime != "docker":
            raise RuntimeError(SANDBOX_REFUSED_APPLE)
        network = sandbox_network()
        if network is None:
            raise RuntimeError(SANDBOX_REFUSED_WITHOUT_NETWORK)
        return network

    def _url_for(self, container_name: str) -> str:
        return f"http://{container_name}:{SANDBOX_API_PORT}"

    def create(self, thread_id: str, sandbox_id: str, extra_mounts: list[tuple[str, str, bool]] | None = None) -> SandboxInfo:
        """Start a new container and return its connection info.

        Args:
            thread_id: Thread ID for which the sandbox is being created. Useful for backends that want to organize sandboxes by thread.
            sandbox_id: Deterministic sandbox identifier (used in container name).
            extra_mounts: Additional volume mounts as (host_path, container_path, read_only) tuples.

        Returns:
            SandboxInfo with container details.

        Raises:
            RuntimeError: If the container fails to start.
        """
        container_name = f"{self._container_prefix}-{sandbox_id}"
        network = self._require_private_network()
        try:
            container_id = self._start_container(container_name, network, extra_mounts)
        except RuntimeError as exc:
            err_lower = str(exc).lower()
            # Container-name conflict: another process may have already started
            # the deterministic sandbox container for this sandbox_id. Try to
            # discover and adopt the existing container instead of failing.
            if "is already in use by container" in err_lower or "conflict. the container name" in err_lower:
                logger.warning(f"Container name {container_name} already in use, attempting to discover existing sandbox instance")
                existing = self.discover(sandbox_id)
                if existing is not None:
                    return existing
            raise
        return SandboxInfo(
            sandbox_id=sandbox_id,
            sandbox_url=self._url_for(container_name),
            container_name=container_name,
            container_id=container_id,
        )

    def destroy(self, info: SandboxInfo) -> None:
        """Stop the container and release its port."""
        # Prefer container_id, fall back to container_name (both accepted by docker stop).
        # This ensures containers discovered via list_running() (which only has the name)
        # can also be stopped.
        stop_target = info.container_id or info.container_name
        if stop_target:
            self._stop_container(stop_target)

    def is_alive(self, info: SandboxInfo) -> bool:
        """Check if the container is still running (lightweight, no HTTP)."""
        if info.container_name:
            return self._is_container_running(info.container_name)
        return False

    def discover(self, sandbox_id: str) -> SandboxInfo | None:
        """Discover an existing container by its deterministic name.

        Checks if a container with the expected name is running, retrieves its
        port, and verifies it responds to health checks.

        Args:
            sandbox_id: The deterministic sandbox ID (determines container name).

        Returns:
            SandboxInfo if container found and healthy, None otherwise.
        """
        container_name = f"{self._container_prefix}-{sandbox_id}"

        if self._runtime != "docker" or sandbox_network() is None:
            return None  # not reachable without the shared network (fail closed)
        if not self._is_container_running(container_name):
            return None
        inspected = self._batch_inspect([container_name]).get(container_name)
        if inspected is None or not inspected[2]:
            logger.warning("Removing sandbox container %s: it has no key from this gateway or runs unconfined", container_name)
            self._stop_container(container_name)
            return None

        sandbox_url = self._url_for(container_name)
        if not wait_for_sandbox_ready(sandbox_url, timeout=5, headers=auth_headers(container_name)):
            return None  # not ready, or not keyed with this gateway's secret

        return SandboxInfo(
            sandbox_id=sandbox_id,
            sandbox_url=sandbox_url,
            container_name=container_name,
        )

    def list_running(self) -> list[SandboxInfo]:
        """Enumerate all running containers matching the configured prefix.

        Uses a single ``docker ps`` call to list container names, then a
        single batched ``docker inspect`` call to retrieve creation timestamp
        and port mapping for all containers at once.  Total subprocess calls:
        2 (down from 2N+1 in the naive per-container approach).

        Note: Docker's ``--filter name=`` performs *substring* matching,
        so a secondary ``startswith`` check is applied to ensure only
        containers with the exact prefix are included.

        Containers without port mappings are still included (with empty
        sandbox_url) so that startup reconciliation can adopt orphans
        regardless of their port state.
        """
        # Step 1: enumerate container names via docker ps
        try:
            result = subprocess.run(
                [
                    self._runtime,
                    "ps",
                    "--filter",
                    f"name={self._container_prefix}-",
                    "--format",
                    "{{.Names}}",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                stderr = (result.stderr or "").strip()
                logger.warning(
                    "Failed to list running containers with %s ps (returncode=%s, stderr=%s)",
                    self._runtime,
                    result.returncode,
                    stderr or "<empty>",
                )
                return []
            if not result.stdout.strip():
                return []
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            logger.warning(f"Failed to list running containers: {e}")
            return []

        # Filter to names matching our exact prefix (docker filter is substring-based)
        # Only sandbox names: <prefix>-<8 hex> (the provider's deterministic id).
        # Anything else that merely shares the prefix (the egress proxy was
        # `omni-harness-sandbox-egress`) is neither adopted nor stopped.
        sandbox_name = re.compile(re.escape(self._container_prefix) + r"-[0-9a-f]{8}")
        container_names = [name.strip() for name in result.stdout.strip().splitlines() if sandbox_name.fullmatch(name.strip())]
        if not container_names:
            return []

        # Step 2: batched docker inspect — single subprocess call for all containers
        inspections = self._batch_inspect(container_names)

        infos: list[SandboxInfo] = []
        reachable = self._runtime == "docker" and sandbox_network() is not None
        for container_name in container_names:
            data = inspections.get(container_name)
            if data is None:
                # Container disappeared between ps and inspect, or inspect failed
                continue
            created_at, _host_port, hardened = data
            if not hardened:
                # Unkeyed or unconfined (started before #98/#99, or not by this
                # gateway): any other sandbox could drive it. Removed, never adopted.
                logger.warning("Removing sandbox container %s: it has no key from this gateway or runs unconfined", container_name)
                self._stop_container(container_name)
                continue
            sandbox_id = container_name[len(self._container_prefix) + 1 :]
            sandbox_url = self._url_for(container_name) if reachable else ""

            infos.append(
                SandboxInfo(
                    sandbox_id=sandbox_id,
                    sandbox_url=sandbox_url,
                    container_name=container_name,
                    created_at=created_at,
                )
            )

        logger.info(f"Found {len(infos)} running sandbox container(s)")
        return infos

    def _batch_inspect(self, container_names: list[str]) -> dict[str, tuple[float, int | None, bool]]:
        """Batch-inspect containers in a single subprocess call.

        Returns a mapping of ``container_name -> (created_at, host_port, hardened)``.
        Missing containers or parse failures are silently dropped from the result.
        """
        if not container_names:
            return {}
        try:
            result = subprocess.run(
                [self._runtime, "inspect", *container_names],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            logger.warning(f"Failed to batch-inspect containers: {e}")
            return {}

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            logger.warning(
                "Failed to batch-inspect containers with %s inspect (returncode=%s, stderr=%s)",
                self._runtime,
                result.returncode,
                stderr or "<empty>",
            )
            return {}

        try:
            payload = json.loads(result.stdout or "[]")
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse docker inspect output as JSON: {e}")
            return {}

        out: dict[str, tuple[float, int | None, bool]] = {}
        for entry in payload:
            # ``Name`` is prefixed with ``/`` in the docker inspect response
            name = (entry.get("Name") or "").lstrip("/")
            if not name:
                continue
            created_at = _parse_docker_timestamp(entry.get("Created", ""))
            host_port = _extract_host_port(entry, 8080)
            out[name] = (created_at, host_port, _is_hardened(entry, name))
        return out

    # ── Container operations ─────────────────────────────────────────────

    def _start_container(
        self,
        container_name: str,
        network: str,
        extra_mounts: list[tuple[str, str, bool]] | None = None,
    ) -> str:
        """Start a new container.

        Args:
            container_name: Name for the container.
            network: The private Docker network shared with the gateway (no host port is published).
            extra_mounts: Additional volume mounts.

        Returns:
            The container ID.

        Raises:
            RuntimeError: If container fails to start.
        """
        cmd = [self._runtime, "run"]

        # Docker's default seccomp profile applies (#99): the image's browser,
        # the only part that wanted it unconfined, is disabled.

        # NO -p: nothing is published on the host. The container joins the
        # private network it shares with the gateway (security baseline).
        cmd.extend(
            [
                "--rm",
                "-d",
                "--network",
                network,
                # The network is internal (no route out), and Docker Desktop's
                # names for the host are pinned away, so sandbox code cannot
                # reach host-loopback services through them.
                "--add-host",
                "host.docker.internal:0.0.0.0",
                "--add-host",
                "gateway.docker.internal:0.0.0.0",
                "--name",
                container_name,
                # No privilege escalation inside (spec 009 FR-017): the image
                # has no sudo grant and no setuid binaries; this makes sure.
                "--security-opt",
                "no-new-privileges",
                # Only the capabilities the image's start-up needs (create the
                # user, chown its home, drop to it with su/supervisord); no raw
                # sockets, mknod, chroot, setfcap/setpcap or setuid bits.
                "--cap-drop",
                "ALL",
                *[arg for cap in SANDBOX_CAPS for arg in ("--cap-add", cap)],
            ]
        )

        # Environment variables
        for key, value in self._environment.items():
            cmd.extend(["-e", f"{key}={value}"])
        # Its own API key (#98), set after the configured environment so
        # nothing can replace it; then the egress proxy, when there is one.
        cmd.extend(["-e", f"{SANDBOX_KEY_ENV}={sandbox_api_key(container_name)}"])
        cmd.extend(_egress_args(sandbox_egress()))

        # Config-level volume mounts
        for mount in self._config_mounts:
            cmd.extend(
                _format_container_mount(
                    self._runtime,
                    mount.host_path,
                    mount.container_path,
                    mount.read_only,
                )
            )

        # Extra mounts (thread-specific, skills, etc.)
        if extra_mounts:
            for host_path, container_path, read_only in extra_mounts:
                cmd.extend(
                    _format_container_mount(
                        self._runtime,
                        host_path,
                        container_path,
                        read_only,
                    )
                )

        cmd.append(self._image)

        log_cmd = _format_container_command_for_log(_redact_container_command_for_log(cmd))
        logger.info(f"Starting container using {self._runtime}: {log_cmd}")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            container_id = result.stdout.strip()
            logger.info(f"Started container {container_name} (ID: {container_id}) using {self._runtime}")
            return container_id
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to start container using {self._runtime}: {e.stderr}")
            raise RuntimeError(f"Failed to start sandbox container: {e.stderr}")

    def _stop_container(self, container_id: str) -> None:
        """Stop a container (--rm ensures automatic removal)."""
        try:
            subprocess.run(
                [self._runtime, "stop", container_id],
                capture_output=True,
                text=True,
                check=True,
            )
            logger.info(f"Stopped container {container_id} using {self._runtime}")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to stop container {container_id}: {e.stderr}")

    def _is_container_running(self, container_name: str) -> bool:
        """Check if a named container is currently running.

        This enables cross-process container discovery — any process can detect
        containers started by another process via the deterministic container name.
        """
        try:
            result = subprocess.run(
                [self._runtime, "inspect", "-f", "{{.State.Running}}", container_name],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0 and result.stdout.strip().lower() == "true"
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False
