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
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

import mcp.types as types
import uvicorn
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from .adapters.claude_code import ClaudeCodeAdapter
from .adapters.codex import CodexAdapter
from .discovery import Discovery, DiscoveryConfig
from .record_source import RecordSource
from .redaction import Channel, redact_or_suppress
from .registry import Observability, SessionRegistry
from .reply import compose_rollup, compose_status
from .state import StateConfig, resolve
from .summarize.mechanical import MechanicalSummarizer
from .watcher import FileWatcher, Reconciler, WatchConfig

logger = logging.getLogger(__name__)
DEFAULT_PORT = 18101


#: Spoken and displayed names, by agent.
AGENT_LABELS = {"claude": "Claude Code", "codex": "Codex"}
#: Todo items and changed files carried per session in a reply.
MAX_TODOS = 50
MAX_FILES = 50


class WatcherService:
    """Holds the registry and refreshes it. No MCP knowledge lives here.

    One RecordSource per agent root (Feature 005): Claude Code always, Codex
    when a root is configured. An agent whose root is configured but cannot be
    read is reported as such in every reply, never as "no sessions" (FR-026).
    """

    def __init__(self, root: Path, *, codex_root: Path | None = None, channel: Channel = Channel.REMOTE) -> None:
        self.source = RecordSource(root=root)
        self.sources: dict[str, RecordSource] = {"claude": self.source}
        more = []
        if codex_root is not None:
            self.sources["codex"] = RecordSource(root=codex_root)
            more.append(CodexAdapter(self.sources["codex"]))
        self.discovery = Discovery(ClaudeCodeAdapter(self.source), DiscoveryConfig(), more_adapters=more)
        self.registry = SessionRegistry()
        self.summarizer = MechanicalSummarizer()
        self.state_config = StateConfig()
        self.channel = channel
        # The adapter keeps per-file read offsets; the background loop and an
        # MCP request can both refresh, and must not interleave.
        self._refresh_lock = threading.Lock()

    def refresh(self, *, now: datetime | None = None) -> None:
        with self._refresh_lock:
            self._refresh(now=now)

    def _refresh(self, *, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        refs = self.discovery.sweep(now=now)
        sessions = [resolve(r, now=now, config=self.state_config) for r in refs]
        # merge(), not replace_all(): a session that completed and then aged out
        # of the discovery window must keep its terminal state rather than
        # vanishing. A vanished session reads as "never existed", which is a
        # different and wronger claim than "finished an hour ago" (FR-004).
        self.registry.merge(sessions, now)
        for sid in self.discovery.sticky_ids - set(self.registry.sessions):
            self.discovery.release(sid)

    def agents(self) -> list[dict]:
        """Per-agent health: readable, and how much drift its reader has seen."""
        out = []
        for agent, source in self.sources.items():
            if source.root is None:
                continue  # not configured (tests that pre-fill the registry)
            # An agent home that exists without a sessions folder has never
            # recorded a session: that is "none", not "can't tell".
            folder = source.root if source.root.is_dir() else source.root.parent
            readable = folder.is_dir() and os.access(folder, os.R_OK)
            out.append(
                {
                    "agent": agent,
                    "label": AGENT_LABELS.get(agent, agent),
                    "readable": readable,
                    "reason": None if readable else f"{source.root} is not mounted or not readable",
                    # Malformed lines, untyped records, unknown record types
                    # (skipped or parsed) and named shape changes: the signal
                    # that the agent's format moved (FR-024).
                    "drift": source.stats.drift_signals,
                    "unknown_types": dict(source.stats.unknown_types),
                    "diagnostics": dict(source.stats.diagnostics),
                }
            )
        return out

    def _envelope(self, now: datetime) -> dict:
        obs = self.registry.observability(now)
        return {
            "observable": obs is Observability.LIVE,
            "observability": obs.value,
            "as_of": self.registry.last_heartbeat_at.isoformat() if self.registry.last_heartbeat_at else None,
            "staleness_seconds": self.registry.staleness_seconds(now),
            "agents": self.agents(),
        }

    def _safe(self, text: str) -> str:
        """Agent-written text (todo titles, paths) is redacted, or Withheld."""
        safe, ok = redact_or_suppress(text, self.channel)
        return safe if ok else "Withheld"

    def _activity(self, s) -> dict:
        todos = None if s.todos is None else [{"title": self._safe(t), "status": st} for t, st in s.todos[:MAX_TODOS]]
        return {
            "agent": s.agent,
            "agent_label": AGENT_LABELS.get(s.agent, s.agent),
            "todos": todos,
            "files_changed": [self._safe(f) for f in s.files_changed[-MAX_FILES:]],
            # Observed: the agent recorded the link (a `continued-in` record).
            "continued_from": s.continued_from,
            "continued_in": s.continued_in,
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
                    "quiet_seconds": s.quiet_seconds(now),
                    "summary": text,
                    "summary_provenance": prov,
                    "relay_suppressed": not ok,
                    **self._activity(s),
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
        elif (continued := self.registry.continuation_of(key)) is not None:
            # Asked by the earlier id of a continued session: it is this one.
            matches = [continued]
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
                "quiet_seconds": s.quiet_seconds(now),
                "summary": text,
                "summary_provenance": prov,
                "relay_suppressed": not ok,
                "recent_events": events,
                **self._activity(s),
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
                    "Read-only (Tier 1). Use the `reply` field verbatim — it already "
                    "applies the required wording. If you rephrase, keep these: when "
                    "`observable` is false an empty list does NOT mean no sessions are "
                    "running, and the staleness caveat must come BEFORE any session "
                    "data; 'finished' was observed, 'may have stalled' was inferred."
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
            spoken = compose_rollup(payload)
        elif name == "get_session_status":
            payload = service.session_status(str(arguments.get("session_id", "")))
            spoken = compose_status(payload)
        else:
            payload = {"error": f"unknown tool {name}"}
            spoken = f"unknown tool {name}"
        # `reply` carries the wording rules already applied — caveat-first when
        # stale, hedge-leading for inferred states, completed and stalled kept
        # apart. The structured payload follows for anything that needs fields.
        payload = {"reply": spoken, **payload}
        return [types.TextContent(type="text", text=json.dumps(payload, indent=2))]

    return server


def build_app(service: WatcherService) -> Starlette:
    server = build_server(service)
    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as (r, w):
            await server.run(r, w, server.create_initialization_options())
        # A Starlette endpoint must return a response. Returning None raised
        # "'NoneType' object is not callable" when every client disconnected:
        # one traceback per tool call, which with the trigger engine polling
        # each minute would be ~1,440 a day in the watcher's log.
        return Response()

    async def health(request):
        now = datetime.now(UTC)
        return JSONResponse(
            {
                "ok": True,
                "observability": service.registry.observability(now).value,
                "sessions": len(service.registry.sessions),
                "agents": service.agents(),
            }
        )

    return Starlette(
        routes=[
            Route("/health", endpoint=health),
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )


def start_background_refresh(service: WatcherService, config: WatchConfig | None = None) -> tuple[threading.Event, FileWatcher, str]:
    """Keep the registry current between tool calls.

    Without this the heartbeat never beats, so `observability` is always stale
    between calls and always fresh during one — a signal that carries no
    information. The Reconciler's unconditional interval is also what makes a
    dropped filesystem event or a sleep/wake gap survivable.
    """
    reconciler = Reconciler(config=config or WatchConfig())
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            now = datetime.now(UTC)
            if reconciler.due(now):
                gap = reconciler.detect_gap(now)
                if gap is not None:
                    logger.info("observation gap of %s (sleep/wake?); reconciling", gap)
                try:
                    service.refresh(now=now)
                except Exception:  # noqa: BLE001 - a bad sweep must not kill the loop
                    logger.exception("refresh failed; will retry on the next interval")
                reconciler.note_swept(datetime.now(UTC))
            stop.wait(1.0)

    threading.Thread(target=loop, daemon=True, name="session-watcher-refresh").start()
    fw = FileWatcher(service.source.root, reconciler.note_change)
    mode = fw.start()
    logger.info("watching %s (%s)", service.source.root, mode)
    # Further roots (Codex) get their own watcher; the reconciliation sweep
    # covers them either way, so a root that cannot be watched only delays.
    for agent, source in service.sources.items():
        if source is service.source or source.root is None or not source.root.is_dir():
            continue
        extra = FileWatcher(source.root, reconciler.note_change)
        logger.info("watching %s for %s (%s)", source.root, agent, extra.start())
    return stop, fw, mode


def build_service(root: Path, codex_root: Path | None) -> WatcherService:
    """The service exactly as `main` builds it: the production composition root."""
    return WatcherService(root=root, codex_root=codex_root)


def main() -> None:
    ap = argparse.ArgumentParser(description="Read-only coding-session watcher (MCP over SSE)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--root", type=Path, default=Path.home() / ".claude" / "projects")
    # Codex is watched only when a root is given (compose passes the read-only
    # mount). Configured but unreadable is reported, never read as "none".
    ap.add_argument("--codex-root", type=Path, default=None)
    ap.add_argument("--log-level", default="info")
    args = ap.parse_args()
    logging.basicConfig(level=args.log_level.upper())
    service = build_service(args.root, args.codex_root)
    service.refresh()
    start_background_refresh(service)
    # 0.0.0.0 so a containerized backend can reach us via host.docker.internal.
    uvicorn.run(build_app(service), host="0.0.0.0", port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    main()
