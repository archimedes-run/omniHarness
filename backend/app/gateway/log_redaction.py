"""Keep credentials that travel in URLs out of the gateway's logs.

httpx logs every request at INFO as `HTTP Request: POST <url> "<status>"`, and
Telegram's Bot API carries the bot token in the URL PATH
(`https://api.telegram.org/bot<TOKEN>/getUpdates`). With Telegram enabled the
gateway wrote its token to logs/gateway.log on every long-poll — about every
ten seconds — found in the Phase 1 end-to-end check within a minute of turning
it on.

A filter on the `httpx` logger rewrites the record before any handler formats
it. httpx passes the URL in `record.args`, not in `record.msg`, so both are
rewritten.
"""

from __future__ import annotations

import logging
import re

#: `/bot<token>/` (and `/file/bot<token>/`) on the Telegram Bot API host.
_TELEGRAM_BOT_PATH = re.compile(r"(api\.telegram\.org/(?:file/)?bot)[^/\s\"']+")
_REDACTED = r"\1[redacted]"


def redact_url_credentials(text: str) -> str:
    return _TELEGRAM_BOT_PATH.sub(_REDACTED, text)


class UrlCredentialFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_url_credentials(record.msg)
        if isinstance(record.args, tuple):
            # httpx passes the URL as an httpx.URL object; str() is what the
            # formatter would have produced anyway.
            record.args = tuple(redact_url_credentials(str(a)) if "api.telegram.org" in str(a) else a for a in record.args)
        return True


def install() -> None:
    """Idempotent: one filter on the httpx logger however often it is called."""
    logger = logging.getLogger("httpx")
    if not any(isinstance(f, UrlCredentialFilter) for f in logger.filters):
        logger.addFilter(UrlCredentialFilter())
