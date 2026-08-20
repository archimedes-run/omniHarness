"""T006 TRANSPORT SPIKE — throwaway. Delete once the real server (T037) lands.

Sole purpose: prove that a host-resident SSE MCP server is reachable from the
containerized backend, before any of Phase 2 is built on that assumption.
If this cannot be made to work, the transport decision (FR-018a) is wrong and
the plan needs revisiting — which is exactly what we want to learn now rather
than at T065.
"""

from __future__ import annotations

import argparse

import mcp.types as types
import uvicorn
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

server = Server("session-watcher-spike")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_coding_sessions",
            description="SPIKE: hardcoded status payload proving transport reachability.",
            inputSchema={"type": "object", "properties": {}},
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    return [
        types.TextContent(
            type="text",
            text='{"observable": true, "as_of": "SPIKE", "sessions": [{"project": "spike-proof", "state": "working"}]}',
        )
    ]


def build_app() -> Starlette:
    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as (r, w):
            await server.run(r, w, server.create_initialization_options())

    async def health(request):
        return JSONResponse({"ok": True, "spike": "session-watcher"})

    return Starlette(
        routes=[
            Route("/health", endpoint=health),
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18101)
    args = ap.parse_args()
    # 0.0.0.0 so the container can reach us via host.docker.internal.
    uvicorn.run(build_app(), host="0.0.0.0", port=args.port, log_level="warning")
