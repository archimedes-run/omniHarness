"""The gateway's logs never contain an IM bot token (found in the Phase 1 E2E).

httpx logs every request URL at INFO, and Telegram's Bot API puts the token in
the URL path: https://api.telegram.org/bot<TOKEN>/getUpdates. With Telegram
enabled, the gateway wrote the token to logs/gateway.log on every long-poll,
about every ten seconds — found within a minute of turning it on.
"""

from __future__ import annotations

import logging

import httpx

FAKE_TOKEN = "123456789:AAFakeTokenFakeTokenFakeTokenFake12"


def _request_through_httpx() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
    with httpx.Client(transport=transport) as client:
        client.post(f"https://api.telegram.org/bot{FAKE_TOKEN}/getUpdates")


def test_a_telegram_request_is_logged_without_its_token(caplog) -> None:
    from app.gateway.app import create_app

    create_app()  # what the gateway does at import; installs the filter
    with caplog.at_level(logging.INFO, logger="httpx"):
        _request_through_httpx()

    lines = [r.getMessage() for r in caplog.records if r.name == "httpx"]
    assert lines, "positive control: httpx logged the request at all"
    assert not any(FAKE_TOKEN in line for line in lines), lines
    assert any("bot[redacted]/getUpdates" in line for line in lines), lines
