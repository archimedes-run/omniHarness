"""Tests for Discord channel integration wiring."""

from __future__ import annotations

from app.channels.discord import DiscordChannel
from app.channels.message_bus import MessageBus
from app.channels.service import _CHANNEL_REGISTRY


def test_discord_channel_registered() -> None:
    assert "discord" in _CHANNEL_REGISTRY


def test_discord_channel_init() -> None:
    bus = MessageBus()
    channel = DiscordChannel(bus=bus, config={"bot_token": "token"})

    assert channel.name == "discord"
