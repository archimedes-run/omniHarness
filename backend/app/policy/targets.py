"""What a Tier 3 call will actually act on (FR-029).

WHY THIS EXISTS. `PolicyMiddleware` takes a `resolve_targets` callable and
falls back to `[f"{tool_name}({arguments})"]` when it is absent —
ONE target, holding a repr of the whole call. `registration.build()` never
passed one, so in production every plan read

    I intend to use calendar_decline on exactly these 1 item(s):
      - calendar_decline({'meetings': ['Standup 9am', 'Review 2pm']})

Two requirements were quietly unmet by that. FR-029 asks for the resolved
SPECIFIC targets, because confirming a description authorises whatever it later
turns out to mean. And FR-009's scope threshold compares a target COUNT against
a limit — with the count pinned at one, it could never fire, so the extra care
at large blast radius was inert.

THE RULE BELOW IS A HEURISTIC, AND IT IS LABELLED AS ONE WHERE YOU READ IT.
A tool's arguments do not say which of them is "the things this acts on"; no
schema in this system marks that. So: exactly one list-valued argument means
its items are the targets. That is a guess, and the plan text names the argument
it guessed so you can see what it claimed rather than trusting it.

WHEN IT CANNOT TELL, IT SAYS SO rather than picking. Zero list arguments, or
more than one, falls back to a single entry describing the call. The action is
still Tier 3 and still requires confirmation; what is lost is only the
threshold's extra demand, which cannot be computed from a scope nobody knows.
Guessing which list mattered would be worse: it would state a specific scope
that might be wrong, and the user would confirm it.
"""

from __future__ import annotations

from typing import Any

#: Item types worth showing to a person. A list of dicts is structure, not a
#: list of things, and rendering it would put JSON in a sentence.
_NAMEABLE = (str, int, float)


def resolve_targets(tool_name: str, arguments: dict[str, Any] | None) -> list[str]:
    """The specific items this call will act on, or one honest fallback."""
    args = arguments or {}
    candidates = [(key, value) for key, value in args.items() if isinstance(value, list) and value and all(isinstance(item, _NAMEABLE) for item in value)]

    if len(candidates) == 1:
        key, value = candidates[0]
        return [str(item) for item in value]

    return [describe_unresolved(tool_name, args, len(candidates))]


def describe_unresolved(tool_name: str, arguments: dict[str, Any], candidate_count: int) -> str:
    """The fallback line, which admits what it does not know."""
    if candidate_count > 1:
        return f"{tool_name} — could not tell which arguments are the items it acts on, so this covers the whole call: {arguments}"
    return f"{tool_name}({arguments})"


def source_argument(arguments: dict[str, Any] | None) -> str | None:
    """The argument the targets were taken from, for the plan to name.

    Returns None when they were not resolved from one — the plan then says the
    scope could not be itemised rather than implying a specific list.
    """
    args = arguments or {}
    candidates = [key for key, value in args.items() if isinstance(value, list) and value and all(isinstance(item, _NAMEABLE) for item in value)]
    return candidates[0] if len(candidates) == 1 else None
