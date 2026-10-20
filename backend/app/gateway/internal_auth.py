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

import hashlib
import logging
import os
import re
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


def create_internal_auth_headers() -> dict[str, str]:
    """Return headers that authenticate Gateway internal calls."""
    return {INTERNAL_AUTH_HEADER_NAME: _INTERNAL_AUTH_TOKEN}


def is_valid_internal_auth_token(token: str | None) -> bool:
    """Return True when *token* matches this server's internal token."""
    return isinstance(token, str) and bool(token) and secrets.compare_digest(token, _INTERNAL_AUTH_TOKEN)


#: SCHEDULED-RUN GRANTS (security baseline). Only a request carrying a grant
#: the trigger engine issued may mark a turn "synthetic-trigger".
#:
#: Why not a token: the engine runs inside the gateway, but under
#: `uvicorn --workers N` its loopback call lands on ANY worker, so a secret held
#: in one process cannot be checked by another; and anything derived from the
#: internal token can be computed by every holder of that token (the channels).
#:
#: A grant is a random, single-use nonce, bound to the exact request
#: (sha256 of method, path and body) and valid for GRANT_TTL_SECONDS. The engine
#: writes it as a file in a 0700 directory under the runtime home that every
#: worker shares; the worker that serves the request redeems it with an atomic
#: rename, so a second use (a replay) finds nothing. No long-lived secret
#: exists, in the environment or on disk.
TRIGGER_GRANT_HEADER_NAME = "X-OmniHarness-Trigger-Grant"

#: The IM channel a turn came from (Telegram, Slack...), sent by the channel
#: manager. Honoured only with a valid internal token (channel_of).
CHANNEL_HEADER_NAME = "X-OmniHarness-Channel"


#: Carries a single-use CHANNEL-OWNER grant (kind "channel-owner"), issued by the
#: channel manager only when the channel's explicit allowlist names the sender.
#: A bare internal-token call cannot forge it: it is a nonce the manager wrote
#: to the shared grant directory for exactly this thread's run.
CHANNEL_OWNER_HEADER_NAME = "X-OmniHarness-Channel-Owner-Grant"


def channel_header_present(request) -> bool:
    """Any channel header WITH the internal token: the request relays a channel
    message, whether or not the name is valid (an invalid name is still relayed,
    never a direct internal turn)."""
    headers = getattr(request, "headers", None) or {}
    return is_valid_internal_auth_token(headers.get(INTERNAL_AUTH_HEADER_NAME)) and headers.get(CHANNEL_HEADER_NAME) is not None


def trigger_grant_presented(request) -> bool:
    """A scheduled-run grant header was sent with the internal token."""
    headers = getattr(request, "headers", None) or {}
    return is_valid_internal_auth_token(headers.get(INTERNAL_AUTH_HEADER_NAME)) and headers.get(TRIGGER_GRANT_HEADER_NAME) is not None


async def channel_sender_is_owner(request) -> bool:
    """A valid channel name AND a channel-owner grant for this very run path."""
    headers = getattr(request, "headers", None) or {}
    if channel_of(request) is None:
        return False
    return redeem_trigger_grant(headers.get(CHANNEL_OWNER_HEADER_NAME), request.method, request.url.path, b"", kind="channel-owner")


def issue_channel_owner_grant(run_path: str) -> str:
    """For the channel manager: this run's message is from the allowlisted owner.
    Bound to the method and path (the SDK builds the body), single-use."""
    return issue_trigger_grant("POST", run_path, b"", kind="channel-owner")


def channel_of(request) -> str | None:
    """The channel name, only for an internal-token request; else None."""
    headers = getattr(request, "headers", None) or {}
    if not is_valid_internal_auth_token(headers.get(INTERNAL_AUTH_HEADER_NAME)):
        return None
    name = headers.get(CHANNEL_HEADER_NAME)
    return name if isinstance(name, str) and re.fullmatch(r"[a-z0-9_-]{1,32}", name) else None


#: Generous, because a grant is issued right before its one request and is
#: single-use: a long queue behind busy workers must not refuse a real run.
GRANT_TTL_SECONDS = 600
_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")


def _grant_dir():
    from omniharness.config.paths import get_paths

    directory = get_paths().base_dir / "trigger_grants"
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    return directory


def _request_digest(method: str, path: str, body: bytes, kind: str = "trigger") -> str:
    return hashlib.sha256(kind.encode() + b"\0" + method.upper().encode() + b"\0" + path.encode() + b"\0" + body).hexdigest()


def issue_trigger_grant(method: str, path: str, body: bytes, *, kind: str = "trigger") -> str:
    """Called by the trigger engine just before it sends ONE request."""
    import json
    import time

    directory = _grant_dir()
    now = time.time()
    for stale in directory.glob("*.grant"):
        try:
            if now - stale.stat().st_mtime > GRANT_TTL_SECONDS:
                stale.unlink()
        except OSError:
            pass
    nonce = secrets.token_urlsafe(32)
    payload = json.dumps({"digest": _request_digest(method, path, body, kind), "expires": now + GRANT_TTL_SECONDS})
    tmp = directory / f".{nonce}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(payload)
    os.replace(tmp, directory / f"{nonce}.grant")
    return nonce


def redeem_trigger_grant(nonce: str | None, method: str, path: str, body: bytes, *, kind: str = "trigger") -> bool:
    """True once, for the request the grant was issued for; False otherwise."""
    import json
    import time

    if not isinstance(nonce, str) or not _NONCE_RE.match(nonce):
        return False
    directory = _grant_dir()
    claimed = directory / f".{nonce}.{secrets.token_hex(8)}.redeemed"
    try:
        os.rename(directory / f"{nonce}.grant", claimed)  # atomic: one redeemer wins
    except OSError:
        return False
    try:
        grant = json.loads(claimed.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    finally:
        try:
            claimed.unlink()
        except OSError:
            pass
    if float(grant.get("expires", 0)) < time.time():
        return False
    return secrets.compare_digest(str(grant.get("digest", "")), _request_digest(method, path, body, kind))


async def is_trigger_engine_request(request) -> bool:
    """The internal token AND a grant the engine issued for exactly this request."""
    headers = getattr(request, "headers", None) or {}
    if not is_valid_internal_auth_token(headers.get(INTERNAL_AUTH_HEADER_NAME)):
        return False
    nonce = headers.get(TRIGGER_GRANT_HEADER_NAME)
    if not isinstance(nonce, str):
        return False
    body = await request.body()
    return redeem_trigger_grant(nonce, request.method, request.url.path, body)


def get_internal_user():
    """Return the synthetic user used for trusted internal channel calls."""
    return SimpleNamespace(id=DEFAULT_USER_ID, system_role="internal")


#: Prefix of the message id the trigger engine gives its injected prompt.
TURN_ID_PREFIX = "trigger-turn-"
#: Signed turn ids already accepted once (single use, per process).
_CONSUMED_TURN_IDS: set[str] = set()


def sign_turn_id(nonce: str, thread_id: str = "") -> str:
    """A message id only this server can mint, bound to one thread and one
    purpose (the engine's injected prompt). The gateway keeps it only on a
    request that carries the trigger engine's credential, only for that thread,
    and only once (see `accept_turn_id`). Any other caller's id is dropped, so
    no one can replace an earlier message (add_messages replaces by id), even
    by replaying an id read back from the thread's state."""
    mac = hmac.new(_INTERNAL_AUTH_TOKEN.encode(), f"turn-id|{thread_id}|{nonce}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"{TURN_ID_PREFIX}{nonce}.{mac}"


def accept_turn_id(value: object, *, thread_id: str, from_trigger_engine: bool) -> bool:
    """True once for a valid id the engine signed for `thread_id`, on the
    engine's own request; False for anything else, and for any id seen before."""
    if not from_trigger_engine or not isinstance(value, str) or not value.startswith(TURN_ID_PREFIX) or "." not in value:
        return False
    nonce, _, _mac = value[len(TURN_ID_PREFIX) :].rpartition(".")
    if not nonce or not secrets.compare_digest(sign_turn_id(nonce, thread_id), value) or value in _CONSUMED_TURN_IDS:
        return False
    _CONSUMED_TURN_IDS.add(value)
    return True
