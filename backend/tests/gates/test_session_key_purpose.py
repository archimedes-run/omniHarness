"""The session secret signs session tokens and nothing else (Spec 012 S2 review).

Any other signed value (a preview link, a frame view token) uses a key derived
for its purpose (auth/derived.py), so it can never be presented as a session.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-session-purpose-gate-min-32")

BACKEND = Path(__file__).resolve().parents[2]
APP = BACKEND / "app"
HARNESS = BACKEND / "packages" / "harness" / "omniharness"
ALLOWED = {"gateway/auth/config.py", "gateway/auth/jwt.py", "gateway/auth/derived.py"}
#: Every place the secret's ENVIRONMENT variable may appear, and why.
ENV_ALLOWED = {
    "app/gateway/auth/config.py": "reads it: the session secret itself",
    "app/gateway/secret_usage.py": "names it in the table of secrets the gateway uses (no read)",
    "packages/harness/omniharness/utils/safe_env.py": "names it in the list kept out of child environments (no read)",
    "packages/harness/omniharness/community/aio_sandbox/sandbox_auth.py": (
        "derives per-sandbox API keys by HMAC (container name) from it when the internal token is unset; the keys are never tokens the gateway accepts and the sandbox never sees the secret"
    ),
}


def test_only_the_auth_modules_touch_the_session_secret():
    users = sorted(str(p.relative_to(APP)) for p in APP.rglob("*.py") if re.search(r"\bjwt_secret\b", p.read_text(encoding="utf-8")))
    assert set(users) <= ALLOWED, users


def test_the_secret_is_read_from_the_environment_only_where_listed():
    found = sorted(str(p.relative_to(BACKEND)) for root in (APP, HARNESS) for p in root.rglob("*.py") if "AUTH_JWT_SECRET" in p.read_text(encoding="utf-8"))
    assert set(found) <= set(ENV_ALLOWED), sorted(set(found) - set(ENV_ALLOWED))
    assert set(found) == set(ENV_ALLOWED), "a listed reader moved: update ENV_ALLOWED"


def test_every_session_token_carries_the_session_typ():
    from app.gateway.auth.config import get_auth_config
    from app.gateway.auth.jwt import SESSION_TYP, create_access_token

    payload = jwt.decode(create_access_token("u1"), get_auth_config().jwt_secret, algorithms=["HS256"])
    assert payload["typ"] == SESSION_TYP


def test_decode_token_refuses_any_other_typ_and_any_other_shape():
    from app.gateway.auth.config import get_auth_config
    from app.gateway.auth.errors import TokenError
    from app.gateway.auth.jwt import TokenPayload, create_access_token, decode_token

    secret = get_auth_config().jwt_secret
    now = datetime.now(UTC)
    base = {"sub": "u1", "exp": now + timedelta(minutes=5), "iat": now, "ver": 0}
    assert isinstance(decode_token(create_access_token("u1")), TokenPayload)
    assert isinstance(decode_token(jwt.encode(base, secret, algorithm="HS256")), TokenPayload)  # an older session token
    for other in ({**base, "typ": "artifact_preview"}, {**base, "typ": "artifact_frame"}, {**base, "tid": "t", "root": "/x"}, {**base, "aid": "a", "n": 1}):
        assert decode_token(jwt.encode(other, secret, algorithm="HS256")) == TokenError.MALFORMED, other


def test_a_preview_token_is_not_signed_with_the_session_secret():
    from app.gateway.auth.config import get_auth_config
    from app.gateway.auth.jwt import decode_token
    from app.gateway.routers.artifacts import _create_preview_token

    token = _create_preview_token("thread-1", "u1", "/mnt/user-data/outputs/site")
    try:
        jwt.decode(token, get_auth_config().jwt_secret, algorithms=["HS256"])
        raise AssertionError("signed with the session secret")
    except jwt.InvalidSignatureError:
        pass
    assert not hasattr(decode_token(token), "sub")
