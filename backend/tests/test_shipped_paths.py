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


#: Paths that TESTS read from. A test asserting against untracked config is as
#: hollow as a requirement reading from one — it passes on the machine where it
#: was written and fails, or worse silently skips, on a clean checkout.
#:
#: This category exists because it was reproduced two days after Article XIV was
#: ratified: a test asserting "the shipped config declares a thinking-capable
#: model" read `config.yaml`, which is gitignored.
TEST_READ_PATHS = [
    ("config.example.yaml", "frontend mode-mapping test — asserts a thinking-capable model ships"),
    ("extensions_config.example.json", "worker surface tests — assert the send capability is denied"),
    ("backend/app/policy/default_rules.yaml", "shipped-rules tests — assert 001/002 tools stay Tier 1"),
    ("backend/app/trigger_engine/default_rules.json", "wiring tests — assert the shipped defaults parse and are disabled"),
]


@pytest.mark.parametrize("path,reader", TEST_READ_PATHS)
def test_a_path_a_test_reads_is_tracked(tracked, path, reader):
    """Article XIV, applied to tests.

    A requirement reading untracked config loses its guarantee on a fresh
    clone. A TEST reading untracked config loses its evidence — which is worse
    in one respect: the requirement at least fails visibly when exercised, while
    the test simply stops proving anything and still reports green.
    """
    assert path in tracked, f"{path} is not tracked, and it is read by: {reader}.\n\nOn a clean checkout that test asserts against a file that is not there. It passes where it was written and proves nothing anywhere else."


def test_no_test_reads_a_gitignored_path_from_the_repo_root(tracked):
    """Scans the test suites for reads of a REPO-ROOT gitignored path.

    Narrow on purpose. ``tmp_path / "config.yaml"`` is legitimate — a test
    writing its own fixture — and an earlier, broader version of this check
    flagged those plus every docstring that mentioned a filename. A check with a
    high false-positive rate gets a whitelist, then gets ignored, then gets
    deleted.

    What it looks for is the shape that actually occurred: navigating UP to the
    repository root with ``parents[...]`` and reading a gitignored file from
    there. That is the only way a test picks up the developer's real config
    rather than one it made itself.

    LIMIT, stated rather than implied: a computed path defeats this. It catches
    the literal form, which is the form the bug took — twice, once in each
    language.
    """
    import re

    #: Reads that are deliberate, each with the reason. A file may read a
    #: gitignored path as a PRECONDITION TO SKIP — that is the opposite failure
    #: mode: the test declines to run rather than pretending to have proved
    #: something. What is forbidden is reading one as a source of assertions.
    allowed = {
        "backend/tests/test_client_live.py": "reads config.yaml to SKIP when real credentials are absent; a precondition, not an assertion source",
    }

    gitignored = ("config.yaml", "extensions_config.json", ".omni-harness")
    pattern = re.compile(r"""["'][^"']*(?:""" + "|".join(re.escape(g) for g in gitignored) + r")")
    comment_starts = ("#", "//", "*", '"""', "'''")
    offenders: list[str] = []

    for root in (REPO / "backend" / "tests", REPO / "frontend" / "tests"):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix not in (".py", ".ts", ".tsx") or not path.is_file():
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                stripped = line.lstrip()
                if stripped.startswith(comment_starts) or "example" in line:
                    continue
                # BOTH navigation idioms. Python tests use `parents[N]`;
                # TypeScript tests use `join(__dirname, "..")`. An earlier
                # version checked only the first and missed a frontend test
                # reading gitignored config — the exact bug this exists for,
                # found by CI instead.
                if "parents[" not in line and "__dirname" not in line:
                    continue
                if not pattern.search(line):
                    continue
                if str(path.relative_to(REPO)) in allowed:
                    continue
                offenders.append(f"{path.relative_to(REPO)}:{number}: {stripped[:70]}")

    assert not offenders, (
        "these tests navigate to the repo root and read a gitignored path, so they assert "
        "against a file that does not exist on a clean checkout:\n  " + "\n  ".join(offenders) + "\n\nIf the read is a PRECONDITION TO SKIP rather than a source of assertions, add the "
        "file to `allowed` with that reason."
    )


def test_the_check_would_notice_an_untracked_requirement_file(tracked, tmp_path):
    """CONTROL (Article XII).

    A membership test against a large set passes easily for the wrong reason.
    This confirms the set really excludes something it should.
    """
    stray = REPO / ".omni-harness" / "policy" / "rules.yaml"

    assert _rel(stray) not in tracked, "a path under .omni-harness/ appears tracked — if that directory has stopped being gitignored, this check's premise has changed"
