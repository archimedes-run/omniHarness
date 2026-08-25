"""Named argument predicates for raise-only rule exceptions.

WHY THIS EXISTS. Some tools cannot be classified by name. `postgres_query`
carries `SELECT` and `DELETE FROM` through one entry point, so no name-pattern
rule can be right about it. The existing exception mechanism matches argument
EQUALITY, which cannot express "is this statement a read".

WHY A CLOSED SET RATHER THAN AN EXPRESSION LANGUAGE. Letting the rules file
carry arbitrary predicates would put interpretation back into the security
boundary — the thing Feature 003 rejected for confirmation and for the same
reason. A config file names one of these; it cannot describe a new one. Adding
one is a deliberate code change with a test.

THE FAILURE DIRECTION IS THE POINT. Every predicate here answers "is this
SAFE", never "is this dangerous". Anything it cannot establish — an
unparseable statement, a missing argument, an unexpected type — is not safe,
so the answer is False, the exception applies, and the tier RAISES. A predicate
that returned True when confused would silently lower a tier, which the
raise-only rule exists to make impossible.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

#: A statement is read-only only when it is a single SELECT. Deliberately
#: narrow:
#:
#:  * `WITH ... AS (DELETE ... RETURNING *) SELECT ...` is legal SQL and
#:    writes, so a leading WITH is NOT accepted despite usually being benign.
#:  * a second statement after `;` can be anything, so multiple statements are
#:    never read-only.
#:  * `SELECT ... INTO new_table` writes. Rejected.
#:
#: Being wrong here in the strict direction costs a confirmation prompt. Being
#: wrong in the permissive direction runs an unreviewed DELETE.
_LEADING_COMMENTS = re.compile(r"^(?:\s|--[^\n]*\n|/\*.*?\*/)+", re.S)
_SELECT_INTO = re.compile(r"\binto\b", re.I)


def read_only_sql(value: Any) -> bool:
    """True only when `value` is unambiguously one SELECT statement."""
    if not isinstance(value, str):
        return False
    text = _LEADING_COMMENTS.sub("", value).strip()
    if not text:
        return False
    body = text.rstrip(";").strip()
    if ";" in body:  # a second statement could be anything
        return False
    if not body.lower().startswith("select"):
        return False
    return not _SELECT_INTO.search(body)


#: Branch names that are a default somewhere in common practice. A push to any
#: of these is not reversible in the sense that matters.
#:
#: HONEST LIMIT (Article X): this judges by NAME. Confirming a repository's
#: actual default branch needs a network call, which classification must never
#: make — it would put an outbound request inside the decision about whether an
#: outbound request is allowed, and a slow or failing GitHub would then decide
#: the tier. So a repository whose default is named something unusual will pass
#: this check. That is a real gap, and it is narrower than the one it closes:
#: without it, every push is Tier 2 including a push to main.
_DEFAULT_BRANCHES = frozenset({"main", "master", "trunk", "default", "develop", "development", "prod", "production", "release"})


def branch_is_not_default(value: Any) -> bool:
    """True only when `value` is a named branch that is not a common default."""
    if not isinstance(value, str):
        return False
    branch = value.strip().removeprefix("refs/heads/").strip("/")
    if not branch:
        return False
    return branch.lower() not in _DEFAULT_BRANCHES


def explicitly_true(value: Any) -> bool:
    """True only for the boolean True.

    Not truthiness. `"false"`, `"no"` and `0` are all truthy or falsy in ways
    that differ between callers, and a tier must not turn on which. Anything
    that is not literally True has not established the safe case.
    """
    return value is True


#: The whole vocabulary a rules file may name.
PREDICATES: dict[str, Callable[[Any], bool]] = {
    "read_only_sql": read_only_sql,
    "branch_is_not_default": branch_is_not_default,
    "explicitly_true": explicitly_true,
}
