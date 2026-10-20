"""Starts a built MCP server inside its container (Feature 006, #59).

The generated ``server.py`` is never rewritten. This launcher:

1. waits for the gateway to hand over the container's files: ``/run/omni`` is
   a tmpfs owned by this (non-root) user; the gateway writes ``secrets``
   there over ``docker exec`` stdin, mode 0400, then ``ready``;
2. reads ``secrets`` (``KEY=VALUE`` lines) into THIS process's environment,
   which ``docker inspect`` never shows;
3. imports ``/app/server.py`` under a name that is not ``__main__`` (so its
   own ``if __name__ == "__main__"`` block does not run), finds its one
   ``FastMCP`` instance, and runs it over stdio or SSE (``MCP_TRANSPORT``).

stdout belongs to the MCP protocol in stdio mode; this file writes to stderr.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time

RUN_DIR = os.environ.get("OMNI_RUN_DIR", "/run/omni")
SERVER_PATH = os.environ.get("OMNI_SERVER_PATH", "/app/server.py")
WAIT_SECONDS = float(os.environ.get("OMNI_WAIT_SECONDS", "30"))


def _say(text: str) -> None:
    print(f"[omni-launch] {text}", file=sys.stderr, flush=True)


def wait_for_files() -> None:
    ready = os.path.join(RUN_DIR, "ready")
    deadline = time.monotonic() + WAIT_SECONDS
    while not os.path.exists(ready):
        if time.monotonic() > deadline:
            _say("the gateway never handed over this server's files; exiting")
            sys.exit(3)
        time.sleep(0.05)


def load_secrets() -> int:
    path = os.path.join(RUN_DIR, "secrets")
    if not os.path.exists(path):
        return 0
    count = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh.read().split("\n"):
            if not line:
                continue
            key, sep, value = line.partition("=")
            if not sep or not key:
                _say("a malformed line in the secrets file was skipped")
                continue
            os.environ[key] = value
            count += 1
    return count


def load_server():
    spec = importlib.util.spec_from_file_location("omni_built_server", SERVER_PATH)
    if spec is None or spec.loader is None:
        _say(f"cannot load {SERVER_PATH}")
        sys.exit(2)
    module = importlib.util.module_from_spec(spec)
    sys.modules["omni_built_server"] = module
    spec.loader.exec_module(module)
    from mcp.server.fastmcp import FastMCP

    servers = [v for v in vars(module).values() if isinstance(v, FastMCP)]
    if len(servers) != 1:
        _say(f"expected exactly one FastMCP server in {SERVER_PATH}, found {len(servers)}")
        sys.exit(2)
    return servers[0]


def main() -> None:
    wait_for_files()
    n = load_secrets()
    _say(f"{n} key(s) loaded from the secrets file")
    server = load_server()
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "sse":
        server.settings.host = "0.0.0.0"  # inside its internal network only
        server.settings.port = int(os.environ.get("MCP_PORT", "8080"))
        # Reached only through the sidecar, which checks the endpoint token.
        server.settings.transport_security = None
        server.run(transport="sse")
    else:
        server.run()


if __name__ == "__main__":
    main()
