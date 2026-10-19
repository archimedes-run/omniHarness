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


def _without_the_filter() -> None:
    """Start each test with no filter installed, so a pass proves create_app()
    installs it — not that an earlier test in this process left it behind."""
    from app.gateway.log_redaction import UrlCredentialFilter

    logger = logging.getLogger("httpx")
    for f in [f for f in logger.filters if isinstance(f, UrlCredentialFilter)]:
        logger.removeFilter(f)


def _request_through_httpx() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
    with httpx.Client(transport=transport) as client:
        client.post(f"https://api.telegram.org/bot{FAKE_TOKEN}/getUpdates")


def test_a_telegram_request_is_logged_without_its_token(caplog) -> None:
    from app.gateway.app import create_app

    _without_the_filter()
    create_app()  # what the gateway does at import; installs the filter
    with caplog.at_level(logging.INFO, logger="httpx"):
        _request_through_httpx()

    lines = [r.getMessage() for r in caplog.records if r.name == "httpx"]
    assert lines, "positive control: httpx logged the request at all"
    assert not any(FAKE_TOKEN in line for line in lines), lines
    assert any("bot[redacted]/getUpdates" in line for line in lines), lines


def test_no_handler_ever_sees_the_token(tmp_path) -> None:
    """Every place a log line can go: stdout and stderr (what `docker logs`
    captures when the process is not redirected, as in docker-compose.yaml),
    a file (logs/gateway.log in the dev stack), on the root logger and on the
    httpx logger itself. The filter sits on the httpx LOGGER, before any
    handler, so all of them must receive the redacted record."""
    import io
    import sys

    from app.gateway.app import create_app

    _without_the_filter()
    create_app()
    stdout, stderr = io.StringIO(), io.StringIO()
    handlers = {
        "root stdout": (logging.getLogger(), logging.StreamHandler(stdout)),
        "root stderr": (logging.getLogger(), logging.StreamHandler(stderr)),
        "root file": (logging.getLogger(), logging.FileHandler(tmp_path / "gateway.log")),
        "httpx stderr": (logging.getLogger("httpx"), logging.StreamHandler(sys.stderr)),
    }
    fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    httpx_logger = logging.getLogger("httpx")
    saved = httpx_logger.level
    httpx_logger.setLevel(logging.INFO)
    for logger, handler in handlers.values():
        handler.setFormatter(fmt)
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)
    try:
        _request_through_httpx()
    finally:
        for logger, handler in handlers.values():
            logger.removeHandler(handler)
            handler.close()
        httpx_logger.setLevel(saved)

    outputs = {"root stdout": stdout.getvalue(), "root stderr": stderr.getvalue(), "root file": (tmp_path / "gateway.log").read_text()}
    for name, text in outputs.items():
        assert "api.telegram.org" in text, f"positive control: {name} received the request line"
        assert FAKE_TOKEN not in text, f"the token reached {name}"
