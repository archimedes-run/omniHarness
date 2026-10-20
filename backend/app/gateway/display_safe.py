"""THE display sanitiser for agent- and content-derived text (Feature 006, review round 3).

Every surface that shows text an agent wrote or content supplied (a task
title from an email, a page's title, a plan's targets) shows it through
:func:`safe_field` (one line) or :func:`safe_lines` (a block whose line
structure the SERVER chose). The frontend mirrors these rules in
``frontend/src/core/display/safe.ts`` for text it receives raw (chat
messages, notifications); the backend sends every field it formats already
sanitised, and the frontend applies the same rules again, idempotently.
Both are tested against one case file
(``frontend/tests/unit/display-safe-cases.json``), and
``tests/gates/test_display_render_paths.py`` enumerates the render paths.

The rules:

  * control and format characters go: C0/C1 controls, line and paragraph
    separators (U+2028/2029), bidi embeddings, overrides and isolates
    (U+202A–202E, U+2066–2069), marks (U+200E/200F, U+061C), zero-width
    characters; a line break becomes a space, so content cannot start a line
    of its own (and so cannot forge the line a server-built link sits on);
  * URLs and bare domains in it are DEFANGED (``hxxps://evil[.]example``):
    only links the server builds are live, and those never pass through here.
"""

from __future__ import annotations

import re
import unicodedata

#: Bidi controls and marks, named explicitly (all are also category Cf).
BIDI = frozenset({*range(0x202A, 0x202F), *range(0x2066, 0x206A), 0x200E, 0x200F, 0x061C})
_BREAKS = frozenset({"\n", "\r", " ", " ", "\x0b", "\x0c", "\x85"})

_URL = re.compile(r"\b(h)(ttps?|xxps?)(://)([^\s<>\"'“”]+)", re.I)
#: A bare domain: labels ending in a common TLD. Narrow on purpose, so a file
#: name (report.pdf) or a version (1.2.3) is left alone.
_TLDS = "com|net|org|io|ai|co|dev|app|info|biz|me|us|uk|de|ru|cn|fr|xyz|site|online|top|example|test|local|sh|gg|ly|to|cc|tv|link|click|zip|mov"
_BARE_DOT = re.compile(r"(?<!\[)\.(?!\])")
_DOMAIN = re.compile(rf"\b((?:[a-z0-9-]+\.)+(?:{_TLDS}))\b", re.I)


def _strip(text: str) -> str:
    out = []
    for ch in str(text or ""):
        if ch in _BREAKS or ch == "\t":
            out.append(" ")
            continue
        if ord(ch) in BIDI or unicodedata.category(ch) in ("Cc", "Cf"):
            continue
        out.append(ch)
    return " ".join("".join(out).split())


def defang(text: str) -> str:
    """URLs and bare domains made unclickable: hxxps://evil[.]example."""

    def url(match: re.Match[str]) -> str:
        rest = match.group(4)
        host, sep, path = rest.partition("/")
        return f"hxx{match.group(2)[2:].lower()}://{_BARE_DOT.sub('[.]', host)}{sep}{path}"

    text = _URL.sub(url, text)
    return _DOMAIN.sub(lambda m: m.group(1).replace(".", "[.]"), text)


def safe_field(text: object) -> str:
    """One line of agent- or content-derived text, safe to display anywhere."""
    return defang(_strip(str(text if text is not None else "")))


def safe_lines(text: object) -> str:
    """A block whose LINE STRUCTURE the server chose (a plan, a reply's
    disclosure lines): each line made safe on its own."""
    return "\n".join(safe_field(line) for line in str(text if text is not None else "").split("\n"))
