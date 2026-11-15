"""The locked frame's view token (Spec 012 Slice 2).

Not a JWT and not under the session secret: an HMAC-SHA256 under a key
derived for this one purpose ("artifact-frame-v1"), over owner, artifact,
version, expiry and a random nonce. Only the frame route verifies it, and
the store records the nonce on first use (any worker): a token serves ONE
document. What the frame can read from its own URL afterwards is worthless.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from app.gateway.auth.derived import derived_key

PURPOSE = "artifact-frame-v1"
#: A token not used within this long is void (the host asks for one right
#: before it creates the frame).
SECONDS = 120


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def mint(owner: str, artifact_id: str, n: int, *, now: float | None = None) -> str:
    payload = {"o": owner, "a": artifact_id, "n": n, "e": int((now or time.time()) + SECONDS), "x": secrets.token_urlsafe(18)}
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    mac = _b64(hmac.new(derived_key(PURPOSE), body.encode(), hashlib.sha256).digest())
    return f"{body}.{mac}"


def verify(token: str | None, owner: str, artifact_id: str, n: int, *, now: float | None = None) -> dict | None:
    """The payload when the token is genuine, unexpired and for exactly this
    owner, artifact and version; else None. (Single use is the store's.)"""
    if not token or len(token) > 512 or token.count(".") != 1:
        return None
    body, mac = token.split(".")
    want = _b64(hmac.new(derived_key(PURPOSE), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(want, mac):
        return None
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("o") != owner or payload.get("a") != artifact_id or payload.get("n") != n:
        return None
    if not isinstance(payload.get("e"), int) or payload["e"] < (now or time.time()) or not isinstance(payload.get("x"), str):
        return None
    return payload
