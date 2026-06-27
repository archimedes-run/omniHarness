from pydantic import BaseModel, Field


class WorkflowsConfig(BaseModel):
    """Feature flag for the Workflows domain. Defaults OFF."""

    enabled: bool = Field(default=False, description="Enable the Workflows API and UI (Phase 0 skeleton).")
