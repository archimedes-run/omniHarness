"""Security helpers for sandbox capability gating."""

from omniharness.config import get_app_config

_LOCAL_SANDBOX_PROVIDER_MARKERS = (
    "omniharness.sandbox.local:LocalSandboxProvider",
    "omniharness.sandbox.local.local_sandbox_provider:LocalSandboxProvider",
)

LOCAL_HOST_BASH_DISABLED_MESSAGE = "Running commands on the host was removed: it is not a sandbox boundary. Commands run only in a container sandbox; switch sandbox.use to AioSandboxProvider."

LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE = "The bash subagent needs a container sandbox: running commands on the host was removed. Switch sandbox.use to AioSandboxProvider."


def uses_local_sandbox_provider(config=None) -> bool:
    """Return True when the active sandbox provider is the host-local provider."""
    if config is None:
        config = get_app_config()

    sandbox_cfg = getattr(config, "sandbox", None)
    sandbox_use = getattr(sandbox_cfg, "use", "")
    if sandbox_use in _LOCAL_SANDBOX_PROVIDER_MARKERS:
        return True
    return sandbox_use.endswith(":LocalSandboxProvider") and "omniharness.sandbox.local" in sandbox_use


def is_host_bash_allowed(config=None) -> bool:
    """Return whether host bash execution is explicitly allowed."""
    if config is None:
        config = get_app_config()

    sandbox_cfg = getattr(config, "sandbox", None)
    if sandbox_cfg is None:
        return False
    # Commands run only in a container sandbox; the host-local provider never
    # executes them (security baseline: host execution removed, no opt-in).
    return not uses_local_sandbox_provider(config)
