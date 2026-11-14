"""Only the builder service raises a card itself (Spec 010).

`app.policy.server_cards.raise_card` records a Tier 3 card with no tool call
behind it. Every other card is stated by the policy middleware from a model's
tool call, so a second caller of `raise_card` would be a way to put a card in
front of the owner that no tool call and no policy decision produced.

One scan over app/, packages/ and scripts/: no module other than the builder
service (and server_cards itself, which defines it) imports `server_cards`'s
`raise_card` or `server_cards` as a module, nor calls a `raise_card`. A stale
entry in ALLOWED fails.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
ROOTS = (BACKEND / "app", BACKEND / "packages", BACKEND / "scripts")

ALLOWED: dict[str, str] = {
    "app/policy/server_cards.py": "defines raise_card",
    "app/gateway/builder/service.py": "the builder's own save card and the permission card after a save",
}


def _files():
    for root in ROOTS:
        for path in root.rglob("*.py"):
            if "/tests/" in str(path) or ".venv" in path.parts:
                continue
            yield path


def uses(source: str) -> list[str]:
    """Each import of raise_card (or of the server_cards module, which reaches
    it) and each call of a `raise_card`, as "line: what"."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                if module.endswith("server_cards") and alias.name == "raise_card":
                    found.append(f"{node.lineno}: imports raise_card")
                elif alias.name == "server_cards":
                    found.append(f"{node.lineno}: imports the server_cards module")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.endswith("server_cards"):
                    found.append(f"{node.lineno}: imports the server_cards module")
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if name == "raise_card":
                found.append(f"{node.lineno}: calls raise_card")
    return found


def test_only_the_builder_service_raises_a_card_itself() -> None:
    offenders = []
    for path in _files():
        rel = str(path.relative_to(BACKEND))
        if rel in ALLOWED:
            continue
        offenders += [f"{rel}:{hit}" for hit in uses(path.read_text())]
    assert not offenders, "raise_card is the builder service's alone:\n" + "\n".join(offenders)


def test_the_allowed_entries_are_not_stale() -> None:
    for rel in ALLOWED:
        path = BACKEND / rel
        assert path.exists(), f"stale entry: {rel}"
        assert "raise_card" in path.read_text(), f"stale entry: {rel} no longer uses raise_card"


def test_the_scan_sees_each_form() -> None:
    assert uses("from app.policy.server_cards import raise_card\n")
    assert uses("from app.policy import server_cards\n")
    assert uses("import app.policy.server_cards as sc\n")
    assert uses("x.raise_card(policy=None)\n")
    assert not uses("from app.policy.server_cards import requester_of\n")
