"""Tier 2 disclosure, guaranteed by the system (FR-039, FR-040, FR-041).

Disclosure left to prompt guidance is unverifiable, and its failure is
invisible: a turn where the model forgets is indistinguishable from a turn where
nothing happened. That makes Tier 2 into Tier 1 with good intentions — and with
the workers in this feature, a silently forgotten disclosure is a calendar hold
the user never learns was created.

THE COVERAGE CHECK IS BIASED TOWARD APPENDING (FR-040). Stating the direction is
required, because without it the check gets tuned the wrong way: duplicates are
the visible failure and omissions the invisible one, so anyone adjusting it
feels pressure toward not-appending. A redundant disclosure is clumsy; a missing
one is the defect this exists to prevent.

"UNCERTAIN" HAS AN OPERATIONAL DEFINITION, because an untestable acceptance
criterion on a disclosure guarantee is the failure shape this project keeps
finding. A Tier 2 execution counts as already disclosed ONLY when the reply
names the tool's effect on the SPECIFIC resolved target. Anything less —
mentioning the tool but not the target, or the target but not what happened to
it — is uncertain, and appends.

APPENDED TEXT COMES FROM THE EXECUTION RECORD, never the model's account
(FR-041). A model that misdescribes what it did would otherwise produce a
disclosure that satisfies the check and misinforms the user, which is worse than
silence because it carries the system's authority rather than the model's.
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
        """Generated from the record. Never from the reply."""
        if self.targets:
            items = ", ".join(self.targets)
            return f"I used {self.tool_name} on {items}."
        if self.arguments:
            return f"I used {self.tool_name} with {self.arguments}."
        return f"I used {self.tool_name}."


@dataclass
class DisclosureLedger:
    """Accumulates Tier 2 executions for the turn, then guarantees the reply
    covers them."""

    records: list[ExecutionRecord] = field(default_factory=list)

    def record(self, tool_name: str, arguments: dict, result: Any, targets: tuple[str, ...] = ()) -> ExecutionRecord:
        entry = ExecutionRecord(tool_name=tool_name, arguments=arguments or {}, result=result, targets=targets)
        self.records.append(entry)
        return entry

    def covered(self, reply: str, record: ExecutionRecord) -> bool:
        """Is this execution already disclosed by the reply?

        THE OPERATIONAL DEFINITION (FR-040). Coverage requires the reply to name
        BOTH the tool's effect and the specific target. Naming one without the
        other is uncertain, and uncertain means append.
        """
        text = (reply or "").lower()
        if record.tool_name.lower() not in text:
            return False
        if record.targets:
            # SUBSTRING MATCH, DELIBERATELY, AND DO NOT "IMPROVE" IT.
            #
            # This is exact containment, so a reply saying "Tuesday afternoon"
            # does NOT cover a target of "Tue 3pm with Darcy" — it appends. That
            # near miss looks like a false positive and is the whole point.
            #
            # The obvious improvement is fuzzy or semantic matching, so a reply
            # that gestures at the right thing counts as covered. That change
            # moves the bias from append toward silence, which is the wrong
            # direction: a redundant disclosure is clumsy, a missing one is the
            # defect FR-039 exists to prevent. Duplicates are the VISIBLE
            # failure and omissions the INVISIBLE one, so anyone tuning this
            # feels pressure toward not-appending — which is why FR-040 states
            # the direction rather than leaving it to judgement.
            #
            # A similarity score also reintroduces the thing Gate B removed:
            # a threshold is a judgement, and a judgement about whether the
            # model said enough is exactly what "system-guaranteed, never
            # model-judged" rules out.
            #
            # tests/policy/test_disclosure_bias.py pins the near-miss case.
            return all(str(target).lower() in text for target in record.targets)
        # No resolved targets to name: the tool alone is the whole of the effect.
        return True

    def apply(self, reply: str) -> str:
        """Return the reply with any missing disclosures appended.

        The model MAY phrase a disclosure itself — `covered` accepts that. It
        may not skip one.
        """
        missing = [record for record in self.records if not self.covered(reply, record)]
        for record in missing:
            record.disclosed = False
        for record in self.records:
            if record not in missing:
                record.disclosed = True
        if not missing:
            return reply

        lines = [reply.rstrip(), "", "Also, for the record:"] if reply and reply.strip() else ["For the record:"]
        lines += [f"  - {record.sentence()}" for record in missing]
        return "\n".join(lines)

    def clear(self) -> None:
        self.records.clear()
