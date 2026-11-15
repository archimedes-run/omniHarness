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


# ---------------------------------------------------------------------------
# Bounded, concurrent toolkit loading (a toolkit that took ~75 s to list
# nothing froze the gateway: toolkits loaded one after another, unbounded).
# The stdio server is replaced by a fake client; no provider is called.
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

from langchain_core.tools import StructuredTool  # noqa: E402


def _fake_tool(name: str) -> StructuredTool:
    return StructuredTool.from_function(func=lambda: name, name=name, description=name)


def _fake_client(delays: dict[str, float], listed: dict[str, list[str]], cleaned: list[str]):
    """A MultiServerMCPClient stand-in: each toolkit's start+list takes its delay."""

    class FakeClient:
        def __init__(self, connections, tool_name_prefix=False):
            [(self.server, _spec)] = connections.items()

        async def get_tools(self):
            toolkit = self.server.removeprefix("connector-").upper()
            try:
                await asyncio.sleep(delays.get(toolkit, 0))
                return [_fake_tool(f"{self.server}_{n}") for n in listed.get(toolkit, [])]
            finally:
                cleaned.append(toolkit)

    return FakeClient


def _load(monkeypatch, accounts: dict[str, str], delays: dict[str, float], listed: dict[str, list[str]], *, limit: float | None = None, make_client=None):
    cleaned: list[str] = []

    async def active(user_id, toolkits):
        return {tk: acct for tk, acct in accounts.items() if tk in toolkits}

    monkeypatch.setenv("COMPOSIO_API_KEY", "test-key")
    if limit is not None:
        monkeypatch.setenv(ct.TOOLKIT_LOAD_TIMEOUT_ENV, str(limit))
    monkeypatch.setattr(ct, "_active_accounts_for_user", active)
    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", (make_client or _fake_client)(delays, listed, cleaned))
    started = time.monotonic()
    tools = ct.load_connector_tools("user-A", list(accounts))
    return tools, time.monotonic() - started, cleaned


LISTED = {"GMAIL": ["send", "read"], "GOOGLECALENDAR": ["list_events"], "GITHUB": ["get_repo", "list_issues"], "GOOGLEDRIVE": ["find"]}


def test_tools_and_order_unchanged_when_every_toolkit_answers(monkeypatch):
    # Completion order is the reverse of the accounts order; the tools come
    # back in the accounts order, each toolkit's in its server's order, as the
    # one-after-another loader returned them.
    accounts = {"GMAIL": "ca_1", "GOOGLECALENDAR": "ca_2", "GITHUB": "ca_3"}
    tools, _elapsed, _cleaned = _load(monkeypatch, accounts, {"GMAIL": 0.3, "GOOGLECALENDAR": 0.15, "GITHUB": 0.0}, LISTED)
    assert [t.name for t in tools] == [
        "connector-gmail_send",
        "connector-gmail_read",
        "connector-googlecalendar_list_events",
        "connector-github_get_repo",
        "connector-github_list_issues",
    ]
    from omniharness.tools.source_tags import source_of

    assert {(source_of(t) or ("", ""))[0] for t in tools} == {"connector:GMAIL", "connector:GOOGLECALENDAR", "connector:GITHUB"}


def test_a_hanging_toolkit_is_skipped_at_the_limit_and_the_others_returned(monkeypatch, caplog):
    accounts = {"GMAIL": "ca_1", "GOOGLEDRIVE": "ca_2", "GITHUB": "ca_3"}
    delays = {"GMAIL": 0.6, "GOOGLEDRIVE": 10.0, "GITHUB": 0.6}
    with caplog.at_level(logging.WARNING, logger=ct.__name__):
        tools, elapsed, cleaned = _load(monkeypatch, accounts, delays, LISTED, limit=1.0)
    assert [t.name for t in tools] == ["connector-gmail_send", "connector-gmail_read", "connector-github_get_repo", "connector-github_list_issues"]
    # About the limit: not the hang (10 s), and not the sum of the toolkits
    # (0.6 + 1.0 + 0.6 = 2.2 s, what loading them one after another takes).
    assert 0.9 <= elapsed < 1.8, elapsed
    # The hung toolkit's client was left (its session context exits, which is
    # what stops a real server process), and it was said once, by name.
    assert "GOOGLEDRIVE" in cleaned
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1, warnings
    assert "GOOGLEDRIVE" in warnings[0] and "timed out" in warnings[0]
    assert "test-key" not in warnings[0] and "ca_2" not in warnings[0]


def test_a_failing_toolkit_is_skipped_with_its_error(monkeypatch, caplog):
    accounts = {"GMAIL": "ca_1", "GITHUB": "ca_3"}

    class Boom(Exception):
        pass

    def raising_client(delays, listed, cleaned):
        base = _fake_client(delays, listed, cleaned)

        class Client(base):
            async def get_tools(self):
                if self.server == "connector-github":
                    raise Boom("server exited")
                return await super().get_tools()

        return Client

    with caplog.at_level(logging.WARNING, logger=ct.__name__):
        tools, _elapsed, _cleaned = _load(monkeypatch, accounts, {}, LISTED, make_client=raising_client)
    assert [t.name for t in tools] == ["connector-gmail_send", "connector-gmail_read"]
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "GITHUB" in warnings[0] and "server exited" in warnings[0]


def test_load_timeout_setting(monkeypatch):
    monkeypatch.delenv(ct.TOOLKIT_LOAD_TIMEOUT_ENV, raising=False)
    assert ct._toolkit_load_timeout() == ct.DEFAULT_TOOLKIT_LOAD_TIMEOUT_SECONDS == 15.0
    monkeypatch.setenv(ct.TOOLKIT_LOAD_TIMEOUT_ENV, "4.5")
    assert ct._toolkit_load_timeout() == 4.5
    for bad in ("soon", "0", "-3"):
        monkeypatch.setenv(ct.TOOLKIT_LOAD_TIMEOUT_ENV, bad)
        assert ct._toolkit_load_timeout() == 15.0


HANGING_SERVER = """
import os, pathlib, time
pathlib.Path(__file__).with_suffix(".pid").write_text(str(os.getpid()))
time.sleep(15)  # never answers the MCP handshake (exits by itself in 15 s)
"""


def test_a_hanging_stdio_server_process_is_stopped(monkeypatch, tmp_path):
    """The real client and a real stdio process that never answers: skipped at
    the limit, and the process it started is gone afterwards."""
    script = tmp_path / "hang_server.py"
    script.write_text(HANGING_SERVER)
    monkeypatch.setattr(ct, "_composio_server_script", lambda: str(script))

    async def active(user_id, toolkits):
        return {"GOOGLEDRIVE": "ca_2"}

    monkeypatch.setenv("COMPOSIO_API_KEY", "test-key")
    monkeypatch.setenv(ct.TOOLKIT_LOAD_TIMEOUT_ENV, "1")
    monkeypatch.setattr(ct, "_active_accounts_for_user", active)
    started = time.monotonic()
    assert ct.load_connector_tools("user-A", ["GOOGLEDRIVE"]) == []
    # The limit, plus the client's own bounded shutdown of the process.
    assert time.monotonic() - started < 8
    pid = int(script.with_suffix(".pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
