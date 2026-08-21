"""Internal-auth requests must carry an identity into the run config.

`AuthMiddleware` authorizes a server-to-server call (Telegram/Slack via
`ChannelManager`, a trigger-injected turn) as the internal user and stamps
`request.state.user`. `get_current_user` used to re-derive identity from the
cookie alone, disagreed with that decision, and returned None — so `start_run`
skipped threading `user_id` into `config["context"]` for every one of those
runs.

The pre-existing test for this asserted on a code path that no longer runs
(`run_agent`, replaced by `launch_agent_run_detached`), so it failed for a
reason unrelated to the bug and hid it. These assert on the resolver directly
and on the state a real request produces.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.gateway.deps import get_current_user
from app.gateway.internal_auth import create_internal_auth_headers, get_internal_user


def _request(*, stamped_user=None, cookies: dict | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/threads/t1/runs/wait",
        "headers": [(b"cookie", "; ".join(f"{k}={v}" for k, v in (cookies or {}).items()).encode())] if cookies else [],
        "query_string": b"",
    }
    req = Request(scope)
    if stamped_user is not None:
        req.state.user = stamped_user
    return req


@pytest.mark.asyncio
async def test_internal_auth_request_resolves_to_the_internal_user():
    """The bug: middleware says 'internal user', the resolver said 'nobody'."""
    req = _request(stamped_user=get_internal_user())

    assert await get_current_user(req) == str(get_internal_user().id)


@pytest.mark.asyncio
async def test_stamped_user_is_preferred_over_the_cookie_path():
    req = _request(stamped_user=SimpleNamespace(id="user-123"))

    with patch("app.gateway.deps.get_optional_user_from_request", new=AsyncMock(return_value=None)):
        assert await get_current_user(req) == "user-123"


@pytest.mark.asyncio
async def test_unstamped_request_still_falls_back_to_the_cookie_path():
    """Public paths and directly-constructed requests never reach the middleware."""
    req = _request()

    with patch("app.gateway.deps.get_optional_user_from_request", new=AsyncMock(return_value=SimpleNamespace(id="cookie-user"))):
        assert await get_current_user(req) == "cookie-user"


@pytest.mark.asyncio
async def test_unauthenticated_request_still_resolves_to_none():
    req = _request()

    with patch("app.gateway.deps.get_optional_user_from_request", new=AsyncMock(return_value=None)):
        assert await get_current_user(req) is None


def test_middleware_stamps_the_internal_user_for_an_internal_auth_call():
    """End of the chain: a real request carrying the internal token is
    authorized as, and stamped with, the internal user."""
    from app.gateway.auth_middleware import AuthMiddleware

    seen: dict = {}
    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.post("/api/threads/{thread_id}/runs/wait")
    async def _endpoint(thread_id: str, request: Request):
        seen["user_id"] = await get_current_user(request)
        return {"ok": True}

    with TestClient(app) as client:
        resp = client.post("/api/threads/t1/runs/wait", json={}, headers=create_internal_auth_headers())

    assert resp.status_code == 200
    assert seen["user_id"] == str(get_internal_user().id), "an internal-auth run must carry an identity; None here means config['context']['user_id'] is dropped for channel and trigger runs"
