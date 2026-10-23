"""Per-sandbox API keys (#98).

Every sandbox shares one internal Docker network, and the AIO API on :8080
runs shell commands. Without a key, code in one thread's sandbox could exec in
another's. Each container now starts with its own SANDBOX_API_KEY, derived
from the gateway's internal secret and the container name:

* every gateway worker, and a restarted gateway, derives the same key for a
  container it adopts, so nothing is stored;
* a sandbox knows only its own key and never the secret, so it cannot derive
  another sandbox's.

No secret, no sandbox: starting one without it is refused.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

SECRET_ENV = "OMNI_HARNESS_INTERNAL_AUTH_TOKEN"
HEADER = "X-AIO-API-Key"
CONTAINER_ENV = "SANDBOX_API_KEY"

REFUSED_WITHOUT_SECRET = f"Refusing to use a sandbox container: its API key is derived from {SECRET_ENV}, which is not set, and an unkeyed sandbox can be driven by any other sandbox on its network."


def sandbox_api_key(container_name: str) -> str:
    secret = os.environ.get(SECRET_ENV, "")
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
