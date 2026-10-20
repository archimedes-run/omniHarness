"""Names of built MCP servers (Feature 006, #59).

Built servers live in a reserved namespace. People see ``built/<slug>``; the
wire key in ``extensions_config.json`` (which becomes the prefix of every tool
name) is ``built__<slug>``, because provider tool-name rules
(``^[a-zA-Z0-9_-]{1,64}$``) forbid ``/``.

A slug is ``[a-z0-9-]`` only: no underscore, so the first ``_`` after
``built__`` always ends the server part of a tool name and a prefixed name
parses one way. Collisions are judged on canonical names
(``omniharness.tools.names``): ``GitHub``, ``git_hub`` and ``git-hub`` are all
``github``'s name.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from omniharness.tools.names import canonical_tool_name

BUILT_PREFIX = "built__"
DISPLAY_PREFIX = "built/"
#: Leaves room for ``built__<slug>_<tool>`` within 64 characters.
MAX_SLUG = 24
MAX_TOOL_NAME = 64


def slugify(text: str) -> str:
    """``[a-z0-9-]`` only, at most MAX_SLUG characters; never empty."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    # The namespace is added by the builder, never typed: "built__github" is "github".
    while slug.startswith("built-"):
        slug = slug[len("built-") :]
    slug = slug[:MAX_SLUG].strip("-")
    return slug or "new-tool"


def wire_key(slug: str) -> str:
    return BUILT_PREFIX + slug


def display_name(slug: str) -> str:
    return DISPLAY_PREFIX + slug


def is_built_key(key: str) -> bool:
    return canonical_tool_name(key).startswith(BUILT_PREFIX)


def _bare(key: str) -> str:
    """The name as a person reads it: no ``built__``, no case, no separators,
    so ``GitHub``, ``git_hub`` and ``git-hub`` are all ``github``. Stricter
    than the canonical tool name on purpose: a look-alike is refused."""
    c = canonical_tool_name(key)
    c = c[len(BUILT_PREFIX) :] if c.startswith(BUILT_PREFIX) else c
    return re.sub(r"[^a-z0-9]", "", c)


def name_collision(slug: str, existing_keys: Iterable[str], other_built_slugs: Iterable[str]) -> str | None:
    """The existing name *slug* collides with, or None.

    Compared canonically, with and without the ``built__`` prefix, against
    every configured MCP server and every other built server.
    """
    mine = _bare(slug)
    for key in existing_keys:
        if _bare(key) == mine:
            return key
    for other in other_built_slugs:
        if _bare(other) == mine:
            return display_name(other)
    return None


def tool_name_collision(key: str, tools: Iterable[str], other_keys: Iterable[str], other_tool_names: Iterable[str]) -> str | None:
    """Why this server's prefixed tool names can't be registered, or None.

    Refused when a full name is too long, equals a tool another server
    registers, or starts with another server's prefix (``git`` + ``hub_x``
    against a server ``git-hub``).
    """
    taken = {canonical_tool_name(n) for n in other_tool_names}
    prefixes = [canonical_tool_name(k) + "_" for k in other_keys if canonical_tool_name(k) != canonical_tool_name(key)]
    for tool in tools:
        full = f"{key}_{tool}"
        if len(full) > MAX_TOOL_NAME:
            return f"the tool name {full!r} is longer than {MAX_TOOL_NAME} characters"
        c = canonical_tool_name(full)
        if c in taken:
            return f"a tool named {full!r} is already registered"
        for p in prefixes:
            if c.startswith(p):
                return f"the tool name {full!r} would read as a tool of {p[:-1]!r}"
    return None
