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
    #: Ran under a standing grant (scheduled runs): its own line.
    grant: bool = False
    #: The specialist that ran it ("" for the agent itself): "(via <agent>)".
    agent: str = ""

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


GRANT_PREFIX = "Ran under grant:"


def _line(prefix: str, records: list[ExecutionRecord]) -> str:
    counts: dict[tuple[str, str], int] = {}
    targets: dict[tuple[str, str], list[str]] = {}
    for record in records:
        key = (record.tool_name, record.agent)
        counts[key] = counts.get(key, 0) + 1
        seen = targets.setdefault(key, [])
        seen.extend(str(t) for t in record.targets if str(t) not in seen)
    parts = []
    for (tool, agent), n in counts.items():
        part = f"{tool} \u00d7{n}" if n > 1 else tool
        if targets[(tool, agent)]:
            part += f" ({', '.join(targets[(tool, agent)])})"
        if agent:
            part += f" (via {agent})"
        parts.append(" ".join(part.split()))
    return f"{prefix} " + ", ".join(parts)


def notice_lines(records: list[ExecutionRecord]) -> list[str]:
    """One line for what ran without asking (each tool in the order it first
    ran, repeats counted, resolved targets in brackets, a specialist's named
    "(via <agent>)"), and one for what ran under a standing grant."""
    lines = []
    plain = [r for r in records if not r.grant]
    granted = [r for r in records if r.grant]
    if plain:
        lines.append(_line(NOTICE_PREFIX, plain))
    if granted:
        lines.append(_line(GRANT_PREFIX, granted))
    return lines


def notice_line(records: list[ExecutionRecord]) -> str:
    return "\n".join(notice_lines(records))


@dataclass
class DisclosureLedger:
    """Accumulates the Tier 2 actions that ran in the turn, then guarantees the
    final reply carries the server's notice of them."""

    records: list[ExecutionRecord] = field(default_factory=list)

    def record(self, tool_name: str, arguments: dict, result: Any, targets: tuple[str, ...] = (), *, grant: bool = False, agent: str = "") -> ExecutionRecord:
        entry = ExecutionRecord(tool_name=tool_name, arguments=arguments or {}, result=result, targets=targets, grant=grant, agent=agent)
        self.records.append(entry)
        return entry

    def apply(self, reply: str, extra: list[ExecutionRecord] | None = None) -> str:
        """The reply with the notice appended: every record (and `extra`: the
        specialists' records rolled up onto this reply), whatever the reply
        says (the model's own words never count as the notice)."""
        records = [*self.records, *(extra or [])]
        if not records:
            return reply
        for record in records:
            record.disclosed = True
        line = notice_line(records)
        return f"{reply.rstrip()}\n\n{line}" if reply and reply.strip() else line

    def clear(self) -> None:
        self.records.clear()
