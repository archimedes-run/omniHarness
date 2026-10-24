"""Every surface that shows agent- or content-derived text goes through THE
display sanitiser (app/gateway/display_safe.py; review round 3).

RENDER_PATHS enumerates the backend formatters that render such text:
Telegram/Slack (the run footer the trigger engine appends to what a channel
delivers), the run summary and grant-use APIs, confirmation cards (chat and
Home's "Waiting on you" read the same list), Home's "What moved today", and
the chat's ledger step. Each must CALL safe_field or safe_lines; a stale
entry fails too. The frontend has its mirror in
frontend/tests/unit/display-render-paths.test.ts, and both sanitisers are
checked against one case file here and there. Behavioural tests feeding a
newline / bidi / URL payload through each path over HTTP live in
tests/studio/test_display_safe_paths.py.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
CASES = BACKEND.parent / "frontend" / "tests" / "unit" / "display-safe-cases.json"

#: (file, function) -> the surface it renders.
RENDER_PATHS: dict[tuple[str, str], str] = {
    ("app/gateway/trigger_engine_wiring.py", "_run_footer"): "Telegram / Slack: what a scheduled run did on its own",
    ("app/gateway/routers/studio.py", "_run_summary"): "the run summary page",
    ("app/gateway/routers/studio.py", "grant_uses"): "Agent Studio: done on its own",
    ("app/gateway/routers/confirmations.py", "_view"): "confirmation and suggestion cards (chat, Home's Waiting on you)",
    ("app/gateway/home_view.py", "describe_change"): "Home: what moved today (ledger)",
    ("app/gateway/home_view.py", "describe_moved"): "Home: what moved today (outside sources)",
    ("app/ledger/controller.py", "apply"): "chat: the ledger step's disclosed text",
}

#: Render paths that put a LIVE link on screen: each must pass it through
#: provider_link (or build it with github_pr_link) so only a provably
#: provider-own link stays live.
LINK_PATHS: dict[tuple[str, str], str] = {
    ("app/gateway/home_view.py", "describe_moved"): "Home: what moved today (an outside item's link)",
    ("app/gateway/home_sources.py", "github_items"): "Home: a GitHub PR's link",
}
LINKERS = frozenset({"provider_link", "github_pr_link"})
SANITISERS = frozenset({"safe_field", "safe_lines"})


def _function(path: Path, name: str) -> ast.AST | None:
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return node
    return None


@pytest.mark.parametrize(("path", "function"), list(RENDER_PATHS))
def test_each_render_path_calls_the_sanitiser(path: str, function: str) -> None:
    node = _function(BACKEND / path, function)
    assert node is not None, f"stale RENDER_PATHS entry: {path}:{function} does not exist"
    calls = {getattr(n.func, "id", None) or getattr(n.func, "attr", None) for n in ast.walk(node) if isinstance(n, ast.Call)}
    assert calls & SANITISERS, f"{path}:{function} renders {RENDER_PATHS[(path, function)]} without display_safe.safe_field/safe_lines"


def test_the_backend_sanitiser_agrees_with_the_shared_cases() -> None:
    from app.gateway.display_safe import safe_field, safe_lines

    cases = json.loads(CASES.read_text(encoding="utf-8"))
    for given, expected in cases["field"]:
        assert safe_field(given) == expected, given
        assert safe_field(safe_field(given)) == expected, given
    for given, expected in cases["lines"]:
        assert safe_lines(given) == expected, given


@pytest.mark.parametrize(("path", "function"), list(LINK_PATHS))
def test_each_live_link_is_proven_the_providers_own(path: str, function: str) -> None:
    node = _function(BACKEND / path, function)
    assert node is not None, f"stale LINK_PATHS entry: {path}:{function}"
    calls = {getattr(n.func, "id", None) or getattr(n.func, "attr", None) for n in ast.walk(node) if isinstance(n, ast.Call)}
    assert calls & LINKERS, f"{path}:{function} puts a live link on screen without display_safe.provider_link/github_pr_link"


@pytest.mark.parametrize(
    ("source", "url", "live"),
    [
        ("github", "https://github.com/acme/app/pull/12", True),
        ("github", "https://github.com.evil.example/acme/app/pull/12", False),
        ("github", "https://github.com/acme/app/pull/12?next=https://evil.example", False),
        ("github", "http://github.com/acme/app/pull/12", False),
        ("github", "https://evil.example/acme/app/pull/12", False),
        ("github", "javascript:alert(1)", False),
        ("calendar", "https://calendar.google.com/calendar/event?eid=abc123", True),
        ("calendar", "https://www.google.com/calendar/event?eid=abc", True),
        ("calendar", "https://calendar.google.com.evil.example/calendar/event", False),
        ("calendar", "https://www.google.com/url?q=https://evil.example", False),
        ("session", "https://github.com/acme/app/pull/12", False),
    ],
)
def test_provider_link_keeps_only_the_providers_own_links(source: str, url: str, live: bool) -> None:
    from app.gateway.display_safe import provider_link

    assert (provider_link(source, url) == url) is live


def test_a_github_link_is_built_from_the_fetched_fields() -> None:
    from app.gateway.display_safe import github_pr_link

    assert github_pr_link("acme/app", 12) == "https://github.com/acme/app/pull/12"
    assert github_pr_link("acme/app/../../evil", 12) is None
    assert github_pr_link("acme/app", "12") is None


def test_the_backend_link_check_agrees_with_the_shared_cases() -> None:
    from app.gateway.display_safe import provider_link

    for source, url, live in json.loads(CASES.read_text(encoding="utf-8"))["links"]:
        assert (provider_link(source, url) == url) is live, (source, url)
