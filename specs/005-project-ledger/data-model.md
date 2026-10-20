# Data Model: Project Ledger

Every entity carries `id`, `created_at`, `updated_at` and a `version`, which is used for stale-write refusal. Times are UTC. The gateway database holds everything (research R11).

## Project
| Field | Type | Rules |
|---|---|---|
| name | text, 1–120 | required |
| why | text, ≤ 2,000 | optional |
| status | `active` · `paused` · `done` · `archived` | default `active` |
| context | text, ≤ 8,000 | standing instructions given to agents working on it |
| repositories | list of `{name, mount_path}` | each must be readable to count as linked; unreadable ones are listed with their reason (FR-040) |
| folders | list of paths | used for session matching and default declared scope |

## Goal
| Field | Type | Rules |
|---|---|---|
| project_id | ref | required |
| title | text, 1–200 | required |
| definition_of_done | text | required |
| target_date | date | optional |
| progress | derived | done tasks ÷ (tasks not dropped); not stored |

## Task
| Field | Type | Rules |
|---|---|---|
| project_id | ref | required |
| short_id | `T-<n>`, per project | unique per project; how commits name it (FR-041) |
| title | text, 1–300 | required |
| status | `todo` · `doing` · `blocked` · `done` · `dropped` | **changed only by the user, or on the user's confirmation** (FR-013) |
| owner | `{kind: user\|agent\|session\|workflow, ref}` | optional |
| due_date | date | optional |
| parent | `{kind: task\|goal, id}` | optional; no cycles |
| declared_files | list of globs | optional; default scope is the project's folders (FR-036) |
| done_at | time | set when status becomes `done` |

**Status transitions**: any state can move to any state, but only through a user action or a confirmed `ledger_apply`. Every change writes a `LedgerChange` row.

## Evidence (append-only)
| Field | Type | Rules |
|---|---|---|
| target | `{kind: project\|task, id}` | required |
| source | `git` · `claude_session` · `codex_session` · `workflow_run` · `calendar` · `chat` | required |
| source_ref | text | the source's own id (commit sha, `session:call_id`, run id, event id) |
| kind | `observed` · `claimed` | required (FR-015); agent todo status is always `claimed` (FR-016) |
| at | time | when it happened at the source |
| summary | text, ≤ 500 | shown only after display redaction, otherwise `withheld = true` (FR-019) |
| detail | json | files, statuses, outcome; paths only, never file contents |
| withheld | bool | set when redaction failed |
| reachable | bool | false when a commit left the branch (edge case); never deleted |

**Uniqueness**: `(source, source_ref, target)` (FR-017).

## Flag (derived, persisted only when dismissed)
| Field | Type | Rules |
|---|---|---|
| task_id | ref | |
| kind | `done_but_changing` · `outside_declared_scope` | always shown as an inference (FR-038) |
| evidence_ids | list | what it is based on |
| dismissed_at | time | dismissing is recorded |

## Note (decision)
| Field | Type | Rules |
|---|---|---|
| project_id | ref | required |
| decided | text | required |
| why | text | optional |
| thread_id | ref | optional |

## Link
| Field | Type | Rules |
|---|---|---|
| from | `{kind: project\|task, id}` | |
| to | `{kind: thread\|workflow\|session\|repository\|external, ref, agent?}` | explicit only; `session` links carry `agent` (claude or codex) |
| todo_ref | text | set when the link came from promoting a todo item (FR-012) |

## LedgerChange (who and when, FR-007)
| Field | Type | Rules |
|---|---|---|
| entity, entity_id | | |
| actor | `user` · `assistant_confirmed` | the assistant writes only on confirmation |
| pending_action_id | ref | for `assistant_confirmed`, the confirmed Tier 3 action |
| before, after | json | |

## Watcher-side state (not in the gateway database)

### Session (per `(agent, session_id)`)
New fields in replies: `agent` (`claude` or `codex`), `todos` (the last confirmed list, items `{title, status}`), `files_changed` (paths from successful results only), `waiting` (`{since, label: observed|inferred}`), `parent_session_id`, `drift` (count per agent).

### TodoState
`confirmed: list[{title, status}]`, `pending: {call_id → change}` (at most 64). Apply on success, discard on failure, and never apply on timeout (research R3).
