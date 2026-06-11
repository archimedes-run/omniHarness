from pydantic import BaseModel, Field


class McpBuilderConfig(BaseModel):
    """Feature flag + knobs for the MCP-builder subsystem."""

    enabled: bool = Field(
        default=False,
        description="Gate all MCP builder endpoints and functionality.",
    )
    vault_key: str | None = Field(
        default=None,
        description=("URL-safe base64-encoded 32-byte Fernet key for encrypting MCP secrets. Must be set in non-dev mode; if absent with dev_mode=True an ephemeral key is generated at startup (secrets are lost on restart)."),
    )
    dev_mode: bool = Field(
        default=False,
        description=("Allow an ephemeral (per-process) Fernet key when vault_key is absent. Encrypted secrets do NOT survive a process restart. Never use in production."),
    )
