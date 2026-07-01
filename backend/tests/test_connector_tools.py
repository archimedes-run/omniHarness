"""Live connector-resolution tests (Part A3 integration).

Covers per-user scoping and the "connected mid-conversation is usable next turn"
guarantee at the resolution layer, plus silent-drop of revoked/absent
connections. The Composio API + stdio subprocess are NOT hit — we mock the
connections repo so the tests are hermetic and fast.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from omniharness.tools import connector_tools as ct


def _repo_returning(rows):
    repo = MagicMock()
    repo.list_by_user = AsyncMock(return_value=rows)
    return repo


@pytest.mark.asyncio
async def test_active_accounts_scoped_per_user():
    rows = [
        {"toolkit": "GMAIL", "status": "active", "composio_connection_id": "ca_A"},
        {"toolkit": "GITHUB", "status": "active", "composio_connection_id": "ca_B"},
        {"toolkit": "SLACK", "status": "revoked", "composio_connection_id": "ca_C"},
    ]
    with (
        patch("omniharness.persistence.engine.get_session_factory", return_value=object()),
        patch("omniharness.persistence.composio_connections.ComposioConnectionRepository", return_value=_repo_returning(rows)),
    ):
        accounts = await ct._active_accounts_for_user("user-A", {"GMAIL", "GITHUB", "SLACK"})
    # Only ACTIVE connections for the requested toolkits; revoked SLACK dropped.
    assert accounts == {"GMAIL": "ca_A", "GITHUB": "ca_B"}


@pytest.mark.asyncio
async def test_different_users_resolve_different_accounts():
    def _fake_repo(_sf):
        repo = MagicMock()

        async def list_by_user(*, user_id):
            if user_id == "user-A":
                return [{"toolkit": "GMAIL", "status": "active", "composio_connection_id": "ca_A"}]
            return [{"toolkit": "GMAIL", "status": "active", "composio_connection_id": "ca_B"}]

        repo.list_by_user = list_by_user
        return repo

    with (
        patch("omniharness.persistence.engine.get_session_factory", return_value=object()),
        patch("omniharness.persistence.composio_connections.ComposioConnectionRepository", side_effect=_fake_repo),
    ):
        a = await ct._active_accounts_for_user("user-A", {"GMAIL"})
        b = await ct._active_accounts_for_user("user-B", {"GMAIL"})
    assert a == {"GMAIL": "ca_A"}
    assert b == {"GMAIL": "ca_B"}  # per-user isolation — no shared cache


@pytest.mark.asyncio
async def test_toolkit_connected_mid_conversation_becomes_resolvable():
    # First turn: no active GMAIL connection -> resolves to nothing.
    with (
        patch("omniharness.persistence.engine.get_session_factory", return_value=object()),
        patch("omniharness.persistence.composio_connections.ComposioConnectionRepository", return_value=_repo_returning([{"toolkit": "GMAIL", "status": "pending", "composio_connection_id": "ca_A"}])),
    ):
        before = await ct._active_accounts_for_user("user-A", {"GMAIL"})
    assert before == {}

    # Next turn after the OAuth callback flips it to active -> now resolvable,
    # with no restart and no config write.
    with (
        patch("omniharness.persistence.engine.get_session_factory", return_value=object()),
        patch("omniharness.persistence.composio_connections.ComposioConnectionRepository", return_value=_repo_returning([{"toolkit": "GMAIL", "status": "active", "composio_connection_id": "ca_A"}])),
    ):
        after = await ct._active_accounts_for_user("user-A", {"GMAIL"})
    assert after == {"GMAIL": "ca_A"}


@pytest.mark.asyncio
async def test_no_session_factory_returns_empty():
    with patch("omniharness.persistence.engine.get_session_factory", return_value=None):
        assert await ct._active_accounts_for_user("user-A", {"GMAIL"}) == {}


def test_load_connector_tools_noop_without_user_or_toolkits():
    assert ct.load_connector_tools(None, ["GMAIL"]) == []
    assert ct.load_connector_tools("user-A", []) == []
