# Research: Project Ledger

Date: 2026-10-19. Each item below gives the decision, the rationale, and the alternatives considered. The evidence behind the Codex, Claude and hooks items was gathered read-only: structure, key names and counts only, never content. Sources:
- sodiumsun/agenttrail at commit `e4ba2daa270abd7ecb51565bbfb12386f47ea418` (MIT, "Copyright (c) 2026 Kelly Sun");
- this machine's `~/.codex` (10 files, 7,508 rows) and `~/.claude/projects` (63 files);
- the Claude Code hooks reference at https://code.claude.com/docs/en/hooks, fetched 2026-10-19.

## R1. The watcher takes several adapters

- **Decision**:
  - `WatcherService` builds a list of `(adapter, RecordSource)` pairs, one per agent root: Claude at `~/.claude/projects`, and Codex at `$CODEX_HOME/sessions` or `~/.codex/sessions`.
  - `Discovery` iterates over them.
  - The registry key becomes `(agent, session_id)`.
  - Replies from the existing two tools gain `agent`, `todos`, `files_changed` and `waiting_label` (observed or inferred) per session.
- **Rationale**: the adapter interface is agent-neutral, but `server.py` wires exactly one adapter and `RecordSource` has one root. So 001 FR-023's "a new adapter and nothing else" does not hold, and the spec says so. Extending the reply's fields keeps the tool names and arguments unchanged (FR-020).
- **Alternatives**:
  - A second watcher process for Codex: rejected, because Article VI forbids another always-on process and it would need a second tool surface.
  - New tools such as `list_codex_sessions`: rejected by 001 FR-018b and FR-023.

## R2. Parsed-record shape

- **Decision**: `ParsedRecord` gains these optional fields: `agent`, `tool_call_id`, `tool_name`, `turn_id`, `parent_session_id`, `todo_change` (a candidate list or delta, not yet applied), `tool_outcome` (success / failure / unknown, for result records), and `files` (paths only).
- **Rationale**: todo confirmation (R3) needs call-to-result linking, and scope flags need files. Optional fields leave the Claude adapter's existing output unchanged.
- **Alternative**: a side channel per adapter. Rejected, because it would be a second parsing path for the same lines.

## R3. Todo lists change only on a confirmed result

- **Decision**: a per-session state machine in `session_watcher/todos.py`:
  1. A call carrying a todo change (TodoWrite / TaskCreate / TaskUpdate / `update_plan`) is held as **pending** under its call id.
  2. A matching result with a success outcome **applies** it. A failure outcome **discards** it.
  3. A pending entry with no result stays pending, at most 64 per session (the oldest is dropped, never applied), and is discarded when the session ends.
  4. Titles and statuses are kept. Descriptions, `activeForm` and `explanation` are dropped at parse time (FR-030).
- **Success per tool**:
  - Claude: a result without `is_error`. TaskCreate/TaskUpdate are confirmed either by the structured `toolUseResult` or by the text receipt.
  - Codex `update_plan`: an output exists for the `call_id`. It is always the constant acknowledgement; there is no failure example on this machine.
  - Codex other tools: exit code `0` in the exec output, `patch_apply_end.success`, or MCP `Ok`.
- **Rationale**: this fixes the reference's bug, where TodoWrite and `update_plan` were applied at call time. Status changes stay **claimed** evidence (FR-016).
- **Alternatives**: applying at call time (the reference's behaviour) was rejected. Reading `~/.claude/tasks/*` as ground truth was deferred to Q5, because the store is undocumented.

## R4. Codex record handling and drift

- **Decision**:
  - **Meaningful**:
    - `session_meta`: `id`, `cwd`, `parent_thread_id`, `thread_source`. A repeat means a resume.
    - `turn_context`: `cwd`, `workspace_roots`.
    - `event_msg`: `task_started`, `task_complete`, `turn_aborted`, `user_message`, `agent_message`, `patch_apply_end`, `mcp_tool_call_end`.
    - `response_item`: `function_call`, `custom_tool_call`, their `*_output`, and `message`.
  - **Inert (listed explicitly)**: `token_count`, `agent_reasoning`, `reasoning`, `thread_settings_applied`, `world_state`, `compacted`, `context_compacted`, `tool_search_call`, `tool_search_output`, `web_search_call`, `web_search_end`, `item_completed`.
  - **Everything else** counts as drift (FR-024).
  - **Selection**: by mtime within the watcher's window; `archived_sessions/` is skipped.
  - **Parent link**: top-level `parent_thread_id` first, then `session_id != id`, then `source.subagent.thread_spawn.parent_thread_id`. A subagent with none of these counts as drift.
- **Rationale**: these are the shapes seen on this machine. The reference silently drops unknown types, which our watcher's drift rule forbids.

## R5. Files a session changed (observed)

- **Decision**: files come only from successful results:
  - Claude: `Edit`, `Write`, `MultiEdit` and `NotebookEdit` `file_path`.
  - Codex: `apply_patch` `*** Add/Update/Delete File:` headers, confirmed by `patch_apply_end.success`, plus the path keys of `patch_apply_end.changes`.

  Paths are stored relative to the session's cwd when inside it; others are flagged as outside.
- **Rationale**: a file named in a failed call was not changed, so recording it as observed would be a false observation.

## R6. Where git is read

- **Decision**:
  - The gateway reads git, read-only, from repository folders the user links. Each is mounted read-only under `/host/repos/<name>` through a tracked compose override, documented in `config.example.yaml`.
  - The command is `git -c core.fsmonitor=false -c gc.auto=0 log --no-color --name-only --format=... <since>..`, with `GIT_OPTIONAL_LOCKS=0` so git takes no index lock.
  - It polls on the trigger loop's existing tick, and only when a repository is linked.
- **Rationale**: the gateway owns the ledger and the dedupe key. The watcher is about coding sessions. Read-only mounts make FR-018 structural, not a promise.
- **Alternative**: the watcher reads git and exposes it through its tools. Rejected, because that would change the watcher's tool surface (FR-020).

## R7. Hooks: who writes the user's settings

- **Decision**:
  - A host-side command, `python scripts/claude_hooks.py install|uninstall|status`, does the writing. Settings shows its exact diff and the one command to run.
  - The command writes atomically (temp file and rename), keeps a backup, and adds one tagged matcher group per event: Notification (`permission_prompt`, `idle_prompt`), TaskCreated, TaskCompleted, SessionStart and SessionEnd. Each handler is `{"type":"command","command":"<tracked script>","async":true,"timeout":2}`.
  - The script POSTs the hook's JSON to `http://127.0.0.1:18101/hooks/claude` with a 1 s timeout. It always exits 0 and prints nothing.
  - Uninstall removes only the tagged groups.
  - It installs at user level (default, pending Q3).
- **Rationale**: the watcher's mount of `~/.claude` is read-only, and must stay so (001 FR-019). Hooks from all settings files are merged and run in parallel, so adding ours never displaces the user's. Silent, async, exit 0 means Claude Code is never blocked, and the UserPromptSubmit/SessionStart context-injection channel is never used.
- **Alternative**: making the mount writable so the UI can apply the change. Rejected, because it breaks the zero-writes guarantee for every other read.

## R8. Scheduled automations run once

- **Decision**: the trigger engine records each cron firing under `compute_idempotency_key(rule_id, scheduled_time=<minute>)`, with a unique constraint. A second evaluator for the same minute finds the key and skips. This wires `platform.idempotency` (plan-inputs).
- **Rationale**: there are several gateway workers (Article XI's first row), and restarts happen.

## R9. Chat capture through the confirmation card

- **Decision**:
  - `ledger_apply(changes)` and `automation_propose(rule)` are agent tools classified **Tier 3** in the shipped rules. The middleware states the plan as the existing in-chat card, records a pending action, and executes on confirm.
  - The card's new **Edit** opens the changes as a form. Saving creates a superseding pending action from the user's own edit, through the UI, which is a trusted channel, and confirms it in the same step.
- **Rationale**: initiation, confirmation, audit, expiry and restate already exist and are tested. A second confirmation path would be a second chokepoint (Article II).

## R10. Today replaces Inbox

- **Decision**: `/workspace/today` holds three sections: Waiting (the Inbox API unchanged), Due (from the ledger), and Moved (from evidence). `/workspace/inbox` redirects to it. The sidebar badge moves with it.
- **Rationale**: the spec's "Decision: where Today lives".

## R11. Storage

- **Decision**:
  - Tables `ledger_projects`, `ledger_goals`, `ledger_tasks`, `ledger_notes`, `ledger_links`, `ledger_evidence` and `ledger_changes` (the who/when log, FR-007), in one Alembic revision.
  - Evidence is unique on `(source, source_ref)`.
  - Optimistic concurrency uses a `version` column, and a stale write returns 409 (edge case: two tabs).
- **Rationale**: the same pattern as `workflow_runs` and the other repositories.

## R12. Calendar

- **Decision**: the gateway feeds `CalendarSource.fetch_events` from the user's existing calendar connection, over the next 24 h (`DEFAULT_HORIZON`). Events attach to a project only through an explicit link to an event or a recurring series (FR-043). No connection means can't-tell.
- **Rationale**: this wires the dormant source (plan-inputs) without a second calendar client.
