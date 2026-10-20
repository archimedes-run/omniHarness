"""Files handed to a built server or its sidecar (Feature 006, #59).

No secret ever goes in ``-e`` or ``--env-file``: Docker keeps those in the
container's config, where ``docker inspect`` shows them. Instead each
container gets a tmpfs at ``/run/omni`` owned by its non-root user, and the
gateway writes each file over ``docker exec`` STDIN (never argv), mode 0400,
then ``ready``, then makes the directory 0500. The container reads them at
startup.

The secrets file is ``KEY=VALUE`` lines, so its keys and values are
validated: a key that could redirect the proxy or the interpreter, or a value
with a line break (a second, injected line), is refused.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from app.gateway.mcp_docker import DockerRunner

RUN_DIR = "/run/omni"
#: The only file names ever written (the name goes into a shell command).
FILE_NAMES = frozenset({"secrets", "squid.conf", "dnsmasq.conf", "passwd"})

_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_RESERVED_EXACT = frozenset({"HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "ALL_PROXY", "HOME", "PATH", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"})
_RESERVED_PREFIX = ("MCP_", "PYTHON", "LD_", "SSL_", "__", "OMNI_")
#: Keys only the gateway's own deploy code writes (never a stored secret).
GATEWAY_KEYS = frozenset({"HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY"})


class SecretFileError(ValueError):
    pass


def secret_name_problem(name: str) -> str | None:
    """Why *name* can't be a stored secret's name, or None."""
    if not _KEY.match(name or ""):
        return f"{name!r} is not a valid name: use A-Z, 0-9 and _, starting with a letter"
    upper = name.upper()
    if upper in _RESERVED_EXACT or upper.startswith(_RESERVED_PREFIX):
        return f"{name!r} is reserved: it would change how the server or its proxy runs"
    return None


def secret_value_problem(name: str, value: str) -> str | None:
    if any(c in value for c in ("\n", "\r", "\x00")):
        return f"the value of {name!r} contains a line break or NUL"
    return None


def render_secrets(secrets: Mapping[str, str], *, gateway: Mapping[str, str] | None = None) -> bytes:
    """The secrets file. *secrets* are the user's (validated, reserved names
    refused); *gateway* are the deploy code's own (e.g. HTTPS_PROXY)."""
    lines: list[str] = []
    for name, value in sorted(secrets.items()):
        problem = secret_name_problem(name) or secret_value_problem(name, value)
        if problem:
            raise SecretFileError(problem)
        lines.append(f"{name}={value}")
    for name, value in sorted((gateway or {}).items()):
        if name not in GATEWAY_KEYS:
            raise SecretFileError(f"{name!r} is not a key the gateway sets")
        problem = secret_value_problem(name, value)
        if problem:
            raise SecretFileError(problem)
        lines.append(f"{name}={value}")
    return ("\n".join(lines) + "\n").encode("utf-8") if lines else b""


async def deliver(runner: DockerRunner, container: str, uid: str, files: Mapping[str, bytes], *, timeout: float = 15.0) -> None:
    """Write each file into the container's /run/omni over stdin, then mark it
    ready and close the directory. Raises RuntimeError naming the step."""
    for name, data in files.items():
        if name not in FILE_NAMES:
            raise ValueError(f"not a container file name: {name!r}")
        rc, _, err = await runner.run(["docker", "exec", "-i", "-u", uid, container, "sh", "-c", f"umask 0377 && cat > {RUN_DIR}/{name}"], stdin=data, timeout=timeout)
        if rc != 0:
            raise RuntimeError(f"could not hand over {name}: {err.strip()[:200]}")
    rc, _, err = await runner.run(["docker", "exec", "-u", uid, container, "sh", "-c", f"touch {RUN_DIR}/ready && chmod 0500 {RUN_DIR}"], timeout=timeout)
    if rc != 0:
        raise RuntimeError(f"could not mark the files ready: {err.strip()[:200]}")
