from pydantic import BaseModel, Field


class McpBuilderConfig(BaseModel):
    """Feature flag + knobs for the MCP-builder subsystem."""

    enabled: bool = Field(
        default=False,
        description="Gate all MCP builder endpoints and functionality.",
    )
    vault_key: str | None = Field(
        default=None,
        description=("NO LONGER ACCEPTED (#59): the key may not live in config.yaml. If set, the gateway refuses to start and names the migration (`make vault-key-migrate`)."),
    )
    vault_key_file: str | None = Field(
        default=None,
        description=("Path to the vault key file (mode 0600, outside the project and OMNI_HARNESS_HOME). Default: $OMNI_HARNESS_MCP_VAULT_KEY_FILE, else /run/secrets/mcp_vault_key (the compose secret). Create it with `make vault-key`."),
    )
    dev_mode: bool = Field(
        default=False,
        description="Ignored since #59: there is no ephemeral or in-repo key any more.",
    )
    reconcile_on_start: bool = Field(
        default=True,
        description="Turn off built servers whose running code is not the approved version, and run the one-time retirement, at startup (#59).",
    )
