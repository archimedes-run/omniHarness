from pydantic import BaseModel, Field


class McpBuilderConfig(BaseModel):
    """Feature flag + knobs for the MCP-builder subsystem."""

    enabled: bool = Field(
        default=False,
        description="Gate all MCP builder endpoints and functionality.",
    )
