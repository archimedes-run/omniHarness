"""Tier 2 disclosure, guaranteed by the system (FR-039, FR-040, FR-041).

Disclosure left to prompt guidance is unverifiable, and its failure is
invisible: a turn where the model forgets is indistinguishable from a turn where
nothing happened. That makes Tier 2 into Tier 1 with good intentions.

THE NOTICE IS THE SERVER'S, ALWAYS (owner decision, spec 009 review H1/H2).
Every Tier 2 action that ran is listed in one line the server appends to the
final reply: "Ran without asking: code_job, ledger_apply ×2". It is built from
the execution records only, never from the model's text, and the model's text
never "covers" a record any more: the earlier coverage check (skip the record
when the reply named the tool and its target) let a model-written sentence
stand in for the system's notice, and that sentence could then be removed by
later text processing (the trailing-offer removal) or be wrong. A redundant
mention is clumsy; a missing notice is the defect this exists to prevent.

APPENDED TEXT COMES FROM THE EXECUTION RECORD, never the model's account
(FR-041). Each record also keeps a compact sentence (`sentence()`), shown as
the notice's details in the web chat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecutionRecord:
    """What a Tier 2 call actually did. The sole source for an appended
    disclosure, and deliberately distinct from the model's narration of it."""

    tool_name: str
    arguments: dict[str, Any]
    result: Any
    targets: tuple[str, ...] = ()
    disclosed: bool = False

    def sentence(self) -> str:
        """Generated from the record. Never from the reply.

        COMPACT ON PURPOSE. This used to interpolate `self.arguments` whole,
        so a disclosure for a file write reproduced the entire file — after
        the user had already read the summary it contained. Observed in real
        use: a one-paragraph note came back in full inside "Also, for the
        record".

        A disclosure nobody reads is a disclosure that failed. Short values
        stay verbatim because they are the specifics FR-040 asks for; long ones
        become a size, because their length is the only part that matters here.
        """
        if self.targets:
            return f"{self.tool_name} on {', '.join(self.targets)}"
        if self.arguments:
            return f"{self.tool_name} with {_render(self.arguments)}"
        return self.tool_name


#: Longer than this and a value is described rather than repeated. 80 is A
#: GUESS, chosen so a path or a title survives intact while a document does
#: not; it has no usage behind it and is expected to move.
_MAX_VALUE = 80


def _render(arguments: dict) -> str:
    """Argument names with short values, and a size for anything long."""
    parts = []
    for key, value in arguments.items():
        text = str(value)
        if len(text) > _MAX_VALUE:
            parts.append(f"{key}=<{len(text)} chars>")
        else:
            parts.append(f"{key}={text!r}")
    return ", ".join(parts)


#: How the notice line starts (the chat and the eval recognise the block by
#: the server's marker, not by this text).
NOTICE_PREFIX = "Ran without asking:"


def notice_line(records: list[ExecutionRecord]) -> str:
    """One line: each tool in the order it first ran, repeats counted, and its
    resolved targets when there are any (FR-040's specifics, on every channel):
    "Ran without asking: calendar_create_hold (Tue 3pm), ledger_apply ×2"."""
    counts: dict[str, int] = {}
    targets: dict[str, list[str]] = {}
    for record in records:
        counts[record.tool_name] = counts.get(record.tool_name, 0) + 1
        seen = targets.setdefault(record.tool_name, [])
        seen.extend(str(t) for t in record.targets if str(t) not in seen)
    parts = []
    for tool, n in counts.items():
        part = f"{tool} \u00d7{n}" if n > 1 else tool
        if targets[tool]:
            part += f" ({', '.join(targets[tool])})"
        parts.append(part)
    return f"{NOTICE_PREFIX} " + ", ".join(" ".join(p.split()) for p in parts)


@dataclass
class DisclosureLedger:
    """Accumulates the Tier 2 actions that ran in the turn, then guarantees the
    final reply carries the server's notice of them."""

    records: list[ExecutionRecord] = field(default_factory=list)

    def record(self, tool_name: str, arguments: dict, result: Any, targets: tuple[str, ...] = ()) -> ExecutionRecord:
        entry = ExecutionRecord(tool_name=tool_name, arguments=arguments or {}, result=result, targets=targets)
        self.records.append(entry)
        return entry

    def apply(self, reply: str) -> str:
        """The reply with the notice appended: every record, whatever the reply
        says (the model's own words never count as the notice)."""
        if not self.records:
            return reply
        for record in self.records:
            record.disclosed = True
        line = notice_line(self.records)
        return f"{reply.rstrip()}\n\n{line}" if reply and reply.strip() else line

    def clear(self) -> None:
        self.records.clear()
