"""The default summarizer: no model, no network, no resident cost (FR-008b).

Spec'd as a first-class path rather than a degraded one, so the bar is that its
output reads acceptably to a person — not merely that it returns a string.

Strips fenced code and terminal control sequences, collapses whitespace, and
clips at a sentence boundary. Never a raw character truncation: cutting mid-word
looks broken in a way that makes the whole feature look broken.
"""

from __future__ import annotations

import re

from ..models import SummaryProvenance
from .port import SummarizerPort, Summary

MAX_LEN = 160

_FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
# Asterisks are safe to strip outright. Underscores are NOT: markdown emphasis
# requires a word boundary, so a bare `_+` rule mangles GOOGLE_API_KEY into
# GOOGLEAPIKEY — which reads as a different variable and is worse than leaving
# the markup in.
_MD_ASTERISK = re.compile(r"\*{1,3}")
_MD_UNDERSCORE = re.compile(r"(?<![A-Za-z0-9])_{1,3}|_{1,3}(?![A-Za-z0-9])")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_LIST_MARKER = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_WS = re.compile(r"\s+")
# Sentence end: ., ! or ? followed by space/end. Avoids splitting "v1.2" or "e.g."
_SENTENCE_END = re.compile(r"(?<=[.!?])\s")


def clean(text: str) -> str:
    text = _FENCED_CODE.sub(" ", text)
    text = _ANSI.sub("", text)
    text = _CONTROL.sub("", text)
    text = _TABLE_ROW.sub(" ", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_HEADING.sub("", text)
    text = _LIST_MARKER.sub("", text)
    text = _INLINE_CODE.sub(r"\1", text)
    text = _MD_ASTERISK.sub("", text)
    text = _MD_UNDERSCORE.sub("", text)
    return _WS.sub(" ", text).strip()


def clip(text: str, limit: int = MAX_LEN) -> str:
    """Clip at a sentence boundary, else a word boundary. Never mid-word."""
    if len(text) <= limit:
        return text
    window = text[: limit + 1]
    parts = _SENTENCE_END.split(window)
    if len(parts) > 1:
        kept = " ".join(parts[:-1]).strip()
        if len(kept) >= limit // 3:  # a usable sentence, not a stub
            return kept
    cut = window.rsplit(" ", 1)[0].strip()
    return (cut or text[:limit].strip()).rstrip(",;:-") + "…"


class MechanicalSummarizer(SummarizerPort):
    """The out-of-box path. Zero dependencies beyond the standard library."""

    def summarize(self, texts: list[str]) -> list[Summary]:
        return [Summary(text=clip(clean(t)), provenance=SummaryProvenance.MECHANICAL) for t in texts]
