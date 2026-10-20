# Contract: `/api/ledger`

All routes require an authenticated user (`require_permission`), as every other `/api` route does. Write routes:
- carry the entity's `version`;
- return **409** with the current item when it changed meanwhile;
- return **422** with the reason when invalid.

There are no deletes of evidence.

**Can't-tell** (FR-050, FR-072): every response that reads an external source includes a `sources` map, `{git|sessions|workflows|calendar: {state: "ok"|"unreadable"|"not_connected", reason?: string, as_of?: time}}`. A list is never empty because a source failed. It is empty only when `state == "ok"`.

**Withheld** (FR-019): any text field that came from a source passes display redaction. If redaction fails, the field holds the Withheld sentence and `withheld: true`.

## Projects
| Method & path | Body / query | Returns |
|---|---|---|
| `GET /api/ledger/projects` | `?status=` | `[ProjectSummary]`: name, status, open tasks, overdue, last moved |
| `POST /api/ledger/projects` | Project fields | `Project` (201) |
| `GET /api/ledger/projects/{id}` | | `ProjectView`: project, goals (with progress), tasks (with flags), links, notes, `sources` |
| `PATCH /api/ledger/projects/{id}` | fields + `version` | `Project` |
| `GET /api/ledger/projects/{id}/evidence` | `?source=&kind=observed\|claimed&before=` | page of `Evidence`, `sources` |

## Goals, tasks, notes, links
| Method & path | Notes |
|---|---|
| `POST /api/ledger/projects/{id}/goals`, `PATCH /api/ledger/goals/{id}` | |
| `POST /api/ledger/projects/{id}/tasks`, `PATCH /api/ledger/tasks/{id}` | `status` changes only here, or through a confirmed `ledger_apply` (FR-013) |
| `POST /api/ledger/tasks/promote` | `{thread_id, project_id, todo_items: [{index, title}]}` → created tasks with links to the thread (FR-012). The thread's list is not modified. |
| `POST /api/ledger/projects/{id}/notes` | |
| `POST /api/ledger/links`, `DELETE /api/ledger/links/{id}` | explicit links only (FR-006, FR-011) |
| `POST /api/ledger/flags/{task_id}/{kind}/dismiss` | records the dismissal (FR-038) |

## Today
`GET /api/ledger/today` →
```json
{
  "waiting": { "items": [...], "count": 3, "source": {"state": "ok"} },
  "due":     { "overdue": [...], "today": [...] },
  "moved":   { "since": "2026-10-19T07:00:00Z", "items": [Evidence], "sources": {...} },
  "calendar":{ "today": [...], "source": {"state": "not_connected"} }
}
```
`waiting` is the Inbox's data (alerts + confirmations + sessions waiting), unchanged in meaning. `moved.since` is the user's last Today visit, or 24 h ago.

## Agent tools (Tier 3, classified in the shipped policy rules)
- `ledger_apply(changes: [{op: create|update|link|promote|note, entity, fields}])`: the card lists every change. It executes the changes in one transaction on confirm and writes `LedgerChange(actor=assistant_confirmed, pending_action_id)`.
- `automation_propose(rule, summary)`: the card states the schedule in words and in rule form, what it will say and where it goes. On confirm it is written through `automations_store` (FR-061). If the engine's parser refuses the rule, the proposal is refused with that reason (FR-062).
- Reads (`ledger_read(project?)`) are Tier 1.
