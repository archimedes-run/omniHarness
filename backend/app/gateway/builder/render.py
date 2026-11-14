"""How a builder draft or diff reads, on its card and to the model (Spec 010 FR-005, FR-019).

Plain text in the small markdown the pending-action card renders
(components/workspace/confirmations/plan-text.tsx: **bold**, `code`, "- "
items, paragraphs), until Slice 3's dedicated cards. Diff lines are marked
"−" / "+" rather than "-" so a removed line never reads as a list item.
Long instructions are collapsed.
"""

from __future__ import annotations

import difflib
import json
from typing import Any

#: Lines of instructions shown in full before collapsing.
SHOW_LINES = 40
#: Diff lines shown before collapsing.
DIFF_LINES = 80

KIND_WORD = {"agent": "agent", "skill": "skill", "automation": "automation"}


def _value(value: Any) -> str:
    if value is None or value == "" or value == []:
        return "(none)"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _block(text: str, limit: int = SHOW_LINES) -> list[str]:
    lines = (text or "").splitlines() or ["(empty)"]
    shown = [f"    {line}" if line.strip() else "" for line in lines[:limit]]
    if len(lines) > limit:
        shown.append(f"    … {len(lines) - limit} more line(s)")
    return shown


def _line_diff(before: str, after: str) -> list[str]:
    out: list[str] = []
    for line in difflib.unified_diff((before or "").splitlines(), (after or "").splitlines(), lineterm="", n=1):
        if line.startswith(("---", "+++")):
            continue
        if line.startswith("@@"):
            out.append("    …")
        elif line.startswith("-"):
            out.append(f"    − {line[1:]}")
        elif line.startswith("+"):
            out.append(f"    + {line[1:]}")
        else:
            out.append(f"      {line[1:]}")
    if len(out) > DIFF_LINES:
        out = out[:DIFF_LINES] + [f"    … {len(out) - DIFF_LINES} more diff line(s)"]
    return out or ["    (no change)"]


def fields_of(kind: str, snapshot: dict | None) -> dict[str, Any]:
    """The fields a person reads, from a store snapshot."""
    if snapshot is None:
        return {}
    if kind == "agent":
        config = snapshot.get("config") or {}
        tools = config.get("tools")
        return {
            "display_name": config.get("display_name"),
            "description": config.get("description"),
            "model": config.get("model"),
            "skills": config.get("skills"),
            "tool_groups": config.get("tool_groups"),
            "tool access": None if tools is None else {"integrations": (tools or {}).get("integrations") or [], "tools": (tools or {}).get("tools") or []},
            "standing grants": config.get("autonomy"),
            "instructions": snapshot.get("soul") or "",
        }
    if kind == "skill":
        files = snapshot.get("files") or {}
        out: dict[str, Any] = {"SKILL.md": files.get("SKILL.md", "")}
        for path in sorted(files):
            if path != "SKILL.md":
                out[path] = files[path]
        return out
    rule = dict(snapshot)
    return {key: rule[key] for key in sorted(rule)}


LONG_FIELDS = frozenset({"instructions", "SKILL.md", "prompt"})


def render_draft(draft: dict, *, live: dict | None, live_version: int) -> str:
    """The card's text: a new thing's fields, or a change's before/after."""
    kind, name = draft["kind"], draft["name"]
    title = draft.get("title") or name
    guessed = set(draft.get("guessed") or [])
    lines: list[str] = []
    after = fields_of(kind, draft.get("snapshot"))
    if draft.get("mode") == "create":
        lines.append(f"**New {KIND_WORD[kind]}: {title}** (`{name}`)")
        lines.append("")
        for key, value in after.items():
            if value in (None, "", [], {}) and key not in LONG_FIELDS:
                continue
            mark = " (guessed)" if key in guessed else ""
            if key in LONG_FIELDS or (isinstance(value, str) and "\n" in value):
                lines.append(f"{key}{mark}:")
                lines += _block(str(value))
            else:
                lines.append(f"{key}{mark}: {_value(value)}")
    else:
        before = fields_of(kind, live)
        lines.append(f"**Change to {KIND_WORD[kind]}: {title}** (`{name}`), based on version {draft.get('base_version')}")
        if live_version != draft.get("base_version"):
            lines.append(f"It has changed since this was drafted (now version {live_version}): saving would be refused. Draft it again.")
        lines.append("")
        changed = False
        for key in list(dict.fromkeys([*before, *after])):
            old, new = before.get(key), after.get(key)
            if old == new:
                continue
            changed = True
            mark = " (guessed)" if key in guessed else ""
            if key in LONG_FIELDS or isinstance(old, str) and "\n" in (old or "") or isinstance(new, str) and "\n" in (new or ""):
                lines.append(f"{key}{mark}, before → after:")
                lines += _line_diff(str(old or ""), str(new or ""))
            else:
                lines.append(f"{key}{mark}: {_value(old)} → {_value(new)}")
        if not changed:
            lines.append("No change from the live version.")
    for note in draft.get("notes") or []:
        lines += ["", note]
    return "\n".join(lines)


def render_live(kind: str, name: str, snapshot: dict | None, version: int, extra: list[str] | None = None) -> str:
    if snapshot is None:
        return f"There is no {KIND_WORD[kind]} called {name!r}."
    lines = [f"**{KIND_WORD[kind].capitalize()} `{name}`**, version {version} (live, read now)", ""]
    for key, value in fields_of(kind, snapshot).items():
        if key in LONG_FIELDS or (isinstance(value, str) and "\n" in value):
            lines.append(f"{key}:")
            lines += _block(str(value), limit=400)
        else:
            lines.append(f"{key}: {_value(value)}")
    for line in extra or []:
        lines += ["", line]
    return "\n".join(lines)
