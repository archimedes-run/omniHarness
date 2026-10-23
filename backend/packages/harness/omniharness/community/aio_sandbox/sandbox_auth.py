"""Per-sandbox API keys (#98).

Every sandbox shares one internal Docker network, and the AIO API on :8080
runs shell commands. Without a key, code in one thread's sandbox could exec in
another's. Each container now starts with its own SANDBOX_API_KEY, derived
from the gateway's internal secret and the container name:

* every gateway worker, and a restarted gateway, derives the same key for a
  container it adopts, so nothing is stored. The root is the internal token
  when it is configured, else AUTH_JWT_SECRET: both come from .env and are the
  same in every worker (an unset internal token is random per process, which
  would key each worker's sandboxes differently);
* a sandbox knows only its own key and never the secret, so it cannot derive
  another sandbox's.

No secret, no sandbox: starting one without it is refused.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

SECRET_ENVS = ("OMNI_HARNESS_INTERNAL_AUTH_TOKEN", "AUTH_JWT_SECRET")
HEADER = "X-AIO-API-Key"
CONTAINER_ENV = "SANDBOX_API_KEY"

REFUSED_WITHOUT_SECRET = f"Refusing to use a sandbox container: its API key is derived from {' or '.join(SECRET_ENVS)}, neither is set, and an unkeyed sandbox can be driven by any other sandbox on its network."


def key_secret() -> str:
    """The root the keys are derived from ("" when there is none)."""
    for name in SECRET_ENVS:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def sandbox_api_key(container_name: str) -> str:
    secret = key_secret()
    if not secret:
        raise RuntimeError(REFUSED_WITHOUT_SECRET)
    digest = hmac.new(secret.encode(), f"sandbox-api-key|{container_name}".encode(), hashlib.sha256).digest()
    key = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    from omniharness.utils.known_secrets import register_secret

    register_secret(key, "sandbox-api-key")
    return key


def auth_headers(container_name: str | None) -> dict[str, str]:
    """Headers for a local container's API; none for a remote (provisioner) sandbox."""
    if not container_name:
        return {}
    return {HEADER: sandbox_api_key(container_name)}
