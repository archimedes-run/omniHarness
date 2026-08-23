"""Authentication for Gateway internal callers.

SHARED ACROSS WORKERS, not process-local.

This was `secrets.token_urlsafe(32)` evaluated at import. Under
`uvicorn --workers N` each worker imports the module in its own process, so
each minted a different token — measured on a 3-worker server: 3 workers, 3
distinct tokens, distributing across all three under concurrent load.

Every internal caller reaches the gateway over HTTP loopback, where the kernel
hands the connection to an arbitrary worker. A request therefore had a ~1/N
chance of landing on the worker that minted its token and was rejected 401
otherwise. That is not theoretical: `ChannelManager` authenticates this way, so
Telegram and Slack have been failing intermittently under load. It hid because
light sequential traffic goes to a single accepting worker — twelve sequential
requests all landed on one PID in testing — so it only surfaces under
concurrency, which is also when it is hardest to attribute to a cause.

The token now comes from the environment, which every worker of a given server
inherits. The generated fallback keeps single-process runs (tests, `make dev`,
a developer's laptop) working with no configuration, and is safe there because
one process both mints and validates.
"""

from __future__ import annotations

import logging
import os
import secrets
from types import SimpleNamespace

from omniharness.runtime.user_context import DEFAULT_USER_ID

logger = logging.getLogger(__name__)

INTERNAL_AUTH_HEADER_NAME = "X-OmniHarness-Internal-Token"

#: Set this for any deployment running more than one worker. Workers inherit
#: the environment from the supervisor, so all of them agree.
INTERNAL_AUTH_TOKEN_ENV = "OMNI_HARNESS_INTERNAL_AUTH_TOKEN"


def _resolve_token() -> tuple[str, bool]:
    """Return (token, came_from_environment)."""
    configured = os.environ.get(INTERNAL_AUTH_TOKEN_ENV, "").strip()
    if configured:
        return configured, True
    return secrets.token_urlsafe(32), False


_INTERNAL_AUTH_TOKEN, _FROM_ENV = _resolve_token()

if not _FROM_ENV:
    logger.info(
        "%s is unset; generated a process-local internal auth token. This is correct for a single-worker run. Set it for any deployment running multiple workers, or internal calls will fail across workers.",
        INTERNAL_AUTH_TOKEN_ENV,
    )


def internal_auth_is_shared() -> bool:
    """True when the token came from the environment and is therefore shared by
    every worker of this server. Read by the multi-worker readiness test."""
    return _FROM_ENV


def create_internal_auth_headers() -> dict[str, str]:
    """Return headers that authenticate Gateway internal calls."""
    return {INTERNAL_AUTH_HEADER_NAME: _INTERNAL_AUTH_TOKEN}


def is_valid_internal_auth_token(token: str | None) -> bool:
    """Return True when *token* matches this server's internal token."""
    return bool(token) and secrets.compare_digest(token, _INTERNAL_AUTH_TOKEN)


def get_internal_user():
    """Return the synthetic user used for trusted internal channel calls."""
    return SimpleNamespace(id=DEFAULT_USER_ID, system_role="internal")
