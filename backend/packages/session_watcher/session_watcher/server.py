"""The SSE MCP server — the watcher's only integration point (FR-018, FR-018b).

SSE rather than stdio, and that is a correctness constraint rather than a
deployment preference: a stdio server is spawned as a subprocess of the backend,
so under Docker it could not read the host's session directory at all (FR-018a,
FR-021). Proven against a running container before any of this was built.

Both tools are Tier 1. There is no mutation argument and no third tool — the
observe-only limit of FR-015 is enforced by absence rather than by policy.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import mcp.types as types
import uvicorn
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .adapters.claude_code import ClaudeCodeAdapter
from .discovery import Discovery, DiscoveryConfig
from .record_source import RecordSource
from .redaction import Channel, redact_or_suppress
from .registry import Observability, SessionRegistry
from .state import StateConfig, resolve
from .summarize.mechanical import MechanicalSummarizer

logger = logging.getLogger(__name__)
DEFAULT_PORT = 18101


class WatcherService:
    """Holds the registry and refreshes it. No MCP knowledge lives here."""

    def __init__(self, root: Path, *, channel: Channel = Channel.REMOTE) -> None:
        self.source = RecordSource(root=root)
        self.discovery = Discovery(ClaudeCodeAdapter(self.source), DiscoveryConfig())
        self.registry = SessionRegistry()
        self.summarizer = MechanicalSummarizer()
        self.state_config = StateConfig()
        self.channel = channel

    def refresh(self, *, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        refs = self.discovery.sweep(now=now)
        sessions = [resolve(r, now=now, config=self.state_config) for r in refs]
        self.registry.replace_all(sessions, now)

    def _envelope(self, now: datetime) -> dict:
        obs = self.registry.observability(now)
        return {
            "observable": obs is Observability.LIVE,
            "observability": obs.value,
            "as_of": self.registry.last_heartbeat_at.isoformat() if self.registry.last_heartbeat_at else None,
            "staleness_seconds": self.registry.staleness_seconds(now),
        }

    def _summarize(self, text: str) -> tuple[str, str, bool]:
        summary = self.summarizer.summarize([text])[0] if text else None
        raw = summary.text if summary else ""
        safe, ok = redact_or_suppress(raw, self.channel)
        prov = summary.provenance.value if summary else "mechanical"
        return safe, prov, ok

    def list_sessions(self, *, now: datetime | None = None) -> dict:
        now = now or datetime.now(UTC)
        out = self._envelope(now)
        rows = []
        for s in self.registry.all_sessions():
            text, prov, ok = self._summarize(s.last_message)
            rows.append(
                {
                    "session_id": s.session_id,
                    "project": s.project,
                    "state": s.state.value,
                    "idle_reason": s.idle_reason.value if s.idle_reason else None,
                    "last_activity_at": s.last_activity_at.isoformat(),
                    "elapsed_seconds": s.elapsed_seconds(now),
                    "quiet_seconds": int((now - s.last_activity_at).total_seconds()),
                    "summary": text,
                    "summary_provenance": prov,
                    "relay_suppressed": not ok,
                }
            )
        out["sessions"] = rows
        return out

    def session_status(self, key: str, *, now: datetime | None = None) -> dict:
        now = now or datetime.now(UTC)
        out = self._envelope(now)
        matches = self.registry.match_project(key)
        if key in self.registry.sessions:
            matches = [self.registry.sessions[key]]
        if len(matches) > 1:
            out.update(
                found=False,
                ambiguous=True,
                candidates=[f"{m.project} ({m.session_id[:8]})" for m in matches],
                session=None,
            )
            return out
        if not matches:
            out.update(found=False, ambiguous=False, candidates=[], session=None)
            return out
        s = matches[0]
        text, prov, ok = self._summarize(s.last_message)
        events = []
        for ev in s.events[-10:]:
            ev_text, ev_prov, _ = self._summarize(ev.summary)
            events.append({"kind": ev.kind.value, "at": ev.at.isoformat(), "summary": ev_text, "summary_provenance": ev_prov})
        out.update(
            found=True,
            ambiguous=False,
            candidates=[],
            session={
                "session_id": s.session_id,
                "project": s.project,
                "state": s.state.value,
                "idle_reason": s.idle_reason.value if s.idle_reason else None,
                "started_at": s.started_at.isoformat(),
                "last_activity_at": s.last_activity_at.isoformat(),
                "elapsed_seconds": s.elapsed_seconds(now),
                "quiet_seconds": int((now - s.last_activity_at).total_seconds()),
                "summary": text,
                "summary_provenance": prov,
                "relay_suppressed": not ok,
                "recent_events": events,
            },
        )
        return out


def build_server(service: WatcherService) -> Server:
    server = Server("session-watcher")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="list_coding_sessions",
                description=(
                    "Status of every coding-agent session observed on this machine. "
                    "Read-only (Tier 1). Check `observable`: when false, session state "
                    "cannot currently be seen and an empty list does NOT mean no "
                    "sessions are running. Lead any reply with the staleness caveat."
                ),
                inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
            ),
            types.Tool(
                name="get_session_status",
                description=(
                    "Detail for one session by id or project name. Read-only (Tier 1). "
                    "`ambiguous` means several matched — ask which, do not choose. "
                    "idle_reason 'completed' was OBSERVED; 'stalled' was INFERRED from "
                    "inactivity and must be worded as such."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {"session_id": {"type": "string"}},
                    "required": ["session_id"],
                    "additionalProperties": False,
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        service.refresh()
        if name == "list_coding_sessions":
            payload = service.list_sessions()
        elif name == "get_session_status":
            payload = service.session_status(str(arguments.get("session_id", "")))
        else:
            payload = {"error": f"unknown tool {name}"}
        return [types.TextContent(type="text", text=json.dumps(payload, indent=2))]

    return server


def build_app(service: WatcherService) -> Starlette:
    server = build_server(service)
    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as (r, w):
            await server.run(r, w, server.create_initialization_options())

    async def health(request):
        now = datetime.now(UTC)
        return JSONResponse(
            {
                "ok": True,
                "observability": service.registry.observability(now).value,
                "sessions": len(service.registry.sessions),
            }
        )

    return Starlette(
        routes=[
            Route("/health", endpoint=health),
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Read-only coding-session watcher (MCP over SSE)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--root", type=Path, default=Path.home() / ".claude" / "projects")
    ap.add_argument("--log-level", default="info")
    args = ap.parse_args()
    logging.basicConfig(level=args.log_level.upper())
    service = WatcherService(root=args.root)
    service.refresh()
    # 0.0.0.0 so a containerized backend can reach us via host.docker.internal.
    uvicorn.run(build_app(service), host="0.0.0.0", port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    main()
