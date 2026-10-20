# Contract: session watcher additions

## Tools: unchanged (FR-020, 001 FR-018b and FR-023)

`list_coding_sessions` and `get_session_status` keep their names and arguments. A gate test compares the advertised tool set, names and argument schemas against a snapshot taken before this feature. Any difference fails.

## Reply fields added per session

| Field | Type | Meaning |
|---|---|---|
| `agent` | `"claude"` \| `"codex"` | which adapter produced it |
| `parent_session_id` | string \| null | subagent rollouts and sidechains |
| `todos` | `[{title, status}]` \| null | the last **confirmed** list (research R3). `null` means the agent has made none, while `[]` means it emptied the list. |
| `files_changed` | `[{path, at, inside_cwd}]` | from successful results only (research R5) |
| `waiting` | `{since, label: "observed"\|"inferred"}` \| null | observed only via hooks (FR-034) |

## Health additions

Health is reported per agent: `{agent, root, readable, reason?, drift: {unknown_types, malformed}, last_read_at}`. An unreadable root is reported. It is never treated as zero sessions (FR-026).

## Hook receiver (optional, FR-034)

- `POST http://127.0.0.1:18101/hooks/claude` accepts a Claude Code hook's JSON. It reads `hook_event_name`, `session_id`, `cwd`, `notification_type`, `task_id` and `task_subject`. Fields are verified against the hooks reference when built (FR-035).
- It always returns 204. Unknown events are counted as drift (`hooks`), not errors.
- It is bound to the existing published port only. It accepts no hook that asks for a decision, and returns nothing a hook could act on (Article IV).

## Configuration (tracked defaults, Article XIV)
- `watcher.codex.enabled` (default true when the root is readable), `watcher.codex.root` (default `$CODEX_HOME/sessions` or `~/.codex/sessions`).
- Compose mounts `${CODEX_HOME:-~/.codex}` read-only at `/root/.codex`, next to the existing `~/.claude` mount.
