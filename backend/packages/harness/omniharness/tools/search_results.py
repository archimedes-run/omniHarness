"""Search results, compact (Feature 007: web research).

Every web_search provider (ddg, serper, tavily, exa, firecrawl) and
image_search answers with its own JSON, indented, with whatever fields it has:
a provider's whole snippet, its usage hints, its totals. The model read all of
it on every lookup, and the chat showed it as raw JSON.

`compact_search_result` reduces any of them to ONE shape, the same for the
model and for the chat:

    {"query": "...", "results": [{"title": "...", "url": "https://...",
     "snippet": "..."}]}

(image_search adds `image_url` per result.) At most MAX_RESULTS results, each
field cut to a length, minified. Only http(s) URLs are kept; anything else
becomes "". A result that is not recognisably search results (an error string,
an error object) is returned unchanged, so a failure still reads as one.

The chat renders this shape as a list of links (title, domain, one line of
snippet), never fetching anything from it: no image, no preview
(frontend core/tools/search-results.ts).
"""

from __future__ import annotations

import json
from typing import Any

SEARCH_TOOLS = frozenset({"web_search", "image_search"})

MAX_RESULTS = 10
TITLE_MAX = 140
SNIPPET_MAX = 240
URL_MAX = 500

_TITLE_KEYS = ("title", "name")
_URL_KEYS = ("url", "link", "href", "source_url", "source")
_SNIPPET_KEYS = ("snippet", "content", "body", "description", "text")
_IMAGE_KEYS = ("image_url", "image", "thumbnail_url", "thumbnail")


def _cut(text: Any, limit: int) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _http(url: Any) -> str:
    value = str(url or "").strip()
    if len(value) > URL_MAX or not value.lower().startswith(("http://", "https://")):
        return ""
    return value


def _first(item: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = item.get(key)
        if value:
            return value
    return ""


def _items(payload: Any) -> tuple[str, list] | None:
    if isinstance(payload, list):
        return "", payload
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return str(payload.get("query") or ""), payload["results"]
    return None


def compact_search_result(tool_name: str, raw: Any) -> str | None:
    """The compact form of a search tool's output, or None when `raw` is not
    recognisably search results (then it is left as it was)."""
    if tool_name not in SEARCH_TOOLS:
        return None
    payload = raw
    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except ValueError:
            return None
    found = _items(payload)
    if found is None:
        return None
    query, items = found
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        entry = {"title": _cut(_first(item, _TITLE_KEYS), TITLE_MAX), "url": _http(_first(item, _URL_KEYS))}
        snippet = _cut(_first(item, _SNIPPET_KEYS), SNIPPET_MAX)
        if snippet:
            entry["snippet"] = snippet
        if tool_name == "image_search":
            entry["image_url"] = _http(_first(item, _IMAGE_KEYS))
        if entry["title"] or entry["url"] or entry.get("image_url"):
            results.append(entry)
        if len(results) >= MAX_RESULTS:
            break
    out: dict[str, Any] = {"query": _cut(query, TITLE_MAX), "results": results} if query else {"results": results}
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


def compact_tool_output(tool_name: str, output: Any) -> Any:
    """`output` with its content compacted when it is a search tool's result:
    a ToolMessage (content replaced), a string, or anything else (unchanged)."""
    if tool_name not in SEARCH_TOOLS:
        return output
    content = getattr(output, "content", None) if not isinstance(output, str) else output
    if not isinstance(content, str):
        return output
    compact = compact_search_result(tool_name, content)
    if compact is None:
        return output
    if isinstance(output, str):
        return compact
    try:
        output.content = compact
    except Exception:  # noqa: BLE001 - an immutable result is left as it was
        return output
    return output
