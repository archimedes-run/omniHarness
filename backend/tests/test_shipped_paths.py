"""Article XIV — every path a requirement reads must resolve to a TRACKED file.

**Verified against a fresh clone, not by inspection.** Inspection is precisely
what cannot see this failure: the file is sitting right there in the working
tree, so it reads, the tests pass, and the manual check succeeds. It is absent
on a clean checkout, where the requirement it backed is not violated so much as
never engaged.

Three instances in Feature 003 alone, each caught by CI rather than locally:
the classification rule set under `.omni-harness/`, the email send-deny in
`extensions_config.json`, and a developer's own `config.yaml` — irrecoverable
when overwritten because no other copy existed.

`git ls-files` is the authority here, not `Path.exists()`. Existence is the
thing that misleads.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _tracked() -> set[str]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True)
    return set(out.stdout.split())


@pytest.fixture(scope="module")
def tracked():
    return _tracked()


def _rel(path: Path) -> str:
    return str(path.resolve().relative_to(REPO))


#: Files a REQUIREMENT reads from. Each entry names the requirement, so an
#: addition here is a claim about what the product needs, not a list of files
#: someone found.
REQUIRED_BY_A_REQUIREMENT = [
    ("backend/app/policy/default_rules.yaml", "FR-007/FR-009/FR-010 — classification. Absent, every tool is Tier 3 by accident rather than decision."),
    ("extensions_config.example.json", "FR-012 — the email send-deny. Absent, the send capability is present on first run."),
    ("config.example.yaml", "the config a new user copies. Absent or invalid, a fresh install does not start."),
    (".specify/memory/constitution.md", "every article. Absent, no gate has an authority to cite."),
    # --- found by auditing Features 001 and 002 against Article XIV ---------
    ("backend/app/trigger_engine/default_rules.json", "FR-001..FR-027 — every proactive message. Absent, the engine evaluated zero rules and reported itself healthy."),
]

#: MCP server entries a REQUIREMENT depends on. An entry present only in the
#: gitignored live config is the same failure in a different file: the
#: capability simply does not exist on a fresh install, and nothing says so.
REQUIRED_MCP_ENTRIES = [
    ("session-watcher", "Feature 001 FR-018 — the gateway has no external tool-registration API, so this entry IS the integration point. Absent, the watcher's tools never reach the agent."),
]


@pytest.mark.parametrize("server,requirement", REQUIRED_MCP_ENTRIES)
def test_a_required_mcp_entry_is_in_the_shipped_example(tracked, server, requirement):
    import json

    example = json.loads((REPO / "extensions_config.example.json").read_text())

    assert server in example.get("mcpServers", {}), (
        f"'{server}' is missing from extensions_config.example.json, and {requirement}\n\nIt is probably present in extensions_config.json, which is gitignored — so it works here and does not exist for anyone else (Article XIV)."
    )


@pytest.mark.parametrize("path,requirement", REQUIRED_BY_A_REQUIREMENT)
def test_the_file_a_requirement_reads_is_tracked(tracked, path, requirement):
    assert path in tracked, (
        f"{path} is NOT tracked by git, and {requirement}\n\nIt exists in this working tree, which is why every local check passes. On a fresh clone the guarantee it backs is simply not there, and nothing says so (Article XIV)."
    )


@pytest.mark.parametrize("path,requirement", REQUIRED_BY_A_REQUIREMENT)
def test_the_file_is_also_present_and_non_empty(tracked, path, requirement):
    """Tracked but empty would satisfy the check above and nothing else."""
    full = REPO / path
    assert full.exists(), f"{path} is tracked but missing from this tree"
    assert full.stat().st_size > 0, f"{path} is empty; {requirement}"


def test_the_policy_default_rules_resolve_to_a_tracked_file(tracked):
    """Follows the RESOLUTION, not the literal path.

    The value a requirement reads from is whatever the code resolves to, which
    is not always what the config says — the default is computed.
    """
    from app.policy.registration import DEFAULT_RULES

    assert _rel(DEFAULT_RULES) in tracked, f"the policy layer's default rules resolve to {DEFAULT_RULES}, which is not tracked"


def test_the_default_rules_actually_load(tracked):
    """Tracked and present is not the same as usable.

    A rule file that fails to parse makes every tool Tier 3 — safe, and not
    what shipping a default means.
    """
    from app.policy.config import ConfigLoader
    from app.policy.registration import DEFAULT_RULES

    ruleset = ConfigLoader(path=DEFAULT_RULES).load()

    assert not ruleset.unreadable, f"the shipped default rules do not load: {ruleset.error}"
    assert ruleset.rules, "the shipped default rules parse to zero rules"


def test_gitignored_paths_are_overrides_with_a_shipped_default_beneath(tracked):
    """The layering rule.

    A gitignored path MAY be read — as a local override. What it may not be is
    the ONLY copy. Each pair below is (override, the shipped default beneath).
    """
    pairs = [
        ("config.yaml", "config.example.yaml"),
        ("extensions_config.json", "extensions_config.example.json"),
    ]
    for override, default in pairs:
        assert override not in tracked, f"{override} is tracked; it is meant to be a local override"
        assert default in tracked, f"{override} is gitignored and {default} is NOT tracked — so there is no shipped default beneath the override, and a fresh clone has neither (Article XIV)"


def test_the_check_would_notice_an_untracked_requirement_file(tracked, tmp_path):
    """CONTROL (Article XII).

    A membership test against a large set passes easily for the wrong reason.
    This confirms the set really excludes something it should.
    """
    stray = REPO / ".omni-harness" / "policy" / "rules.yaml"

    assert _rel(stray) not in tracked, "a path under .omni-harness/ appears tracked — if that directory has stopped being gitignored, this check's premise has changed"
