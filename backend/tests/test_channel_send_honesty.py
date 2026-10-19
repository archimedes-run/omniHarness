"""A channel that cannot send says so (Phase 1, remote delivery).

Telegram's and Slack's send() RETURNED when the client was not connected (and
Telegram's also on a non-numeric chat id), reporting an unsent message as sent
to any caller that checks. The trigger engine checks: it records a delivery
outcome on every firing.
"""

from __future__ import annotations

import pytest

from app.channels.message_bus import MessageBus, OutboundMessage


def _msg(chat_id: str = "4242") -> OutboundMessage:
    return OutboundMessage(channel_name="x", chat_id=chat_id, thread_id="", text="hello")


@pytest.mark.asyncio
async def test_telegram_not_connected_raises() -> None:
    from app.channels.telegram import TelegramChannel

    with pytest.raises(RuntimeError, match="not connected"):
        await TelegramChannel(bus=MessageBus(), config={}).send(_msg())


@pytest.mark.asyncio
async def test_telegram_non_numeric_chat_id_raises() -> None:
    from app.channels.telegram import TelegramChannel

    channel = TelegramChannel(bus=MessageBus(), config={})
    channel._application = object()  # connected, as far as send() can tell
    with pytest.raises(ValueError, match="must be numeric"):
        await channel.send(_msg(chat_id="@not-a-number"))


@pytest.mark.asyncio
async def test_slack_not_connected_raises() -> None:
    from app.channels.slack import SlackChannel

    with pytest.raises(RuntimeError, match="not connected"):
        await SlackChannel(bus=MessageBus(), config={}).send(_msg())
