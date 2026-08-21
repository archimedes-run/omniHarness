# Contract: MCP Tool Surface

**Date**: 2026-08-20 | **Plan**: [../plan.md](../plan.md)

The watcher's **only** integration point with the agent core (FR-018b). Adding a coding-agent
adapter must not change anything on this page (FR-023).

## Server registration

Declared in `extensions_config.json` under `mcpServers`, following the shape already used by
`github-issue-connector`:

```json
{
  "session-watcher": {
    "enabled": true,
    "type": "sse",
    "command": null,
    "args": [],
    "env": {},
    "url": "http://host.docker.internal:18101/sse",
    "headers": {},
    "oauth": null,
    "description": "Read-only status of coding-agent sessions running on this machine."
  }
}
```

Surfaces in the tool catalog as `local:session-watcher`
(`backend/app/gateway/routers/thread_tools.py:117`).

**`type` MUST be `sse`.** A stdio entry is spawned and owned by its client and torn down with
the connection, leaving nothing persistent to hold the registry, the heartbeat, or the filesystem
observer — which makes the `observable` field below unimplementable rather than merely awkward
(FR-018a). This is a correctness constraint, not a deployment preference.

*Not the reason*: an earlier draft claimed a containerized backend cannot reach the host's
session directory. It can — `~/.claude` is mounted (research.md R6b).

---

## Tool 1 — `list_coding_sessions`

**Tier 1 (read)** — executes silently, no confirmation (FR-014, Article II).

**Arguments**: none.

**Returns**

| Field | Type | Notes |
|---|---|---|
| `observable` | bool | `false` when the registry is stale — see below |
| `as_of` | str (ISO-8601) | Time of the data, not time of the call |
| `staleness_seconds` | int | `0` when fresh |
| `sessions` | list[SessionSummary] | May be empty |

`SessionSummary`: `session_id`, `project`, `state`, `idle_reason` (null unless idle),
`last_activity_at`, `elapsed_seconds`, `summary`, `summary_provenance`.

**The `observable` flag is the contract's load-bearing field.** When `false`, the caller MUST NOT
render the result as "no sessions running" regardless of whether `sessions` is empty (FR-011a).
An empty list with `observable: false` means *cannot see*; an empty list with `observable: true`
means *nothing running*. Collapsing the two is the specific defect FR-011a exists to prevent.

**Reply ordering** (FR-011b): when `observable` is `false`, the health caveat leads and the
last-known data follows — never the reverse. A trailing caveat can be acted on before it is heard
when a later phase speaks these aloud.

---

## Tool 2 — `get_session_status`

**Tier 1 (read)** (FR-014).

**Arguments**: `session_id` (str) — accepts either the session id or a project name (FR-012).

**Returns**: `observable`, `as_of`, `staleness_seconds` as above, plus

| Field | Type | Notes |
|---|---|---|
| `found` | bool | `false` → the assistant says so; never substitutes a similar session (FR-012) |
| `ambiguous` | bool | `true` → assistant asks which one (FR-017) |
| `candidates` | list[str] | Populated only when `ambiguous` |
| `session` | SessionDetail \| null | |

`SessionDetail` extends `SessionSummary` with `started_at`, `elapsed_seconds`, and
`recent_events` (ordered, each with `kind`, `at`, `summary`, `summary_provenance`) — FR-013.

---

## Cross-cutting contract rules

**Redaction (FR-011c–f).** Every string field derived from session content — `last_message`,
`summary`, `recent_events[].summary` — passes the redactor before leaving the process, on every
channel. Redactions appear as visible `[redacted]` markers. If redaction fails, the tool returns
an error rather than unredacted content: **fail closed**.

**No write surface.** Neither tool accepts a mutation argument, and no third tool exists. When
the user asks the assistant to answer or intervene in a session, there is nothing to call — the
observe-only limit of FR-015 is enforced by absence, not by policy.

**Honest absence (FR-016).** Any field the watcher has not observed is `null` and is stated as
absent. No field is ever populated with an estimate. An inferred `idle_reason` of `STALLED` is
distinguishable from an observed `COMPLETED` precisely so the assistant can word them differently
(FR-016a).

**Tier stability.** Both tools are Tier 1 permanently. A future interactive watcher introduces
*new* Tier-3 tools; it must not re-tier these (Article II).
