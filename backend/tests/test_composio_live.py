"""Live Composio integration tests.

Gated behind ``COMPOSIO_LIVE_TESTS=1``. Requires ``COMPOSIO_API_KEY`` in the
environment and (optionally) ``TEST_ENTITY_ID`` for isolation. The whole module
is skipped when the gate var is unset, so CI stays green without credentials.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("COMPOSIO_LIVE_TESTS"),
    reason="COMPOSIO_LIVE_TESTS not set",
)

_API_KEY = os.environ.get("COMPOSIO_API_KEY", "")
_ENTITY_ID = os.environ.get("TEST_ENTITY_ID", "omniharness-live-test")


def _client():
    from app.gateway.composio_client import ComposioClient

    return ComposioClient(api_key=_API_KEY)


@pytest.mark.asyncio
async def test_live_initiate_gmail_returns_redirect_url():
    client = _client()
    result = await client.initiate_connection(
        entity_id=_ENTITY_ID,
        toolkit="GMAIL",
        redirect_url="http://localhost:3000/workspace/mcp/callback?toolkit=GMAIL",
    )
    assert result["redirect_url"]
    assert str(result["redirect_url"]).startswith("https://")


@pytest.mark.asyncio
async def test_live_list_connections_returns_list():
    client = _client()
    connections = await client.list_connections(entity_id=_ENTITY_ID)
    assert isinstance(connections, list)


@pytest.mark.asyncio
async def test_live_get_mcp_url_format():
    client = _client()
    url = client.get_mcp_url(toolkit="GMAIL", entity_id="test")
    assert url.startswith("https://mcp.composio.dev/gmail?")
    assert "entityId=test" in url
