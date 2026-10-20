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
