---
name: mcp-server-builder
description: Scaffold, generate, and test a FastMCP server that can be used as an MCP tool provider. Handles API wrapper, database connector, and custom tool templates.
---

# MCP Server Builder

Use this skill when a user asks to create, generate, or build an MCP server. OmniHarness can scaffold a fully functional FastMCP server from a description, write the source code, and run it through the automated test pipeline.

## Workflow

1. **Understand the intent** — identify the server name, description, template type, and any external services or secrets needed.
2. **Scaffold the code** — write `server.py` using FastMCP following the template below. Each tool must have a clear docstring and typed parameters.
3. **Submit for testing** — call `mcp_build(server_id=..., source_code=...)`. The tool runs static security scans, checks that all required secrets are stored in the vault, starts the server in an isolated subprocess, connects the MCP client, lists the discovered tools, and test-calls each one.
4. **Report results** — tell the user which tools were discovered, which test-calls passed, and whether any secrets are missing.
5. **Iterate** — if errors are returned fix the code and call `mcp_build` again.

Do NOT write files to the sandbox for this skill. Pass the complete source code directly to `mcp_build` as the `source_code` parameter.

## Project structure

A minimal MCP server consists of a single `server.py` file.

```
server.py          ← entrypoint — always named server.py
requirements.txt   ← optional — any extra pip packages beyond fastmcp
```

## server.py skeleton

```python
import os

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("server-name")


@mcp.tool()
def tool_name(param: str) -> str:
    """One-sentence description of what this tool does and what it returns."""
    # implementation
    return result


if __name__ == "__main__":
    _transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if _transport == "sse":
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = int(os.environ.get("MCP_PORT", "8080"))
        mcp.settings.transport_security = None
        mcp.run(transport="sse")
    else:
        mcp.run()
```

**Rules that must be followed in every generated server:**

| Rule | Why |
|---|---|
| `from mcp.server.fastmcp import FastMCP` | Only import — never raw `mcp.Server` |
| `if __name__ == "__main__": ...` with `MCP_TRANSPORT` check (see templates) | Supports both stdio (sandbox) and SSE (Docker deploy) |
| Secrets via `os.getenv("KEY_NAME")` only | Values are injected from the vault; never hardcode them |
| **Never raise or crash at startup when a secret is missing** | The server is first started with NO secrets to discover its tools. A server that raises at import or module level when `os.getenv` returns `None` will register 0 tools and can never be verified. Check for missing keys inside the tool handler, return a structured error, don't raise. |
| **Never import `subprocess`, `os.system`, `os.popen`, `eval`, `exec`, `pickle`, or `ctypes`** | These are hard-blocked by the static security scanner and will permanently fail verification |
| Use the `_ensure_api_key()` guard pattern for missing keys | Return a JSON error dict, don't raise — see template below |
| Every tool has a one-sentence docstring | Exposes to the MCP client for tool discovery |
| Typed parameters on every tool function | Required for the MCP schema to be generated correctly |
| No `asyncio.run()` or custom event loops | FastMCP manages the loop |
| No file I/O outside of `/tmp` | Servers run in an isolated subprocess with no persistent disk access |

## Template: API Wrapper

Use when the server wraps a REST/HTTP API (e.g. weather, search, GitHub, Stripe).

**Critical pattern**: `os.getenv` at module level is fine — the value will be `None` during tool
discovery (the server is started with no secrets first). The `_ensure_api_key()` helper catches this
and returns a structured JSON error from the tool handler. Never raise at module level.

```python
import json
import os

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("my-api-wrapper")

BASE_URL = "https://api.example.com"
# Read at module level — will be None during discovery; checked inside tool handlers
API_KEY = os.getenv("EXAMPLE_API_KEY")


def _ensure_api_key() -> str | None:
    """Return a JSON error string if the API key is missing, else None."""
    if not API_KEY:
        return json.dumps({
            "error": "Missing EXAMPLE_API_KEY secret. Add it in Settings → Secrets.",
            "missing_secret": "EXAMPLE_API_KEY",
        })
    return None


@mcp.tool()
def search(query: str) -> str:
    """Search the Example API and return up to 5 results as JSON."""
    missing = _ensure_api_key()
    if missing:
        return missing
    resp = httpx.get(
        f"{BASE_URL}/search",
        headers={"Authorization": f"Bearer {API_KEY}"},
        params={"q": query, "limit": 5},
        timeout=15,
    )
    if resp.status_code >= 400:
        return json.dumps({"error": f"API error {resp.status_code}", "details": resp.text})
    return resp.text


@mcp.tool()
def get_item(item_id: str) -> str:
    """Fetch a single item by ID and return its JSON representation."""
    missing = _ensure_api_key()
    if missing:
        return missing
    resp = httpx.get(
        f"{BASE_URL}/items/{item_id}",
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=15,
    )
    if resp.status_code >= 400:
        return json.dumps({"error": f"API error {resp.status_code}", "details": resp.text})
    return resp.text


if __name__ == "__main__":
    _transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if _transport == "sse":
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = int(os.environ.get("MCP_PORT", "8080"))
        mcp.settings.transport_security = None
        mcp.run(transport="sse")
    else:
        mcp.run()
```

## Template: Database Connector

Use when the server exposes SQL queries over a database (e.g. Postgres, SQLite, MySQL).

```python
import json
import os

import psycopg2
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("my-db-connector")

_DSN = os.getenv("DATABASE_URL")


def _conn():
    return psycopg2.connect(_DSN)


@mcp.tool()
def query(sql: str) -> str:
    """Execute a read-only SQL SELECT and return results as JSON array of objects."""
    if not sql.strip().upper().startswith("SELECT"):
        return json.dumps({"error": "Only SELECT queries are allowed."})
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchmany(100)]
    return json.dumps(rows, default=str)


@mcp.tool()
def list_tables() -> str:
    """Return the names of all tables in the public schema."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        return json.dumps([r[0] for r in cur.fetchall()])


if __name__ == "__main__":
    _transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if _transport == "sse":
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = int(os.environ.get("MCP_PORT", "8080"))
        mcp.settings.transport_security = None
        mcp.run(transport="sse")
    else:
        mcp.run()
```

## Template: Custom Tool

Use for anything that doesn't fit API wrapper or database patterns — file processing, local computation, integration with a Python library, etc.

```python
import os

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("my-custom-tools")

# Secrets from vault — never hardcode values
SERVICE_TOKEN = os.getenv("SERVICE_TOKEN")


@mcp.tool()
def process(input_text: str) -> str:
    """Process input_text and return the transformed result."""
    # Your logic here
    result = input_text.upper()  # placeholder
    return result


@mcp.tool()
def status() -> str:
    """Return a health check status string."""
    return "ok"


if __name__ == "__main__":
    _transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if _transport == "sse":
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = int(os.environ.get("MCP_PORT", "8080"))
        mcp.settings.transport_security = None
        mcp.run(transport="sse")
    else:
        mcp.run()
```

## Calling `mcp_build`

After writing the source code, call the tool exactly like this:

```
mcp_build(
    server_id="<the server_id from the task>",
    source_code="<complete server.py content as a string>"
)
```

The tool returns a JSON object:

```json
{
  "phase": "testing" | "failed" | "ready",
  "tools_discovered": [{"name": "...", "description": "..."}],
  "detected_secret_names": ["ENV_VAR_NAME_1", ...],
  "errors": ["..."],
  "test_results": [{"tool": "...", "ok": true, "output": "..."}],
  "last_verified_at": "2026-06-11T..."
}
```

If `phase` is `"failed"`, inspect `errors` and fix the code, then call `mcp_build` again.

If `detected_secret_names` contains names the user hasn't stored yet, tell them which secrets are needed and that they can add them via **Settings → Secrets** in the MCP Studio UI.

## Tips

- Keep tools focused: one tool = one action.
- Use `httpx` (not `requests`) for HTTP calls — it works with the async event loop.
- If you need a library that isn't in the standard library, add it to a `requirements.txt` comment in your explanation so the user knows to install it (the sandbox will install it automatically when `requirements.txt` is present alongside `server.py`).
- Never print secrets to stdout — FastMCP uses stdout for the MCP wire protocol.
