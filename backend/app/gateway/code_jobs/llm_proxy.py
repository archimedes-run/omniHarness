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
import re
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
from .pricing import cost_usd, price_for
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
    max_concurrent_calls: int = 3
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


#: Request keys passed to the provider; everything else is dropped (no `n`,
#: `store`, `service_tier`, `metadata`, `audio`, `modalities`, `prediction`,
#: logprobs, web search options...), whatever the worker or a project config
#: adds. Output length is set by the proxy, never by the worker.
ALLOWED_KEYS = frozenset(
    {
        "messages",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "stream",
        "temperature",
        "top_p",
        "stop",
        "response_format",
        "reasoning_effort",
        "seed",
        "frequency_penalty",
        "presence_penalty",
    }
)
#: The most output one call may ask for.
OUTPUT_CAP = 32_000
#: The input estimate is a true upper bound: one token per byte of request
#: (no tokenizer encodes more than one token per byte), images aside.
BYTES_PER_TOKEN = 1
#: An inline image (data: URI) may be at most this many characters.
MAX_IMAGE_CHARS = 5 * 1024 * 1024
#: Each image is reserved at this many input tokens (a conservative figure
#: above what the providers' tiling charges for the largest image allowed).
IMAGE_TOKENS = 20_000
_DATA_IMAGE = re.compile(r"^data:image/(png|jpeg|gif|webp);base64,[A-Za-z0-9+/=\s]*$")
_ROLES = frozenset({"system", "developer", "user", "assistant", "tool"})
_FUNCTION_KEYS = frozenset({"name", "description", "parameters", "strict"})


class ContentRefused(ValueError):
    pass


def _text(value: object, what: str) -> str:
    if not isinstance(value, str):
        raise ContentRefused(f"{what} must be text")
    return value


def _content(content: object, counter: dict) -> object:
    """Message content: text, or a list of `text` parts and bounded inline
    images. A remote image URL, a file, audio or any other part type is
    refused: the provider would fetch or read something the worker chose."""
    if content is None or isinstance(content, str):
        return content
    if isinstance(content, dict):
        content = [content]
    if not isinstance(content, list):
        raise ContentRefused("message content must be text or a list of parts")
    out = []
    for part in content:
        if not isinstance(part, dict):
            raise ContentRefused("a content part must be an object")
        kind = part.get("type")
        if kind == "text":
            out.append({"type": "text", "text": _text(part.get("text", ""), "a text part")})
            continue
        if kind == "image_url":
            image = part.get("image_url")
            url = image.get("url") if isinstance(image, dict) else image
            if not isinstance(url, str) or len(url) > MAX_IMAGE_CHARS + 1 or not _DATA_IMAGE.match(url):
                raise ContentRefused("only inline images (data:image/png|jpeg|gif|webp;base64) are allowed, never a URL")
            if len(url) > MAX_IMAGE_CHARS:
                raise ContentRefused("an inline image is too large")
            counter["images"] += 1
            counter["image_chars"] += len(url)
            entry: dict = {"url": url}
            if isinstance(image, dict) and image.get("detail") in ("auto", "low", "high"):
                entry["detail"] = image["detail"]
            out.append({"type": "image_url", "image_url": entry})
            continue
        raise ContentRefused(f"content parts of type {str(kind)[:40]!r} are not allowed")
    return out


def _tool_call(call: object) -> dict:
    if not isinstance(call, dict) or call.get("type", "function") != "function" or not isinstance(call.get("function"), dict):
        raise ContentRefused("only function tool calls are allowed")
    fn = call["function"]
    return {"id": _text(call.get("id", ""), "a tool call id"), "type": "function", "function": {"name": _text(fn.get("name"), "a function name"), "arguments": _text(fn.get("arguments", ""), "function arguments")}}


def _message(message: object, counter: dict) -> dict:
    """Only the keys a chat message needs; anything else is dropped."""
    if not isinstance(message, dict):
        raise ContentRefused("a message must be an object")
    role = message.get("role")
    if role not in _ROLES:
        raise ContentRefused(f"a message role must be one of {sorted(_ROLES)}")
    out: dict = {"role": role, "content": _content(message.get("content"), counter)}
    if isinstance(message.get("name"), str):
        out["name"] = message["name"]
    if role == "assistant" and message.get("tool_calls") is not None:
        calls = message["tool_calls"]
        if not isinstance(calls, list):
            raise ContentRefused("tool_calls must be a list")
        out["tool_calls"] = [_tool_call(c) for c in calls]
    if role == "tool":
        out["tool_call_id"] = _text(message.get("tool_call_id", ""), "a tool_call_id")
    return out


def _tool(tool: object) -> dict:
    """Function tools only: a provider's own server-side tools (web search,
    browsing, code execution, retrieval) would reach outside the sandbox."""
    if not isinstance(tool, dict) or tool.get("type") != "function" or set(tool) - {"type", "function"}:
        raise ContentRefused("only function tools are allowed")
    fn = tool.get("function")
    if not isinstance(fn, dict) or set(fn) - _FUNCTION_KEYS or not isinstance(fn.get("name"), str):
        raise ContentRefused("a function tool may hold only name, description, parameters and strict")
    return {"type": "function", "function": dict(fn)}


def _tool_choice(choice: object) -> object:
    if choice in ("auto", "none", "required"):
        return choice
    if isinstance(choice, dict) and choice.get("type") == "function" and set(choice) == {"type", "function"}:
        fn = choice["function"]
        if isinstance(fn, dict) and set(fn) == {"name"} and isinstance(fn["name"], str):
            return {"type": "function", "function": {"name": fn["name"]}}
    raise ContentRefused("tool_choice must be auto, none, required or a function by name")


def sanitize_request(body: dict) -> tuple[dict, dict]:
    """The request the provider will see, rebuilt from allowed pieces only;
    raises ContentRefused for anything that could reach outside the sandbox.
    Returns (request fields, {"images": n, "image_chars": n})."""
    counter = {"images": 0, "image_chars": 0}
    messages = body.get("messages")
    if not isinstance(messages, list):
        raise ContentRefused("messages must be a list")
    clean: dict = {k: v for k, v in body.items() if k in ALLOWED_KEYS and k not in ("messages", "tools", "tool_choice")}
    clean["messages"] = [_message(m, counter) for m in messages]
    if body.get("tools") is not None:
        if not isinstance(body["tools"], list):
            raise ContentRefused("tools must be a list")
        clean["tools"] = [_tool(t) for t in body["tools"]]
    if body.get("tool_choice") is not None:
        clean["tool_choice"] = _tool_choice(body["tool_choice"])
    return clean, counter


def _normalise_body(clean: dict, upstream: Upstream, output_tokens: int) -> dict:
    out = dict(clean)
    out["model"] = upstream.model
    if out.get("stream"):
        out["stream_options"] = {"include_usage": True}
    if upstream.reasoning_model:
        # Reasoning models refuse max_tokens and any non-default sampling.
        out["max_completion_tokens"] = output_tokens
        for key in ("temperature", "top_p"):
            if key in out and out[key] not in (None, 1, 1.0):
                out.pop(key)
    else:
        out["max_tokens"] = output_tokens
    return out


def _requested_output(body: dict) -> int:
    for key in ("max_completion_tokens", "max_tokens"):
        value = body.get(key)
        if isinstance(value, int) and value > 0:
            return min(value, OUTPUT_CAP)
    return OUTPUT_CAP


def _usage_of(obj: dict) -> tuple[int, int, int] | None:
    usage = obj.get("usage") if isinstance(obj, dict) else None
    if not isinstance(usage, dict):
        return None
    inp = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    out = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    cached = int((details or {}).get("cached_tokens") or 0)
    return inp, cached, out


class _RefusalLog:
    """Unauthenticated refusals are logged at most once a minute per caller
    address, with how many there were, so a flood cannot fill the log."""

    def __init__(self, every: float = 60.0) -> None:
        self.every = every
        self._seen: dict[str, tuple[float, int]] = {}

    def due(self, peer: str) -> int | None:
        now = time.monotonic()
        last, count = self._seen.get(peer, (0.0, 0))
        if now - last >= self.every:
            self._seen[peer] = (now, 0)
            if len(self._seen) > 4096:
                self._seen.clear()
            return count + 1
        self._seen[peer] = (last, count + 1)
        return None


def build_proxy_app(settings: ProxySettings) -> Starlette:
    resolve_container = settings.resolve_container or _ContainerAddresses()
    clients: dict[int, httpx.AsyncClient] = {}
    refusal_log = _RefusalLog()

    def http() -> httpx.AsyncClient:
        # One client per event loop (the listener's loop is re-created if it restarts).
        loop_id = id(asyncio.get_running_loop())
        if loop_id not in clients:
            clients[loop_id] = httpx.AsyncClient(timeout=httpx.Timeout(connect=15.0, read=300.0, write=60.0, pool=15.0), transport=settings.transport)
        return clients[loop_id]

    def refuse(claims: tokens.JobClaims | None, peer: str, status: int, reason: str, model: str = "") -> JSONResponse:
        if claims is not None:
            # Refusals count toward the sandbox's rate; past it, a flood is
            # answered 429 without writing a row each time, and logged once a minute.
            if settings.store.recent_calls(claims.container) >= settings.rate_per_minute:
                if (count := refusal_log.due(f"token:{claims.container}")) is not None:
                    _policy_log(settings.policy_log, {"decision": "refused", "reason": "rate limit (refusals)", "job_id": claims.job_id, "thread_id": claims.thread_id, "peer": peer, "count": count})
                return _error(429, f"Refused by the OmniHarness gateway: rate limit ({settings.rate_per_minute} calls a minute)")
            settings.store.record_call(job_id=claims.job_id, container=claims.container, model=model, status="refused", reason=reason)
            if (count := refusal_log.due(f"token:{claims.container}:{reason[:40]}")) is not None:
                _policy_log(settings.policy_log, {"decision": "refused", "reason": reason, "job_id": claims.job_id, "thread_id": claims.thread_id, "peer": peer, "count": count})
        elif (count := refusal_log.due(peer)) is not None:
            _policy_log(settings.policy_log, {"decision": "refused", "reason": reason, "job_id": None, "thread_id": None, "peer": peer, "count": count})
        return _error(status, f"Refused by the OmniHarness gateway: {reason}")

    async def health(_: Request) -> Response:
        return JSONResponse({"ok": True})

    def authenticate(request: Request) -> tuple[tokens.JobClaims | None, JSONResponse | None, str]:
        peer = request.client.host if request.client else ""
        # No known sandbox subnet: nothing can be from it (fail closed).
        try:
            inside = any(ipaddress.IPv4Address(peer) in net for net in settings.subnets)
        except ValueError:
            inside = False
        if not inside:
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

    async def read_capped(request: Request) -> bytes | None:
        """The body, read in chunks with a running cap (None: too large)."""
        if int(request.headers.get("content-length") or 0) > settings.max_request_bytes:
            return None
        parts, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > settings.max_request_bytes:
                return None
            parts.append(chunk)
        return b"".join(parts)

    async def chat(request: Request) -> Response:
        claims, err, peer = authenticate(request)
        if err is not None:
            return err
        assert claims is not None
        raw = await read_capped(request)
        if raw is None:
            return refuse(claims, peer, 413, "request too large")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            return refuse(claims, peer, 400, "the body is not JSON")
        if not isinstance(body, dict) or body.get("model") != WORKER_MODEL:
            return refuse(claims, peer, 400, f"only the model {WORKER_MODEL!r} is allowed", model=str(body.get("model") if isinstance(body, dict) else ""))
        upstream, why = settings.upstream_for()
        if upstream is None:
            return refuse(claims, peer, 503, why or "no model available")
        try:
            clean, counted = sanitize_request(body)
        except ContentRefused as exc:
            return refuse(claims, peer, 400, str(exc), model=str(body.get("model")))
        price = price_for(upstream.model, settings.prices)
        input_tokens = (len(raw) - counted["image_chars"]) / BYTES_PER_TOKEN + counted["images"] * IMAGE_TOKENS
        input_cost = input_tokens * price.input / 1_000_000
        call_id, reason, output_tokens = settings.store.reserve_call(
            job_id=claims.job_id,
            container=claims.container,
            model=upstream.model,
            monthly_cap_usd=settings.monthly_cap_usd,
            rate_per_minute=settings.rate_per_minute,
            max_inflight=settings.max_concurrent_calls,
            input_cost_usd=input_cost,
            output_usd_per_token=price.output / 1_000_000,
            requested_output_tokens=_requested_output(body),
        )
        if call_id is None:
            status = 429 if reason and ("rate" in reason or "at once" in reason) else 402
            return refuse(claims, peer, status, reason or "refused", model=upstream.model)

        reserve_estimate = input_cost + output_tokens * price.output / 1_000_000
        payload = _normalise_body(clean, upstream, output_tokens)
        headers = {"content-type": "application/json", "authorization": f"Bearer {upstream.api_key}"}
        url = f"{upstream.base_url}/chat/completions"
        started = time.monotonic()

        def finish(status: str, usage: tuple[int, int, int] | None, reason: str | None = None) -> None:
            cost = None
            if usage is not None:
                inp, cached, out = usage
                cost = cost_usd(upstream.model, input_tokens=inp, cached_tokens=cached, output_tokens=out, overrides=settings.prices)
            latency = int((time.monotonic() - started) * 1000)
            charged = settings.store.settle_call(call_id, status=status, usage=usage, cost_usd=cost, latency_ms=latency, reason=reason)
            inp, cached, out = usage or (0, 0, 0)
            entry = {"decision": "allowed", "status": status, "job_id": claims.job_id, "thread_id": claims.thread_id, "model": upstream.model}
            entry.update(input_tokens=inp, cached_tokens=cached, output_tokens=out, cost_usd=round(charged, 6), estimated=usage is None, latency_ms=latency, reason=reason)
            if cost is not None and cost > reserve_estimate + 1e-9:
                entry["over_reservation"] = True
                logger.warning("llm proxy: a call of job %s cost $%.4f, more than its $%.4f reservation", claims.job_id, cost, reserve_estimate)
            _policy_log(settings.policy_log, entry)

        try:
            client = http()
            upstream_request = client.build_request("POST", url, headers=headers, json=payload)
            resp = await client.send(upstream_request, stream=True)
        except httpx.HTTPError as exc:
            # Nothing reached the provider's output: no charge.
            settings.store.settle_call(call_id, status="error", usage=(0, 0, 0), cost_usd=0.0, reason=type(exc).__name__)
            _policy_log(settings.policy_log, {"decision": "error", "reason": type(exc).__name__, "job_id": claims.job_id, "thread_id": claims.thread_id, "model": upstream.model})
            return _error(502, "The model provider could not be reached.", "omni_upstream")

        if resp.status_code != 200:
            await resp.aclose()
            # A refused request costs nothing; its detail stays in the gateway.
            settings.store.settle_call(call_id, status="error", usage=(0, 0, 0), cost_usd=0.0, reason=f"provider status {resp.status_code}")
            _policy_log(settings.policy_log, {"decision": "error", "reason": f"provider status {resp.status_code}", "job_id": claims.job_id, "thread_id": claims.thread_id, "model": upstream.model})
            return _error(resp.status_code if 400 <= resp.status_code < 600 else 502, f"The model provider refused the request (status {resp.status_code}).", "omni_upstream")

        if not payload.get("stream"):
            try:
                data = await resp.aread()
            except httpx.HTTPError as exc:
                finish("interrupted", None, type(exc).__name__)
                raise
            finally:
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
            completed, reason = False, None
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
                completed = True
            except (httpx.HTTPError, asyncio.CancelledError) as exc:
                reason = type(exc).__name__
                raise
            finally:
                await resp.aclose()
                # Cut short (the caller left, or the provider did): the usage
                # chunk may never have arrived, so the reservation is charged.
                finish("ok" if completed else "interrupted", usage if completed else None, reason if completed else (reason or "the caller disconnected"))

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
