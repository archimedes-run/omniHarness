"""The ONE place a tool name is normalised.

Tool names reach this process spelled however their source spells them:

  * built-ins and config tools: ``read_file``, ``web_search``
  * MCP tools, prefixed with their server (``tool_name_prefix=True``):
    ``googlecalendar_create-event``, ``session-watcher_list_coding_sessions``
  * connector toolkits: ``connector-gmail_GMAIL_FETCH_EMAILS``

and the names they are compared against (policy rules, per-server allow/deny
lists) are written by people, who write ``googlecalendar_create_event``. The
Google Calendar MCP server names its tools with hyphens; the rules were written
with underscores; every Calendar write fell through to the no-rule default and
``search-events`` had no rule at all (007 audit).

So both sides go through :func:`canonical_tool_name` and nothing else compares
raw spellings. Callers:

  * registration — ``McpToolSurface.permits`` (the allow/deny surface applied
    when MCP and connector tools are loaded);
  * rule matching — ``app.policy.classify`` (both the call's name and each
    rule's pattern).

What it does, and deliberately no more:

  * case-folds (``GMAIL_FETCH_EMAILS`` and ``gmail_fetch_emails`` are one tool);
  * treats ``-`` and ``_`` as the same separator, INCLUDING in the MCP server
    prefix: ``session-watcher_x`` and ``session_watcher_x`` are one name.

It does NOT strip the server prefix. ``filesystem_read_file`` (an MCP server
reading the host) and ``read_file`` (the sandbox) are different tools with
potentially different tiers; collapsing them would let one inherit the other's
rule. The prefix is part of the name the policy speaks about.

Glob metacharacters (``*``, ``?``, ``[``) pass through unchanged, so a rule
pattern can be normalised with the same function as a name.
"""

from __future__ import annotations


def canonical_tool_name(name: str) -> str:
    """The comparable form of a tool name or tool-name pattern."""
    return str(name).strip().lower().replace("-", "_")
