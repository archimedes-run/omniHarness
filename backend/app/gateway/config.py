import os

from pydantic import BaseModel, Field


class GatewayConfig(BaseModel):
    """Configuration for the API Gateway."""

    host: str = Field(default="127.0.0.1", description="Configured host (GATEWAY_HOST). Informational: uvicorn's --host decides the bind; see actual_bind()")
    port: int = Field(default=8001, description="Port to bind the gateway server")
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"], description="Allowed CORS origins")
    enable_docs: bool = Field(default=True, description="Enable Swagger/ReDoc/OpenAPI endpoints")


_gateway_config: GatewayConfig | None = None


def get_gateway_config() -> GatewayConfig:
    """Get gateway config, loading from environment if available."""
    global _gateway_config
    if _gateway_config is None:
        cors_origins_str = os.getenv("GATEWAY_CORS_ORIGINS") or os.getenv("CORS_ORIGINS", "http://localhost:3000")
        _gateway_config = GatewayConfig(
            host=os.getenv("GATEWAY_HOST", "127.0.0.1"),
            port=int(os.getenv("GATEWAY_PORT", "8001")),
            cors_origins=[origin.strip() for origin in cors_origins_str.split(",") if origin.strip()],
            enable_docs=os.getenv("GATEWAY_ENABLE_DOCS", "true").lower() == "true",
        )
    return _gateway_config


def actual_bind(argv: list[str] | None = None) -> tuple[str, int] | None:
    """The address this process's uvicorn was told to bind, from its command line.

    The gateway does not choose its own socket: the uvicorn CLI does
    (``--host``/``--port``, defaulting to 127.0.0.1:8000). Logging the config
    value instead reported 0.0.0.0 whatever the real bind was. None when this
    process was not started by the uvicorn CLI (tests, embedded use).
    """
    import sys

    args = list(sys.argv if argv is None else argv)
    if not args or "uvicorn" not in os.path.basename(args[0]) and "uvicorn" not in args[:3]:
        return None
    host, port = "127.0.0.1", 8000
    for i, arg in enumerate(args):
        for flag in ("--host", "--port"):
            value = None
            if arg == flag and i + 1 < len(args):
                value = args[i + 1]
            elif arg.startswith(flag + "="):
                value = arg.split("=", 1)[1]
            if value is not None:
                if flag == "--host":
                    host = value
                else:
                    port = int(value)
    return host, port


def published_address_warning(environ: dict | None = None) -> str | None:
    """The compose nginx publish address (BIND_ADDR, passed to the gateway so
    it can say so) when it is NOT loopback: then the app is reachable from the
    network. None when loopback or unset (the default is 127.0.0.1)."""
    env = os.environ if environ is None else environ
    bind = (env.get("BIND_ADDR") or "").strip()
    if not bind or bind in ("127.0.0.1", "::1", "[::1]", "localhost"):
        return None
    return f"The app is published on {bind} (BIND_ADDR), not loopback: anyone who can reach that address can reach the login page."


#: Host names the gateway answers to (port ignored). Loopback for the browser
#: and local callers, `gateway` for containers on the compose network,
#: host.docker.internal for a containerised caller of a host gateway. Anything
#: else is DNS rebinding (a page whose own name now points at 127.0.0.1) and
#: gets 421. Add a LAN name with GATEWAY_ALLOWED_HOSTS if you publish beyond
#: loopback (BIND_ADDR).
DEFAULT_ALLOWED_HOSTS = ("localhost", "127.0.0.1", "[::1]", "gateway", "host.docker.internal")


def allowed_hosts(environ: dict | None = None) -> frozenset[str]:
    env = os.environ if environ is None else environ
    extra = [h.strip().lower() for h in (env.get("GATEWAY_ALLOWED_HOSTS") or "").split(",") if h.strip()]
    return frozenset(DEFAULT_ALLOWED_HOSTS) | frozenset(extra)


class HostGuardMiddleware:
    """421 for a Host header the gateway does not serve (pure ASGI)."""

    def __init__(self, app, hosts: frozenset[str]) -> None:
        self.app = app
        self.hosts = hosts

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        host = ""
        for key, value in scope.get("headers", []):
            if key == b"host":
                host = value.decode("latin1").strip().lower()
                break
        name = host.split("]", 1)[0] + "]" if host.startswith("[") else host.rsplit(":", 1)[0]
        if name not in self.hosts:
            if scope["type"] == "websocket":
                return await send({"type": "websocket.close", "code": 1008})
            await send({"type": "http.response.start", "status": 421, "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"Invalid Host header"})
            return
        return await self.app(scope, receive, send)
