"""Per-job LLM proxy tokens (spec 009 FR-003).

A token names one job, the one sandbox container it may be used from, and an
expiry, signed with a key derived from the gateway's internal secret in its
own domain (`sandbox-llm|`, beside #98's `sandbox-api-key|`). It is not a
provider key: it authorises nothing but model calls for that job, through the
proxy, within the job's budget, while the job is running. Every gateway worker
derives the same key, so a token minted by one worker verifies in another.

Format: ``ohjob1.<b64url(json payload)>.<b64url(hmac-sha256)>``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from omniharness.community.aio_sandbox.sandbox_auth import key_secret

PREFIX = "ohjob1"
DOMAIN = b"sandbox-llm|v1"


class TokenError(Exception):
    pass


@dataclass(frozen=True)
class JobClaims:
    job_id: str
    container: str
    thread_id: str
    expires_at: int


def _key() -> bytes:
    secret = key_secret()
    if not secret:
        raise TokenError("no gateway secret to derive job tokens from")
    return hmac.new(secret.encode(), DOMAIN, hashlib.sha256).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def mint(*, job_id: str, container: str, thread_id: str, ttl_seconds: int, now: float | None = None) -> str:
    issued = int(now if now is not None else time.time())
    payload = json.dumps({"j": job_id, "c": container, "t": thread_id, "e": issued + int(ttl_seconds)}, separators=(",", ":"), sort_keys=True).encode()
    body = f"{PREFIX}.{_b64(payload)}"
    sig = hmac.new(_key(), body.encode(), hashlib.sha256).digest()
    token = f"{body}.{_b64(sig)}"
    from omniharness.utils.known_secrets import register_secret

    register_secret(token, "code-job-token")
    return token


def verify(token: str, *, now: float | None = None) -> JobClaims:
    parts = (token or "").split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        raise TokenError("malformed token")
    body = f"{parts[0]}.{parts[1]}"
    expected = hmac.new(_key(), body.encode(), hashlib.sha256).digest()
    try:
        given = _unb64(parts[2])
        payload = json.loads(_unb64(parts[1]))
    except (ValueError, json.JSONDecodeError) as exc:
        raise TokenError("malformed token") from exc
    if not hmac.compare_digest(expected, given):
        raise TokenError("bad signature")
    if not isinstance(payload, dict) or not all(isinstance(payload.get(k), str) and payload.get(k) for k in ("j", "c", "t")) or not isinstance(payload.get("e"), int):
        raise TokenError("malformed claims")
    if payload["e"] < int(now if now is not None else time.time()):
        raise TokenError("expired")
    return JobClaims(job_id=payload["j"], container=payload["c"], thread_id=payload["t"], expires_at=payload["e"])
