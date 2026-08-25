"""T017/T018 — the closed set accepts what people type, and nothing more.

Driven from specs/004-assistant-ui-surfaces/closed-set-coverage.md so the
document and the code cannot drift: if someone adds an entry without recording
a judgement, or records one without adding the entry, this fails.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.policy.confirm import _CONFIRM_FORMS, _DECLINE_FORMS, _normalise

TABLE = Path(__file__).resolve().parents[3] / "specs" / "004-assistant-ui-surfaces" / "closed-set-coverage.md"


def _rows():
    """(phrase, verdict) from the coverage table's `After` column."""
    out = []
    for line in TABLE.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        after = cells[3].replace("**", "").strip()
        if after not in {"CONFIRM", "DECLINE", "rejected"}:
            continue
        for phrase in re.findall(r"`([^`]+)`", cells[0]):
            out.append((phrase, after))
    return out


def test_the_table_is_readable_and_not_empty():
    """POSITIVE CONTROL. A parser that silently matches nothing would make
    every assertion below vacuous, and the suite would report success."""
    rows = _rows()
    assert len(rows) >= 20, f"only parsed {len(rows)} rows from the coverage table"
    assert any(v == "CONFIRM" for _, v in rows)
    assert any(v == "DECLINE" for _, v in rows)
    assert any(v == "rejected" for _, v in rows)


@pytest.mark.parametrize("phrase,expected", _rows())
def test_each_phrase_matches_its_recorded_judgement(phrase, expected):
    n = _normalise(phrase)
    actual = "CONFIRM" if n in _CONFIRM_FORMS else "DECLINE" if n in _DECLINE_FORMS else "rejected"
    assert actual == expected, f"{phrase!r} normalises to {n!r} and reads as {actual}, not {expected}"


@pytest.mark.parametrize("variant", ["YES", " yes ", "Yes.", "yes!", "yes,", "  YES  ", "Yes, do it!", "yes,   do   it"])
def test_punctuation_case_and_spacing_cannot_change_a_verdict(variant):
    """T018. The double-space defect lived exactly here: 'yes, do it' became
    'yes  do it' and would never have matched an entry that looked correct."""
    assert _normalise(variant) in _CONFIRM_FORMS, f"{variant!r} normalised to {_normalise(variant)!r}"


@pytest.mark.parametrize(
    "smuggled",
    [
        "yes and also delete the rest",
        "yes, then empty the calendar",
        "no, actually do it anyway",
        "confirm everything including next week",
    ],
)
def test_an_affirmation_carrying_an_instruction_is_not_a_confirmation(smuggled):
    """Exactness is the security property. A phrase that says yes AND asks for
    something else is not a member of the set, and must not be treated as one."""
    n = _normalise(smuggled)
    assert n not in _CONFIRM_FORMS and n not in _DECLINE_FORMS, f"{smuggled!r} was recognised"
