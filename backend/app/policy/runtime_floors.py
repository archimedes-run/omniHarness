"""Tiers that depend on where a tool runs, not only on its name.

`bash` is Tier 2 in the rules because it runs in the hardened container
sandbox: the local container backend, which keys every sandbox (#98), runs it
under the default seccomp profile (#99), and gives it no way out but the
registries proxy. Anywhere else (a provisioner sandbox, no egress proxy
configured) none of that holds, so bash asks first: Tier 3. A floor only
raises a tier, never lowers it.

`code_job` (spec 009) has the same floor: it is offered only in the hardened
sandbox, and if it were ever reached anywhere else it asks first.
"""

from __future__ import annotations

from .models import Tier

_CONTAINER_PROVIDER_SUFFIX = ":AioSandboxProvider"


def bash_runs_in_the_hardened_sandbox() -> bool:
    from omniharness.config import get_app_config

    try:
        sandbox = getattr(get_app_config(), "sandbox", None)
    except Exception:  # noqa: BLE001 - no readable config: not hardened
        return False
    use = str(getattr(sandbox, "use", "") or "")
    if not use.endswith(_CONTAINER_PROVIDER_SUFFIX) or "aio_sandbox" not in use:
        return False
    extra = getattr(sandbox, "model_extra", None) or {}
    if getattr(sandbox, "provisioner_url", None) or extra.get("provisioner_url"):
        return False  # remote sandboxes: not keyed or confined by this gateway
    from omniharness.community.aio_sandbox.local_backend import sandbox_egress, sandbox_network
    from omniharness.community.aio_sandbox.sandbox_auth import key_secret

    return sandbox_network() is not None and sandbox_egress() is not None and bool(key_secret())


def runtime_floor(canonical_name: str) -> Tier | None:
    if canonical_name in ("bash", "code_job") and not bash_runs_in_the_hardened_sandbox():
        return Tier.TIER_3
    return None
