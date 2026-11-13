"""The chat builder's confirmation rules (Spec 010 FR-015, FR-016, FR-026).

IN CODE, NOT IN THE RULES FILE. The tiers live in default_rules.yaml like every
tool's, but a configured rules file replaces that file outright
(registration.resolve_rules_path), and a guarantee must not depend on a file
an install may replace. So the two rules below are code, and the builder's
save path checks them again when it runs (app/gateway/builder/service.py):

1. A builder save confirmed by TYPING is matched against its own short closed
   list, as the whole message (case and trailing punctuation ignored), and
   nothing else: not the general list (`confirm._CONFIRM_FORMS`, which
   admits "sure" and "ok"). Anything else typed while a builder card is open
   is a revision for the model, not an unrecognised answer to restate.
2. Some builder parts are BUTTON ONLY (grants, tool-access widening, new
   connections): no typed message of any content confirms them.
"""

from __future__ import annotations

#: Tier 3 builder tools a clear typed "yes" may confirm (FR-015).
TYPED_SAVE_TOOLS: frozenset[str] = frozenset({"builder_save", "builder_undo"})

#: Tier 3 builder tools only their card's button confirms (FR-016).
BUTTON_ONLY_TOOLS: frozenset[str] = frozenset({"builder_grant"})

#: Every builder tool that proposes (Tier 3); each is prechecked before a card.
PROPOSING_TOOLS: frozenset[str] = TYPED_SAVE_TOOLS | BUTTON_ONLY_TOOLS

#: The builder's tools whose results the harness composes itself and which
#: carry NO stored text: a draft's acknowledgement and a proposal's plan, save
#: or refusal name ids, field names, counts and versions only (the owner reads
#: the full draft on the card). They do not make the turn "content"
#: (lineage.TRUSTED_TOOL_RESULTS); trust is by the tool's identity
#: (middleware._mark_trusted_ack), never its name.
#:
#: NOT here: builder_read and builder_diff. They return stored text (an
#: agent's instructions, a skill's files, a rule's prompt), which content may
#: have put there, so a turn that read them is a content turn: a save proposed
#: after them is a suggestion, saved only by its button.
TRUSTED_RESULT_TOOLS: frozenset[str] = frozenset({"builder_draft"}) | PROPOSING_TOOLS

#: FR-015 / decided default Q2: the whole message, normalised by
#: confirm._normalise (lower case, punctuation stripped, spaces collapsed).
BUILDER_CONFIRM_FORMS: frozenset[str] = frozenset({"yes", "y", "save", "apply", "do it", "go ahead"})


def is_builder_card(tool_name: str | None) -> bool:
    return bool(tool_name) and tool_name in PROPOSING_TOOLS


def button_only(tool_name: str | None) -> bool:
    return bool(tool_name) and tool_name in BUTTON_ONLY_TOOLS
