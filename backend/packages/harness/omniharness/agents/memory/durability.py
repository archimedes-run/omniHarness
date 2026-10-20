"""Keep memory to durable things (Phase 2.6).

Memory is for what stays true across conversations: preferences, ongoing
projects at a high level, people, context. It was filling with the residue of
single tasks: file paths like /mnt/user-data/outputs/report.md, tool steps,
commands, one-off searches. The updater prompt now says so, but a prompt is a
request, not a guarantee, so this module is the guarantee: after every update
(and in the one-time cleanup), any summary sentence or fact that carries a
transient marker is dropped.

Deliberately sentence-level and conservative. A sentence that mentions a path
is about a task, not the person; dropping the sentence is safer than editing
it into something the model did not say.
"""

from __future__ import annotations

import re
from typing import Any

#: Markers of task residue, each with what it catches.
TRANSIENT: tuple[tuple[str, re.Pattern[str]], ...] = (
    # /mnt/user-data/outputs/x.md, ~/Documents/repo, /Users/me/file — but not
    # the path part of a URL (preceded by ":" or "/") and not "and/or".
    ("unix path", re.compile(r"(?<![\w.:/])(?:~|/)(?:[\w.@+-]+/)+[\w.@+-]*")),
    ("windows path", re.compile(r"\b[A-Za-z]:\\[^\s]+")),
    # `pnpm build`, `git push -f`, `python3 run.py --x`
    (
        "command",
        re.compile(r"`[^`]*(?:\s-{1,2}[\w-]+|\b(?:npm|pnpm|npx|pip|uv|git|docker|make|curl|wget|python3?|node|cd|ls|rm|mkdir|cat|grep|sudo)\b)[^`]*`"),
    ),
    ("shell prompt", re.compile(r"(?:^|\s)\$\s+\w")),
    # "Step 3:", "then call", "used the web_search tool", "read_file("
    ("tool step", re.compile(r"\b(?:step\s+\d+\b|then\s+(?:call|run|invoke)\b|(?:call(?:ed|s)?|invok(?:e|ed|es)|us(?:e|ed|es)|ran|run)\s+the\s+[\w-]+\s+tool\b|tool\s+calls?\b)", re.IGNORECASE)),
    ("function call", re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\(")),
)

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def transient_markers(text: str) -> list[str]:
    """Which transient markers the text carries (empty: it is durable)."""
    return [name for name, pattern in TRANSIENT if pattern.search(text)]


def durable_text(text: str) -> str:
    """The text without the sentences that carry a transient marker."""
    kept = [s for s in _SENTENCE.split(text.strip()) if s and not transient_markers(s)]
    return " ".join(kept).strip()


def scrub_transient(memory_data: dict[str, Any]) -> dict[str, Any]:
    """Drop task residue from every summary and fact, in place; returns it."""
    for group in ("user", "history"):
        for section in (memory_data.get(group) or {}).values():
            if isinstance(section, dict) and isinstance(section.get("summary"), str):
                section["summary"] = durable_text(section["summary"])
    facts = memory_data.get("facts")
    if isinstance(facts, list):
        memory_data["facts"] = [f for f in facts if not transient_markers(str(f.get("content", "")))]
    return memory_data
