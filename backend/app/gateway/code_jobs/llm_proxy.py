"""The gateway's LLM proxy for coding jobs (spec 009 FR-003, FR-004, FR-004b, D3).

A separate listener, bound to the gateway's own address on the sandbox
network only, speaking the chat-completions API. The sandbox has no provider
key: OpenCode sends a per-job token (tokens.py); the proxy checks it, checks
the call comes from the token's own container, checks the job is running and
under its budget, the month under its cap and the sandbox under its rate,
then forwards to the provider with the key injected here. Every call, allowed
or refused, is recorded (store.llm_calls) and written to the policy log
(`<policy state dir>/llm-proxy.jsonl`). Prompts and completions are never
logged.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import socket
import threading
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from . import tokens
from .pricing import cost_usd
from .store import CodeJobStore
from .upstream import Upstream

logger = logging.getLogger(__name__)

#: The one model name the worker may ask for (the managed config's alias).
WORKER_MODEL = "worker"
_CONTAINER_TTL = 30.0


@dataclass
class ProxySettings:
    store: CodeJobStore
    upstream_for: Callable[[], tuple[Upstream | None, str | None]]
    subnets: list[ipaddress.IPv4Network]
    monthly_cap_usd: float
    rate_per_minute: int
    max_request_bytes: int
    prices: dict = field(default_factory=dict)
    policy_log: Path | None = None
    #: container name -> address; injectable for tests.
    resolve_container: Callable[[str], str | None] | None = None
    transport: httpx.AsyncBaseTransport | None = None


def _error(status: int, message: str, kind: str = "omni_refused") -> JSONResponse:
    return JSONResponse({"error": {"message": message, "type": kind}}, status_code=status)


class _ContainerAddresses:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, str | None]] = {}

    def __call__(self, name: str) -> str | None:
        hit = self._cache.get(name)
        if hit and time.monotonic() - hit[0] < _CONTAINER_TTL:
            return hit[1]
        try:
            addr = socket.gethostbyname(name)
        except OSError:
            addr = None
        self._cache[name] = (time.monotonic(), addr)
        return addr


def _policy_log(path: Path | None, entry: dict) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": datetime.now(UTC).isoformat(), "kind": "llm-proxy", **entry}, sort_keys=True) + "\n")
    except OSError:
        logger.warning("llm proxy: could not write the policy log")


def _normalise_body(body: dict, upstream: Upstream) -> dict:
    out = dict(body)
    out["model"] = upstream.model
    if out.get("stream"):
        opts = dict(out.get("stream_options") or {})
        opts["include_usage"] = True
        out["stream_options"] = opts
    if upstream.reasoning_model:
        # Reasoning models refuse max_tokens and any non-default sampling.
        if "max_tokens" in out:
            out.setdefault("max_completion_tokens", out.pop("max_tokens"))
        for key in ("temperature", "top_p"):
            if key in out and out[key] not in (None, 1, 1.0):
                out.pop(key)
    out.pop("user", None)
    return out


def _usage_of(obj: dict) -> tuple[int, int, int] | None:
    usage = obj.get("usage") if isinstance(obj, dict) else None
    if not isinstance(usage, dict):
        return None
    inp = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    out = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    cached = int((details or {}).get("cached_tokens") or 0)
    return inp, cached, out


def build_proxy_app(settings: ProxySettings) -> Starlette:
    resolve_container = settings.resolve_container or _ContainerAddresses()
    clients: dict[int, httpx.AsyncClient] = {}

    def http() -> httpx.AsyncClient:
        # One client per event loop (the listener's loop is re-created if it restarts).
        loop_id = id(asyncio.get_running_loop())
        if loop_id not in clients:
            clients[loop_id] = httpx.AsyncClient(timeout=httpx.Timeout(connect=15.0, read=300.0, write=60.0, pool=15.0), transport=settings.transport)
        return clients[loop_id]

    def refuse(claims: tokens.JobClaims | None, peer: str, status: int, reason: str, model: str = "") -> JSONResponse:
        if claims is not None:
            settings.store.record_call(job_id=claims.job_id, container=claims.container, model=model, status="refused", reason=reason)
        _policy_log(settings.policy_log, {"decision": "refused", "reason": reason, "job_id": claims.job_id if claims else None, "thread_id": claims.thread_id if claims else None, "peer": peer})
        return _error(status, f"Refused by the OmniHarness gateway: {reason}")

    async def health(_: Request) -> Response:
        return JSONResponse({"ok": True})

    def authenticate(request: Request) -> tuple[tokens.JobClaims | None, JSONResponse | None, str]:
        peer = request.client.host if request.client else ""
        if settings.subnets:
            try:
                if not any(ipaddress.IPv4Address(peer) in net for net in settings.subnets):
                    return None, refuse(None, peer, 403, "not from the sandbox network"), peer
            except ValueError:
                return None, refuse(None, peer, 403, "not from the sandbox network"), peer
        auth = request.headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        try:
            claims = tokens.verify(token)
        except tokens.TokenError as exc:
            return None, refuse(None, peer, 401, f"invalid job token ({exc})"), peer
        if resolve_container(claims.container) != peer:
            return None, refuse(claims, peer, 403, "the token belongs to another sandbox"), peer
        return claims, None, peer

    async def models(request: Request) -> Response:
        claims, err, _ = authenticate(request)
        if err is not None:
            return err
        return JSONResponse({"object": "list", "data": [{"id": WORKER_MODEL, "object": "model", "owned_by": "omni-harness"}]})

    async def chat(request: Request) -> Response:
        claims, err, peer = authenticate(request)
        if err is not None:
            return err
        assert claims is not None
        length = int(request.headers.get("content-length") or 0)
        if length > settings.max_request_bytes:
            return refuse(claims, peer, 413, "request too large")
        raw = await request.body()
        if len(raw) > settings.max_request_bytes:
            return refuse(claims, peer, 413, "request too large")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            return refuse(claims, peer, 400, "the body is not JSON")
        if not isinstance(body, dict) or body.get("model") != WORKER_MODEL:
            return refuse(claims, peer, 400, f"only the model {WORKER_MODEL!r} is allowed", model=str(body.get("model") if isinstance(body, dict) else ""))
        if settings.store.calls_since(claims.container, time.time() - 60) >= settings.rate_per_minute:
            return refuse(claims, peer, 429, f"rate limit ({settings.rate_per_minute} calls a minute)")
        reason = settings.store.reserve_call(job_id=claims.job_id, monthly_cap_usd=settings.monthly_cap_usd)
        if reason:
            return refuse(claims, peer, 402, reason)
        upstream, why = settings.upstream_for()
        if upstream is None:
            return refuse(claims, peer, 503, why or "no model available")

        payload = _normalise_body(body, upstream)
        headers = {"content-type": "application/json", "authorization": f"Bearer {upstream.api_key}"}
        url = f"{upstream.base_url}/chat/completions"
        started = time.monotonic()
        try:
            client = http()
            upstream_request = client.build_request("POST", url, headers=headers, json=payload)
            resp = await client.send(upstream_request, stream=True)
        except httpx.HTTPError as exc:
            settings.store.record_call(job_id=claims.job_id, container=claims.container, model=upstream.model, status="error", reason=type(exc).__name__)
            _policy_log(settings.policy_log, {"decision": "error", "reason": type(exc).__name__, "job_id": claims.job_id, "thread_id": claims.thread_id, "model": upstream.model})
            return _error(502, "The model provider could not be reached.", "omni_upstream")

        def finish(status: str, usage: tuple[int, int, int] | None, reason: str | None = None) -> None:
            inp, cached, out = usage or (0, 0, 0)
            cost = cost_usd(upstream.model, input_tokens=inp, cached_tokens=cached, output_tokens=out, overrides=settings.prices)
            latency = int((time.monotonic() - started) * 1000)
            settings.store.record_call(job_id=claims.job_id, container=claims.container, model=upstream.model, status=status, input_tokens=inp, cached_tokens=cached, output_tokens=out, cost_usd=cost, latency_ms=latency, reason=reason)
            entry = {"decision": "allowed", "status": status, "job_id": claims.job_id, "thread_id": claims.thread_id, "model": upstream.model}
            entry.update(input_tokens=inp, cached_tokens=cached, output_tokens=out, cost_usd=round(cost, 6), latency_ms=latency, reason=reason)
            _policy_log(settings.policy_log, entry)

        if resp.status_code != 200:
            detail = (await resp.aread())[:4000]
            await resp.aclose()
            finish("error", None, f"provider status {resp.status_code}")
            return Response(detail, status_code=resp.status_code, media_type=resp.headers.get("content-type", "application/json"))

        if not payload.get("stream"):
            data = await resp.aread()
            await resp.aclose()
            try:
                usage = _usage_of(json.loads(data))
            except json.JSONDecodeError:
                usage = None
            finish("ok", usage)
            return Response(data, status_code=200, media_type="application/json")

        async def relay() -> AsyncIterator[bytes]:
            usage: tuple[int, int, int] | None = None
            buffer = b""
            status, reason = "ok", None
            try:
                async for chunk in resp.aiter_bytes():
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        text = line.strip()
                        if text.startswith(b"data:") and b'"usage"' in text:
                            try:
                                found = _usage_of(json.loads(text[5:].strip()))
                            except (json.JSONDecodeError, ValueError):
                                found = None
                            if found:
                                usage = found
                    yield chunk
            except (httpx.HTTPError, asyncio.CancelledError) as exc:
                status, reason = "interrupted", type(exc).__name__
                raise
            finally:
                await resp.aclose()
                finish(status, usage, reason)

        return StreamingResponse(relay(), status_code=200, media_type="text/event-stream", headers={"cache-control": "no-cache"})

    async def not_found(request: Request) -> Response:
        return _error(404, "not found")

    app = Starlette(
        routes=[
            Route("/healthz", health, methods=["GET"]),
            Route("/v1/models", models, methods=["GET"]),
            Route("/v1/chat/completions", chat, methods=["POST"]),
            Route("/{path:path}", not_found, methods=["GET", "POST", "PUT", "DELETE", "PATCH"]),
        ]
    )
    return app


class ProxyListener:
    """Runs the proxy on (host, port) if the port is free, in its own thread.

    Its own thread and event loop: uvicorn takes over SIGINT/SIGTERM when it
    serves on the main thread, which would steal the gateway's own shutdown.
    With several gateway workers, the first to bind serves; the others retry,
    so one takes over if it stops. Job state lives in the shared store, so the
    serving worker need not be the one running the job.
    """

    def __init__(self, app: Starlette, host: str, port: int, retry_seconds: float = 10.0) -> None:
        self.app, self.host, self.port, self.retry_seconds = app, host, port, retry_seconds
        self._thread: threading.Thread | None = None
        self._server = None
        self._stop = threading.Event()
        self.serving = False

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="code-job-llm-proxy", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        import uvicorn

        while not self._stop.is_set():
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((self.host, self.port))
            except OSError:
                sock.close()
                self._stop.wait(self.retry_seconds)
                continue
            config = uvicorn.Config(self.app, log_level="warning", access_log=False, lifespan="off", timeout_keep_alive=30)
            self._server = uvicorn.Server(config)
            self.serving = True
            logger.info("code jobs: LLM proxy listening on %s:%s (sandbox network only)", self.host, self.port)
            try:
                asyncio.run(self._server.serve(sockets=[sock]))
            except Exception:  # noqa: BLE001 - logged; the loop retries
                logger.exception("code jobs: the LLM proxy stopped")
            finally:
                self.serving = False
                sock.close()

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
