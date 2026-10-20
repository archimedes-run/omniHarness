"""The GitHub connector rule set: the ONE place its tiering is defined (007).

default_rules.yaml names all GitHub Composio actions one by one (no glob, so
an action added later is refused until it is named). Nobody judges 952 actions
by hand, so the tier comes from the action's name, by the rule below, and the
YAML lines are GENERATED from it:

    cd backend && PYTHONPATH=. uv run python tests/policy/github_connector_policy.py

rewrites the GitHub lines of app/policy/default_rules.yaml in place. The tests
(test_connector_rules.py) import the same word list and function, and fail if
the YAML differs from what this would write. So the list below is used by the
generator, the check, and the tests alike.

The action list is the installed SDK's (composio-core, pinned in uv.lock):
composio/client/enums/action.pyi, read from disk, never from Composio's API.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RULES_FILE = Path(__file__).resolve().parents[2] / "app" / "policy" / "default_rules.yaml"

#: A first word that makes an action a read: Tier 1, unless a word below says otherwise.
READ_VERBS = ("GET", "LIST", "SEARCH", "FETCH", "FIND")

#: A read whose name contains any of these (anywhere, any case) is Tier 3: it
#: reveals access, configuration or credentials rather than content. Decided
#: 2026-10-20; VARIABLE added the same day (Actions variables are plaintext and
#: often hold configuration values).
SENSITIVE_WORDS = ("SECRET", "KEY", "TOKEN", "CREDENTIAL", "WEBHOOK", "ADMIN", "PERMISSION", "VARIABLE")

_LINE = re.compile(r'^    - \{pattern: "connector-github_(GITHUB_[A-Z0-9_]+)", tier: (\d)\}$', re.MULTILINE)


def sdk_actions(toolkit: str) -> list[str]:
    """Every action the installed SDK lists for `toolkit`, sorted."""
    import composio

    stub = Path(composio.__file__).parent / "client" / "enums" / "action.pyi"
    text = stub.read_text(encoding="utf-8")
    return sorted(set(re.findall(rf"^\s+({toolkit}_[A-Z0-9_]+): \"Action\"", text, re.MULTILINE)))


def is_sensitive(action: str) -> bool:
    return any(word in action.upper() for word in SENSITIVE_WORDS)


def github_tier(action: str) -> int:
    if action.split("_")[1] not in READ_VERBS:
        return 3
    return 3 if is_sensitive(action) else 1


def rule_line(action: str) -> str:
    return f'    - {{pattern: "connector-github_{action}", tier: {github_tier(action)}}}'


def rules_in_file(text: str) -> list[tuple[str, int]]:
    """The GitHub connector lines in the rules file, in file order."""
    return [(m.group(1), int(m.group(2))) for m in _LINE.finditer(text)]


def regenerate(text: str, actions: list[str]) -> str:
    """`text` with its GitHub connector block replaced by the generated lines."""
    matches = list(_LINE.finditer(text))
    if not matches:
        raise ValueError("no GitHub connector lines found in the rules file")
    start, end = matches[0].start(), matches[-1].end()
    return text[:start] + "\n".join(rule_line(a) for a in actions) + text[end:]


if __name__ == "__main__":
    original = RULES_FILE.read_text(encoding="utf-8")
    updated = regenerate(original, sdk_actions("GITHUB"))
    RULES_FILE.write_text(updated, encoding="utf-8")
    changed = sorted(set(updated.splitlines()) - set(original.splitlines()))
    print(f"{len(changed)} line(s) changed", *changed, sep="\n", file=sys.stderr)
