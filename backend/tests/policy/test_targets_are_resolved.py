"""FR-029/FR-009 — the plan names the specific things, and the count is real.

`resolve_targets` existed on the middleware, was used correctly when supplied,
and was NEVER SUPPLIED by `registration.build()`. Every production plan read
"exactly these 1 item(s)" and held a repr of the whole call, so FR-029 was
unmet and FR-009's threshold — which compares a target COUNT against a limit —
could never fire.

The fifth instance of built-correct-and-never-wired, and the third in this
module.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.policy.config import ConfigLoader
from app.policy.disclose import DisclosureLedger
from app.policy.middleware import PolicyMiddleware
from app.policy.registration import build
from app.policy.targets import resolve_targets, source_argument

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# The wiring — the part that was missing
# ---------------------------------------------------------------------------


def test_the_production_builder_supplies_a_target_resolver(tmp_path):
    """THE DEFECT. `build()` returned a middleware with resolve_targets=None,
    so the fallback ran for every call ever made."""
    config = SimpleNamespace(policy=SimpleNamespace(enabled=True, rules_path="", state_dir=str(tmp_path), expires_after_seconds=14400))
    middleware = build(config)

    assert middleware is not None
    assert middleware.resolve_targets is not None, "production builds a middleware that cannot resolve targets"
    assert middleware.resolve_targets("calendar_decline", {"meetings": ["a", "b"]}) == ["a", "b"]


# ---------------------------------------------------------------------------
# The heuristic, and what it refuses to guess
# ---------------------------------------------------------------------------


def test_one_list_argument_becomes_the_targets():
    assert resolve_targets("calendar_decline", {"meetings": ["Standup", "Review"]}) == ["Standup", "Review"]
    assert source_argument({"meetings": ["Standup", "Review"]}) == "meetings"


@pytest.mark.parametrize(
    "arguments,why",
    [
        ({"path": "/tmp/a", "content": "hi"}, "no list argument"),
        ({"ids": ["a", "b"], "labels": ["x"]}, "two list arguments — which is the scope?"),
        ({}, "no arguments at all"),
        ({"rows": [{"id": 1}]}, "a list of structures is not a list of things"),
    ],
)
def test_it_says_it_cannot_tell_rather_than_picking(arguments, why):
    """Guessing which list mattered would state a specific scope that might be
    wrong — and the user would confirm it. One honest entry instead."""
    targets = resolve_targets("some_tool", arguments)

    assert len(targets) == 1, f"{why}: it guessed instead of falling back"
    assert source_argument(arguments) is None, f"{why}: it named a source it could not know"


def test_two_list_arguments_produce_a_line_that_admits_it():
    line = resolve_targets("gmail_delete", {"ids": ["a", "b"], "labels": ["x"]})[0]
    assert "could not tell" in line


# ---------------------------------------------------------------------------
# What the user reads
# ---------------------------------------------------------------------------


@pytest.fixture
def middleware(tmp_path):
    (tmp_path / "policy.yaml").write_text('policy:\n  rules:\n    - pattern: "calendar_decline"\n      tier: 3\n  confirmation:\n    expires_after_seconds: 14400\n')
    return PolicyMiddleware(
        loader=ConfigLoader(path=tmp_path / "policy.yaml"),
        pending=SimpleNamespace(save=lambda a: a, open_actions=lambda now: [], get=lambda i: None, expire_due=lambda now: []),
        ledger=DisclosureLedger(),
        resolve_targets=resolve_targets,
        actor="default",
        now=lambda: NOW,
    )


def test_the_plan_names_the_argument_it_guessed_from(middleware):
    """The heuristic is labelled where the user reads it, not only in a
    docstring. They can see what it claimed instead of trusting it."""
    text = middleware._plan_text(
        "calendar_decline",
        ["Standup", "Review"],
        arguments={"meetings": ["Standup", "Review"]},
    )

    assert "exactly these 2 item(s) (from `meetings`)" in text
    assert "  - Standup" in text and "  - Review" in text


def test_the_plan_claims_no_source_when_it_could_not_resolve_one(middleware):
    """CONTROL. If the provenance were always printed it would be decoration,
    and a fallback would look like a resolved scope."""
    text = middleware._plan_text("write_file", ["write_file({...})"], arguments={"path": "/tmp/a"})

    assert "(from `" not in text
    assert "exactly these 1 item(s):" in text
