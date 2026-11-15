"""JWT token creation and verification."""

from datetime import UTC, datetime, timedelta

import jwt
from pydantic import BaseModel

from app.gateway.auth.config import get_auth_config
from app.gateway.auth.errors import TokenError

#: The only kind of token the session secret signs (auth/derived.py keys sign
#: everything else).
SESSION_TYP = "session"
#: The claims a session token from before `typ` existed carries, exactly.
#: Accepted until those tokens expire (token_expiry_days); anything else
#: without `typ: session` is refused.
_LEGACY_CLAIMS = frozenset({"sub", "exp", "iat", "ver"})


class TokenPayload(BaseModel):
    """JWT token payload."""

    sub: str  # user_id
    exp: datetime
    iat: datetime | None = None
    ver: int = 0  # token_version — must match User.token_version


def create_access_token(user_id: str, expires_delta: timedelta | None = None, token_version: int = 0) -> str:
    """Create a JWT access token.

    Args:
        user_id: The user's UUID as string
        expires_delta: Optional custom expiry, defaults to 7 days
        token_version: User's current token_version for invalidation

    Returns:
        Encoded JWT string
    """
    config = get_auth_config()
    expiry = expires_delta or timedelta(days=config.token_expiry_days)

    now = datetime.now(UTC)
    payload = {"sub": user_id, "exp": now + expiry, "iat": now, "ver": token_version, "typ": SESSION_TYP}
    return jwt.encode(payload, config.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> TokenPayload | TokenError:
    """Decode and validate a JWT token.

    Returns:
        TokenPayload if valid, or a specific TokenError variant.
    """
    config = get_auth_config()
    try:
        payload = jwt.decode(token, config.jwt_secret, algorithms=["HS256"])
        if not isinstance(payload, dict):
            return TokenError.MALFORMED
        typ = payload.get("typ")
        if typ != SESSION_TYP and not (typ is None and set(payload) <= _LEGACY_CLAIMS):
            # Not a session token (another purpose, or a forged shape).
            return TokenError.MALFORMED
        payload.pop("typ", None)
        return TokenPayload(**payload)
    except jwt.ExpiredSignatureError:
        return TokenError.EXPIRED
    except jwt.InvalidSignatureError:
        return TokenError.INVALID_SIGNATURE
    except jwt.PyJWTError:
        return TokenError.MALFORMED
