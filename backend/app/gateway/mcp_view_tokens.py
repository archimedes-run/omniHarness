""" "The code was viewed" as something the gateway observed (#59).

``GET /servers/{id}/approval`` hands out the code with a view token: random,
bound to (server, user, code hash), single-use, short-lived, kept in memory.
``POST /servers/{id}/enable`` must present it, so an approval can only be for
code that was fetched for review by that user, in that version.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass

#: How long a viewed packet stays approvable.
VIEW_TOKEN_TTL_SECONDS = 15 * 60


@dataclass(frozen=True)
class _Issued:
    server_id: str
    user_id: str
    code_sha256: str
    expires_at: float


class ViewTokens:
    def __init__(self, ttl_seconds: float = VIEW_TOKEN_TTL_SECONDS, clock=time.monotonic) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._issued: dict[str, _Issued] = {}
        self._lock = threading.Lock()

    def issue(self, *, server_id: str, user_id: str, code_sha256: str) -> tuple[str, float]:
        """A new token for this user viewing this code; returns (token, ttl seconds)."""
        token = secrets.token_urlsafe(32)
        with self._lock:
            now = self._clock()
            self._issued = {t: i for t, i in self._issued.items() if i.expires_at > now}
            self._issued[token] = _Issued(server_id, user_id, code_sha256, now + self._ttl)
        return token, self._ttl

    def consume(self, token: str | None, *, server_id: str, user_id: str, code_sha256: str) -> str | None:
        """Use a token once. Returns None when valid, else the reason it is not."""
        if not token:
            return "Open the code first: approval needs the code to have been shown to you."
        with self._lock:
            issued = self._issued.pop(token, None)
        if issued is None:
            return "That review has already been used or never existed; open the code again."
        if issued.expires_at <= self._clock():
            return "That review expired; open the code again."
        if issued.user_id != user_id or issued.server_id != server_id:
            return "That review was not yours for this server; open the code again."
        if issued.code_sha256 != code_sha256:
            return "The code changed since you opened it; review it again."
        return None
