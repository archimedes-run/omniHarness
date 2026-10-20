from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Keys that once let agent commands run on the HOST. Host execution was
#: removed (security baseline); a config that still names one is refused at
#: startup, saying exactly what to delete.
REMOVED_HOST_EXECUTION_KEYS = ("allow_host_bash", "allow_host_bash_unsafe", "host_bash", "allow_host_execution")


class VolumeMountConfig(BaseModel):
    """Configuration for a volume mount."""

    host_path: str = Field(..., description="Path on the host machine")
    container_path: str = Field(..., description="Path inside the container")
    read_only: bool = Field(default=False, description="Whether the mount is read-only")


class SandboxConfig(BaseModel):
    """Config section for a sandbox.

    Common options:
        use: Class path of the sandbox provider (required)
        (Host command execution was removed: commands run only in a container
        sandbox. ``allow_host_bash`` is refused if present.)

    AioSandboxProvider specific options:
        image: Docker image to use (default: ghcr.io/archimedes-run/omni-harness-sandbox:latest)
        port: Base port for sandbox containers (default: 8080)
        replicas: Maximum number of concurrent sandbox containers (default: 3). When the limit is reached the least-recently-used sandbox is evicted to make room.
        container_prefix: Prefix for container names (default: omni-harness-sandbox)
        idle_timeout: Idle timeout in seconds before sandbox is released (default: 600 = 10 minutes). Set to 0 to disable.
        mounts: List of volume mounts to share directories with the container
        environment: Environment variables to inject into the container (values starting with $ are resolved from host env)
    """

    use: str = Field(
        ...,
        description="Class path of the sandbox provider (e.g. omniharness.sandbox.local:LocalSandboxProvider)",
    )
    image: str | None = Field(
        default=None,
        description="Docker image to use for the sandbox container",
    )
    port: int | None = Field(
        default=None,
        description="Base port for sandbox containers",
    )
    replicas: int | None = Field(
        default=None,
        description="Maximum number of concurrent sandbox containers (default: 3). When the limit is reached the least-recently-used sandbox is evicted to make room.",
    )
    container_prefix: str | None = Field(
        default=None,
        description="Prefix for container names",
    )
    idle_timeout: int | None = Field(
        default=None,
        description="Idle timeout in seconds before sandbox is released (default: 600 = 10 minutes). Set to 0 to disable.",
    )
    mounts: list[VolumeMountConfig] = Field(
        default_factory=list,
        description="List of volume mounts to share directories between host and container",
    )
    environment: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables to inject into the sandbox container. Values starting with $ will be resolved from host environment variables.",
    )

    bash_output_max_chars: int = Field(
        default=20000,
        ge=0,
        description="Maximum characters to keep from bash tool output. Output exceeding this limit is middle-truncated (head + tail), preserving the first and last half. Set to 0 to disable truncation.",
    )
    read_file_output_max_chars: int = Field(
        default=50000,
        ge=0,
        description="Maximum characters to keep from read_file tool output. Output exceeding this limit is head-truncated. Set to 0 to disable truncation.",
    )
    ls_output_max_chars: int = Field(
        default=20000,
        ge=0,
        description="Maximum characters to keep from ls tool output. Output exceeding this limit is head-truncated. Set to 0 to disable truncation.",
    )

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def _refuse_host_execution_keys(cls, data):
        if isinstance(data, dict):
            present = [k for k in REMOVED_HOST_EXECUTION_KEYS if k in data]
            if present:
                raise ValueError(
                    f"sandbox.{present[0]} is no longer supported: running agent commands on the host was removed for security, "
                    f"so this key does nothing safe. Delete the line 'sandbox.{present[0]}' from config.yaml. Commands now run only in a "
                    "container sandbox (sandbox.use: omniharness.community.aio_sandbox:AioSandboxProvider)."
                )
        return data
