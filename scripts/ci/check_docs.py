#!/usr/bin/env python3
"""Docs lint for CI: cheap, stdlib-only, no downloads.

Two checks over every tracked file, run on every CI event:

1. No merge-conflict markers (``<<<<<<<`` / ``>>>>>>>`` at the start of a line)
   in any tracked text file.
2. Every relative link in a tracked Markdown file points at a path that exists
   in the checkout. External links (http, mailto, ...) and in-page anchors are
   not checked: this needs no network and cannot flake.

Links that were already broken when this check was added are listed in
``docs-known-broken.txt`` (``file -> target``, no line numbers, so editing
around them does not churn the list). That list may only shrink: a new broken
link fails, and so does an entry that is no longer broken, so fixing a link
means deleting its line.

Exit 1 with one line per problem; exit 0 when clean.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

REPO = Path(__file__).resolve().parents[2]
KNOWN_BROKEN = Path(__file__).with_name("docs-known-broken.txt")

CONFLICT = re.compile(r"^(<{7}|>{7})( |$)")
# [text](target) and ![alt](target); target ends at whitespace or ')'.
LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
# [label]: target  (reference-style definitions)
REF_DEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s+<?(\S+?)>?(?:\s|$)")
FENCE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE = re.compile(r"`+[^`]*`+")
SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def tracked(*patterns: str) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", *patterns],
        cwd=REPO,
        capture_output=True,
        check=True,
    )
    return [REPO / p for p in out.stdout.decode().split("\0") if p]


def read_text(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except (FileNotFoundError, IsADirectoryError):
        return None  # a tracked symlink to a directory, or deleted in the worktree
    if b"\0" in data[:8192]:
        return None  # binary
    return data.decode("utf-8", errors="replace")


def conflict_markers() -> list[str]:
    problems = []
    for path in tracked():
        text = read_text(path)
        if text is None:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if CONFLICT.match(line):
                problems.append(f"{path.relative_to(REPO)}:{n}: merge-conflict marker")
    return problems


def link_targets(text: str):
    in_fence = False
    for n, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        line = INLINE_CODE.sub("", line)
        for m in LINK.finditer(line):
            yield n, m.group(1)
        m = REF_DEF.match(line)
        if m:
            yield n, m.group(1)


def known_broken() -> set[str]:
    lines = KNOWN_BROKEN.read_text().splitlines() if KNOWN_BROKEN.exists() else []
    return {
        ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")
    }


def broken_links() -> list[str]:
    known = known_broken()
    seen: set[str] = set()
    problems = []
    for md in tracked("*.md"):
        text = read_text(md)
        if text is None:
            continue
        for n, target in link_targets(text):
            if (
                target.startswith("#")
                or SCHEME.match(target)
                or target.startswith("//")
            ):
                continue
            path = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if not path:
                continue
            base = REPO if path.startswith("/") else md.parent
            resolved = (base / path.lstrip("/")).resolve()
            if not resolved.exists():
                key = f"{md.relative_to(REPO)} -> {target}"
                seen.add(key)
                if key not in known:
                    problems.append(
                        f"{md.relative_to(REPO)}:{n}: link target does not exist: {target}"
                    )
    for key in sorted(known - seen):
        problems.append(
            f"{KNOWN_BROKEN.relative_to(REPO)}: no longer broken, delete this line: {key}"
        )
    return problems


def main() -> int:
    problems = conflict_markers() + broken_links()
    for p in problems:
        print(p)
    if problems:
        print(f"\n{len(problems)} docs problem(s).", file=sys.stderr)
        return 1
    print("docs lint: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
