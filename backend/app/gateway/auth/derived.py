"""Purpose-bound keys derived from the auth secret.

The session secret signs session tokens ONLY (auth/jwt.py, `typ: session`).
Anything else the gateway signs (a preview link, a frame view token) uses a
key derived for that one purpose, so it can never be replayed as a session
and a leak of one kind of token gives nothing for another.
"""

from __future__ import annotations

import hashlib
import hmac

from app.gateway.auth.config import get_auth_config


def derived_key(purpose: str) -> bytes:
    """HMAC-SHA256(secret, "omniharness:" + purpose): a fixed key per purpose."""
    secret = get_auth_config().jwt_secret.encode("utf-8")
    return hmac.new(secret, f"omniharness:{purpose}".encode(), hashlib.sha256).digest()
