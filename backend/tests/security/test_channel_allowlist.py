"""Chat channels: an EMPTY allowlist means nobody, and a stranger gets silence.

Through the production composition the channel manager uses: the real
TelegramChannel / SlackChannel handler publishes to the real MessageBus, the
real ChannelManager dispatch loop consumes it and would start the run through
its gateway client. The client is a spy: a run that started would show up on
it (no run means no model call and no tool call).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

OWNER_TG_ID = 4242
STRANGER_TG_ID = 999


def _update(user_id: int, text: str = "what's on my calendar"):
    update = MagicMock()
    update.effective_chat.type = "private"
    update.effective_chat.id = 100
    update.effective_user.id = user_id
    update.message.text = text
    update.message.message_id = 7
    update.message.reply_to_message = None
    update.message.reply_text = AsyncMock()
    return update


async def _composed(tmp_path: Path, allowed: list):
    from app.channels.manager import ChannelManager
    from app.channels.message_bus import MessageBus
    from app.channels.store import ChannelStore
    from app.channels.telegram import TelegramChannel

    bus = MessageBus()
    manager = ChannelManager(bus=bus, store=ChannelStore(path=tmp_path / "store.json"), langgraph_url="http://127.0.0.1:8001/api")
    client = MagicMock()
    client.threads.create = AsyncMock(return_value={"thread_id": "t-1"})
    client.threads.get = AsyncMock(return_value={"thread_id": "t-1"})
    client.runs.wait = AsyncMock(return_value={"messages": [{"type": "ai", "content": "Your calendar is empty."}]})
    manager._client = client
    await manager.start()
    channel = TelegramChannel(bus=bus, config={"bot_token": "test-token", "allowed_users": allowed})
    channel._main_loop = asyncio.get_running_loop()
    channel._application = MagicMock()
    channel._application.bot.send_message = AsyncMock()
    return manager, client, channel


async def _settle() -> None:
    for _ in range(20):
        await asyncio.sleep(0.02)


def _no_contact(client, channel, update) -> None:
    client.threads.create.assert_not_called()
    client.runs.wait.assert_not_called()
    channel._application.bot.send_message.assert_not_called()
    update.message.reply_text.assert_not_called()


def test_a_stranger_starts_nothing_and_hears_nothing(tmp_path, caplog) -> None:
    async def go():
        manager, client, channel = await _composed(tmp_path, [OWNER_TG_ID])
        try:
            stranger = _update(STRANGER_TG_ID)
            with caplog.at_level(logging.INFO):
                await channel._on_text(stranger, None)
                await channel._cmd_start(stranger, None)
                await _settle()
            _no_contact(client, channel, stranger)
            assert str(STRANGER_TG_ID) in caplog.text and "what's on my calendar" not in caplog.text

            owner = _update(OWNER_TG_ID)
            await channel._on_text(owner, None)
            for _ in range(100):
                if client.runs.wait.called:
                    break
                await asyncio.sleep(0.02)
            client.runs.wait.assert_called_once()  # positive control: the configured id works
        finally:
            await manager.stop()

    asyncio.run(go())


def test_an_empty_allowlist_means_nobody_and_says_so_at_startup(tmp_path, caplog) -> None:
    async def go():
        with caplog.at_level(logging.WARNING):
            manager, client, channel = await _composed(tmp_path, [])
        try:
            assert "CLOSED" in caplog.text
            for who in (OWNER_TG_ID, STRANGER_TG_ID):
                update = _update(who)
                await channel._on_text(update, None)
                await _settle()
                _no_contact(client, channel, update)
        finally:
            await manager.stop()

    asyncio.run(go())


@pytest.mark.parametrize("allowed,sender,expected", [([], "U1", False), (["U1"], "U2", False), (["U1"], "U1", True)])
def test_slack_follows_the_same_rule(allowed, sender, expected) -> None:
    from app.channels.message_bus import MessageBus
    from app.channels.slack import SlackChannel

    bus = MessageBus()
    bus.publish_inbound = AsyncMock()
    channel = SlackChannel(bus=bus, config={"bot_token": "xoxb-test", "app_token": "xapp-test", "allowed_users": allowed})
    channel._loop = MagicMock()
    published: list = []
    channel._loop.is_running.return_value = True
    import app.channels.slack as slack_module

    original = slack_module.asyncio.run_coroutine_threadsafe

    def capture(coro, loop):
        published.append(coro)
        coro.close()
        return MagicMock()

    slack_module.asyncio.run_coroutine_threadsafe = capture
    try:
        channel._handle_message_event({"user": sender, "text": "hi", "channel": "C1", "ts": "1.0"})
    finally:
        slack_module.asyncio.run_coroutine_threadsafe = original
    assert bool(published) is expected


def test_an_openclaw_webhook_without_a_token_refuses_everyone() -> None:
    from app.channels.message_bus import MessageBus
    from app.channels.openclaw import OpenClawChannel

    closed = OpenClawChannel(bus=MessageBus(), config={})
    assert not closed.verify_bearer_token("") and not closed.verify_bearer_token("anything")
    opened = OpenClawChannel(bus=MessageBus(), config={"bearer_token": "s3cret-value"})
    assert opened.verify_bearer_token("s3cret-value") and not opened.verify_bearer_token("nope")
