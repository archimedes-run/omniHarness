"""Content-derived URLs leave the machine as text, not as links.

An email or page the agent read can make it end a reply with a URL carrying
private data. Sent to Telegram, Slack or Discord as-is, the platform's servers
fetch it to build a link preview: zero-click exfiltration (review 4). Two
defences, both applied at the channel boundary (`Channel.deliver` and each
channel's `send`):

- previews are switched off on every outbound message (Telegram
  `link_preview_options`, Slack `unfurl_links`/`unfurl_media`, Discord
  `suppress_embeds`);
- every URL in the message body is defanged (``https://a.example/x`` becomes
  ``hxxps://a[.]example/x``), so no client linkifies it either. The only
  URLs left live are ones the server built itself and listed in
  `OutboundMessage.server_links`; agent text cannot put anything there.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# A scheme URL (http, https, ftp, ws…) or a bare www. host, up to whitespace or
# a closing bracket/quote that is not part of it.
_URL = re.compile(r"(?i)\b(?:(?:https?|ftps?|wss?)://|www\.)[^\s<>\"'`)\]]+")


def defang_url(url: str) -> str:
    """``https://a.example/x?d=1`` -> ``hxxps://a[.]example/x?d=1``."""
    m = re.match(r"(?i)^(https?|ftps?|wss?)://([^/?#]*)(.*)$", url, re.S)
    if m is None:  # www.host/...
        host, slash, rest = url.partition("/")
        return host.replace(".", "[.]") + slash + rest
    scheme, host, rest = m.groups()
    scheme = {"http": "hxxp", "https": "hxxps"}.get(scheme.lower(), f"{scheme}[:]")
    sep = ":" if scheme.startswith("hxxp") else ""
    return f"{scheme}{sep}//{host.replace('.', '[.]')}{rest}"


def defang_urls(text: str, live: Iterable[str] = ()) -> str:
    """Every URL in `text` defanged, except the exact URLs in `live`."""
    keep = {u for u in live if u}
    return _URL.sub(lambda m: m.group(0) if m.group(0) in keep else defang_url(m.group(0)), text)
