# Feature Specification: Project Ledger

**Feature Branch**: `005-project-ledger`

**Created**: 2026-10-19

**Status**: Draft

**Version**: 1.1 (2026-10-20: Amendment 1 to FR-009, see below)

**Input**: User description: OmniHarness becomes the source of truth for the user's personal projects.

- **Entities**: Project, Goal, Task, Evidence, Note and Link.
- **Capture from chat**: the agent proposes and the user confirms. A thread's todos can be promoted to project tasks, and automations ("every weekday at 9, brief me") can be created from chat.
- **Observed evidence**: from git, from Claude Code and Codex sessions (including each agent's own todo list, applied only after a successful tool result), from workflow runs and from the calendar. Evidence is always labelled observed or claimed, and it never overwrites the plan.
- **Views**: a Today view and a Project view that fit the current sidebar, with Projects as a sidebar item.
- **Carried-forward rules**: the wiring gate from day one, an integration test through the production composition root, empty vs can't-tell, and Withheld for redaction.
- **Reference**: sodiumsun/agenttrail (MIT), for the coding-session evidence: a Codex adapter, native todo lists, optional Claude Code hooks, and declared-vs-observed scope.

## Preconditions Discovered During Specification

Every claim the input makes about the current system was checked against the code and, where it concerns local data, against this machine's own session files (structure only; no content was read). Where the input and the code disagree, the code wins and the requirement is written against it.

| Claim in the input | Verified | Evidence |
|---|---|---|
| A thread's todos exist and could be promoted | **Holds** | The lead agent keeps a per-thread todo list (`write_todos`, items with content and status), stored only in that thread's state |
| The session watcher's adapter boundary "was designed for a second agent" | **Partly** | The adapter interface is agent-neutral, but the watcher builds exactly one adapter, its record reader has a single root, and the parsed-record shape has no tool-call id, turn id, parent-session link or todo payload. A second agent needs changes to discovery wiring and the record shape, not only a new adapter. 001 FR-023's "a new adapter rather than a change to the registry" does not hold as written. |
| The watcher can read `~/.codex` | **DOES NOT HOLD** | The watcher runs in a container that mounts only `~/.claude`, read-only. Codex sessions, and any linked repository, need their own read-only mounts. |
| Codex sessions live at `sessions/YYYY/MM/DD/*.jsonl` | **Holds** | Verified on this machine: 7 files, rows `{timestamp, type, payload}`, and a `session_meta` carrying `id` (equal to the filename's uuid) and `cwd`. A resume appends another `session_meta` to the *original* file; one file has 37. Selection must therefore be by file modification time, never by folder date. |
| Codex subagent rollouts attach to their parent | **Holds, in a different shape than the reference** | Here the parent id is a top-level `parent_thread_id`. The reference implementation reads a nested `source.subagent.thread_spawn.parent_thread_id` and would miss both links on this machine. |
| A tool result says whether a call succeeded | **Holds for Claude, varies for Codex** | Claude results carry `is_error`. Codex has no uniform flag: exec tools carry an exit code in their output, patches carry `success`, MCP calls `Ok`/`Err`, and `update_plan` only acknowledges receipt. |
| Claude sessions use TodoWrite | **Not on this machine** | 0 TodoWrite calls in 63 files. Current sessions use TaskCreate/TaskUpdate (subject, status), whose results are text receipts and sometimes structured. TodoWrite support cannot be verified against real data here. |
| The reference applies todo changes only after success | **DOES NOT HOLD** | It defers TaskCreate/TaskUpdate correctly, but applies TodoWrite and Codex `update_plan` lists when the call is made, before any result. The input says to get this right, and FR-031 requires it. |
| Claude Code hooks can report "waiting on you" | **Holds** | The Notification hook carries `notification_type`, including `permission_prompt` and `idle_prompt`. Hooks from every settings file are merged and run side by side, so ours can be added without touching the user's. The user has no hooks configured today. Source: Claude Code hooks reference, fetched 2026-10-19. |
| Calendar and completion triggers exist | **Partly** | Both trigger sources exist and are unwired. Their rules are rejected at load because nothing supplies them a feed (`plan-inputs.md`). |
| Automations can be written | **Holds** | The Automations write path validates a rule with the trigger engine's own parser, writes it atomically, refuses a stale edit, and is applied by hot reload. Chat-created automations go through it rather than around it. |
| Something reads git activity | **DOES NOT HOLD** | No code reads any repository today. |

Consequences, carried into the requirements rather than worked around:

1. **Codex support is a watcher change, not just an adapter** (FR-020 to FR-023).
2. **Host data needs explicit, read-only, user-chosen mounts** (FR-026, FR-040). An unmounted source reads as "can't tell", never as "nothing happened".
3. **Todo state is applied on a confirmed result only**, which is a correction of the reference, not a port of it (FR-031).

## Decision: where Today lives

**Today replaces Inbox, in the same place in the sidebar.** The sidebar becomes:

New chat · Chats · **Today** · **Projects** · Automations · Connections · Agents, then More (Settings, …) in the footer.

Why:
- **"Blocked on me" already is the Inbox.** Today's first section is the same set: approvals waiting, sessions waiting on the user, and alerts. Keeping both would split one set of items across two pages and put two badges on the same thing.
- **Today is the daily landing place.** It belongs near the top, where Inbox is now, not inside Projects, where it would be one click further away and would hide work that belongs to no project.
- **The sidebar stays short.** Adding Projects and renaming Inbox to Today keeps seven items; adding both alongside Inbox would make eight.
- **Nothing is lost.** The Inbox's badge (things waiting on you) moves to Today unchanged. `/workspace/inbox` redirects to Today, and links in alerts keep working.

Projects sits after Today because it is where you go from Today. Automations, Connections and Agents keep their order.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Capture a project and its tasks from chat (Priority: P1)

The user tells the assistant about something they are working on: "I'm launching the beta by Dec 1; I need the landing page, the waitlist and the announcement." The assistant proposes a project (a name, why it matters, a goal with a date, three tasks) as a card in the chat. The user edits one task title and confirms, and the project now exists. Later, in a different chat, they say "this is for the beta". The thread attaches to the project, and the todos the assistant made in that thread can be promoted into project tasks with one action.

**Why this priority**: without written projects there is nothing for evidence to attach to and nothing for Today to show. This alone replaces a separate to-do tool for personal work.

**Independent Test**: from an empty ledger, capture a project with a goal and tasks from chat, attach a second thread, promote two of its todos, and open the Project view. Every item is there, with the chat it came from, and nothing was created without a confirmation.

**Acceptance Scenarios**:

1. **Given** no projects, **When** the user describes one in chat, **Then** the assistant proposes it as a card listing exactly what would be created, and nothing is stored until the user confirms.
2. **Given** a proposal card, **When** the user edits a field and confirms, **Then** the stored project matches the edited card, and the Project view links to the chat it came from.
3. **Given** a thread whose agent has made a todo list, **When** the user promotes items, **Then** each becomes a project task linked to that thread, and the thread's own list is unchanged.
4. **Given** a promoted todo, **When** the thread's agent later marks it done, **Then** the project task gains that as **claimed** evidence and its status is not changed by it (FR-013).
5. **Given** a proposal in chat, **When** it was suggested by content the assistant read (a web page, an email) rather than by the user, **Then** no proposal is made (initiation, FR-008).

---

### User Story 2 - Today: what is blocked on me, what moved, what is due (Priority: P1)

The user opens Today in the morning. At the top, **Waiting on you**: an approval the assistant is holding, a Claude Code session asking a permission question, and an alert. Next, **Due**: two tasks due today and one overdue, each with its project. Then **Moved since yesterday**: three commits in the beta repository, a Codex session that finished its plan, and a workflow run that failed. Each item says where it came from and whether it was observed or only claimed.

**Why this priority**: this is the page the user opens every day. It is what turns the ledger from storage into something used.

**Independent Test**: with seeded projects and stubbed evidence sources, open Today. Each section shows the right items, empty sections say they are empty, and a source that cannot be read says so instead of looking empty.

**Acceptance Scenarios**:

1. **Given** items waiting on the user, **When** Today opens, **Then** they are listed first, with the same count the sidebar badge shows.
2. **Given** tasks due today or earlier and not done, **When** Today opens, **Then** they appear under Due, overdue first, each naming its project.
3. **Given** evidence recorded since the user last opened Today (or the last 24 hours if never), **When** Today opens, **Then** it appears under Moved, newest first, each item labelled observed or claimed.
4. **Given** the session watcher is unreachable, **When** Today opens, **Then** Moved says sessions can't be read right now. It does not omit them silently or say nothing moved (FR-050).
5. **Given** nothing is waiting, due or moved, **When** Today opens, **Then** each section says so plainly in one line, and the page does not look broken.

---

### User Story 3 - See what coding agents actually did, Claude and Codex alike (Priority: P2)

The user runs Claude Code in one repository and Codex in another. Both appear in the same session list and pages, each labelled by agent. Each session's own todo list (Claude's tasks, Codex's plan) is shown as it stands after the agent's last successful update. On a ledger task the user has linked to a session, the agent's todo progress appears as claimed evidence, and the files it changed appear as observed evidence. If the user marked a task done and the files in its scope keep changing, the task shows "done, but still changing". If the session works outside the files the task declared, that is flagged too.

**Why this priority**: it is the evidence the user asked for by name, and it extends a feature that already exists. But it is only useful once tasks exist (US1) and somewhere shows them (US2).

**Independent Test**: with recorded Claude and Codex session files (synthetic fixtures shaped like this machine's), list sessions. Both agents appear in the same reply, and each todo list reflects only updates whose results succeeded. Linking one to a task shows the right evidence and the right flags.

**Acceptance Scenarios**:

1. **Given** Codex and Claude sessions active in the last window, **When** the agent or the user lists coding sessions, **Then** both appear in the same list through the same tools, each labelled with its agent, and no new tool exists (FR-020).
2. **Given** a Codex session resumed days later, **When** discovery runs, **Then** it is found by its recent modification, and the repeated session header reads as a resume, not as a new session or as drift (FR-022).
3. **Given** a Codex subagent rollout, **When** it is discovered, **Then** it is attached to its parent session, in either known link shape (FR-023).
4. **Given** a todo update whose tool call failed, was interrupted, or has no result yet, **When** the list is shown, **Then** it shows the last confirmed list, not the attempted one (FR-031).
5. **Given** a record type the adapter does not know, **When** it is read, **Then** it is counted as drift for that agent and shown where watcher health is shown (FR-024).
6. **Given** a task marked done whose declared files are modified afterwards by a session or a commit, **When** the task is viewed, **Then** it is flagged "done, but still changing", as an inference, with the evidence behind it (FR-036).

---

### User Story 4 - Evidence from git, workflow runs and the calendar (Priority: P3)

A project links a repository folder, a workflow and a calendar. Commits on the linked repository appear on the project as observed evidence, attributed to tasks when a commit message names one. A workflow run assigned to a task reports its outcome as observed evidence. Calendar events titled or tagged with the project appear on it and on Today.

**Why this priority**: it rounds out "what moved", but each source is independently optional, and the ledger is useful without any of them.

**Independent Test**: link a test repository, a stub workflow and a stub calendar to a project. Make a commit, complete a run and add an event; each appears once, labelled observed, under the right task or project.

**Acceptance Scenarios**:

1. **Given** a linked repository, **When** a commit is made, **Then** it appears as observed evidence (author, time, message subject, files changed). The commit body is shown only after display redaction, and is Withheld if that fails (FR-052).
2. **Given** a repository that is linked but not readable (not mounted, moved, permission denied), **When** the project is viewed, **Then** it says the repository can't be read and why, rather than showing no activity.
3. **Given** a workflow run assigned to a task, **When** it finishes, **Then** its outcome is recorded once as observed evidence on that task.
4. **Given** a connected calendar, **When** an event matches a project, **Then** it appears on the project and on Today's Due when it is today. A disconnected calendar reads as can't-tell, not as an empty day.

---

### User Story 5 - Create automations from chat (Priority: P3)

The user says "every weekday at 9, brief me on the beta". The assistant proposes an automation as a card: when (weekdays, 09:00, in the user's time zone), what (a brief of project Beta: due, blocked, moved), and where it is delivered. The user confirms, and the automation appears in Automations, where it can be edited like any other. It never runs twice for one scheduled time.

**Why this priority**: the input names it explicitly, and it reuses the existing automation path. It is not needed for the ledger to be useful.

**Independent Test**: ask for an automation in chat, confirm the card, and find it on the Automations page, valid and enabled. Decline a second one and nothing is written. Fire the schedule twice for the same minute and one brief is delivered.

**Acceptance Scenarios**:

1. **Given** a request for a recurring brief, **When** the assistant proposes it, **Then** the card states the schedule in words and in the rule's own form, what it will say, and where it will go, and nothing is written until confirmed.
2. **Given** a confirmed automation, **When** the Automations page opens, **Then** it is listed and editable, and it was validated by the same rules a hand-made automation is.
3. **Given** a request the engine cannot express, **When** it is proposed, **Then** the card says what it cannot do. It does not save an approximation silently.
4. **Given** one scheduled time, **When** the trigger is evaluated more than once (several workers, a restart), **Then** one run happens (FR-063).

---

### User Story 6 - Proactive help from the ledger (Priority: P4)

The morning brief reads the ledger: what is due, what is blocked on the user, and what moved. An overdue task produces one polite alert, which follows quiet hours and coalescing like every other alert. A session waiting on the user produces a "blocked on you" alert linked to the task it belongs to.

**Why this priority**: it compounds the value of everything above. But it depends on it, and on the existing trigger engine's politeness rules.

**Independent Test**: seed an overdue task and a waiting session, run the trigger engine as production builds it, and read the brief and the alerts. Each names the task and its project and follows quiet hours.

**Acceptance Scenarios**:

1. **Given** an overdue task, **When** the overdue check runs, **Then** one alert is produced per task per day at most, and none during quiet hours (Article VII).
2. **Given** the ledger cannot be read, **When** the brief runs, **Then** the brief says the ledger could not be read. It does not omit that section and present a partial brief as complete.

---

### User Story 7 - Optional: higher-fidelity "waiting on you" from Claude Code hooks (Priority: P5)

In Settings, the user turns on "Report Claude Code prompts precisely". The page shows exactly what will be added to their Claude Code settings: a silent, background handler for permission prompts, idle prompts and task events. The user confirms. From then on, a session asking permission is shown as waiting on the user as **observed**, not inferred from the shape of its last message. Turning it off removes exactly what was added and nothing else.

**Why this priority**: it improves accuracy, not capability. It touches the user's own configuration, so it must be opt-in.

**Independent Test**: enable it against a temporary settings file that already has other hooks. Only our entries are added, the user's are intact, and disabling restores the file byte-for-byte. A simulated permission prompt marks the session waiting, labelled observed.

**Acceptance Scenarios**:

1. **Given** existing user hooks, **When** the upgrade is enabled, **Then** they are preserved, and ours are added alongside them.
2. **Given** the upgrade is enabled, **When** a permission prompt fires, **Then** the session shows waiting on you as observed. Without the upgrade it still shows waiting, labelled inferred.
3. **Given** the upgrade is enabled, **When** the user disables it, **Then** exactly the added entries are removed.
4. **Given** the hook cannot reach OmniHarness (it is not running), **When** Claude Code fires it, **Then** Claude Code is not slowed, blocked or shown any output.

### Edge Cases

- The same commit, session or run is seen twice (restart, re-scan): it is recorded once.
- A session's cwd matches two projects' linked folders: the evidence attaches to the more specific folder, ties attach to both, and each attachment says why (FR-044).
- An agent's todo item and a ledger task have the same title but are different work: nothing is matched by title alone. Links are explicit (made by promotion or by the user).
- A todo update's result never arrives (the session was killed): the last confirmed list stands, and the pending update is never applied.
- A Codex file is half-written when read: the partial last line is not parsed until it is complete. Malformed complete lines count as drift.
- A project is archived while automations reference it: those automations say the project is archived when they run. They do not silently brief on nothing.
- A linked repository is force-pushed or rebased: commits that disappear stay in the evidence history, marked as no longer on the branch, and are not deleted.
- Evidence text fails redaction: the item shows as Withheld, with its source and time still visible.
- The user deletes a task that has evidence: the evidence remains readable in the project's history, attached to "deleted task: <title>".
- Two browser tabs edit the same task: the second save is refused as stale, saying what changed. It does not overwrite.
- Today on a day with no due work, no waiting items and no sources connected: it says what is not connected and how to connect it, once, in muted text.

## Requirements *(mandatory)*

### The ledger

- **FR-001**: The system MUST store, as its own source of truth, Projects, Goals, Tasks, Evidence, Notes and Links. No external tool is required for a personal project.
- **FR-002**: A **Project** MUST have a name and a status (active, paused, done or archived). It MAY have a "why", standing instructions or context for agents working on it, linked repositories and folders, and links.
- **FR-003**: A **Goal** (milestone) MUST belong to a project and have a definition of done. It MAY have a target date.
- **FR-004**: A **Task** MUST have a title and a status (to do, doing, blocked, done or dropped). It MAY have:
  - an owner: the user, an agent, a coding session, or a workflow;
  - a due date;
  - a parent task or goal;
  - declared files (paths or patterns it is expected to touch).
- **FR-005**: A **Note** MUST record what was decided and why, with its time, and MAY link to the conversation it came from.
- **FR-006**: A **Link** MUST connect a project or task to a thread, workflow, coding session, repository or external id. Links are explicit; nothing is linked by title similarity.
- **FR-007**: Every change to the ledger MUST record who made it (the user, or the assistant on the user's confirmation) and when. A deleted item's evidence MUST remain readable.

### Capture from chat

- **FR-008**: *Initiation.* The assistant MUST NOT propose creating, changing or deleting ledger items, or automations, because of content it read (tool results, web pages, email, session logs). Only a user turn may cause a proposal. (Article XIII: separate from FR-009.)
- **FR-009**: *Confirmation.* No ledger write proposed by the assistant MAY happen until the user confirms it through a trusted channel. Content inside a tool result MUST NOT satisfy a confirmation. (Article XIII: separate from FR-008.)
  - **Amendment 1 (v1.1, 2026-10-20, user decision; referenced from 006 spec.md):** the routine, reversible ops (create a task, update a task including dropping it, add a note) are Tier 2 instead of confirmed first. Rationale: the user decided that asking before every routine task change costs more than it protects, provided each such write is disclosed and can be undone, and provided content can never cause one by itself.
    - When the write follows from the USER's own message in this turn, it runs, the reply discloses it, and the disclosure carries an Undo that reverts the ledger write (`POST /api/ledger/writes/{write_id}/undo`; refused, changing nothing, if anything it touched was edited since).
    - When it originates from content the agent read (a tool result, an email, a web page, a list cell, a stored run, a subagent's output), it is a SUGGESTION card that runs only when the user confirms it on the card; it never runs by itself and a typed reply does not confirm it. The provenance test is feature 003's (`app/policy/lineage.initiation_origin`, read by `PolicyMiddleware._origin`), not a second model.
    - Which content counts (user decision 2026-10-20, refined): only UNTRUSTED content taints — any tool output not explicitly harness-internal (mail, web, files, list cells, stored runs, MCP reads, a subagent's or called agent's output). The harness's own write acknowledgements (ledger_apply's results, Undo receipts) do not. One classifier decides it (`lineage.tool_result_is_trusted`, default untrusted). So "create tasks A, B and C" runs all three with Undo, but an email read between them makes the later ones suggestions.
    - The taint lasts for the conversation (review round 2): once untrusted content is anywhere in a thread's history, a routine write in that thread is a suggestion card, whatever turn it is in, because that content is still in the model's context and could be steering it. Whether the user's new message "asks for" a write is not something a structural check can know, so it is not attempted. A declined suggestion therefore never comes back as a Tier 2 write on a later "thanks".
    - An unattended workflow run makes routine writes suggestions too (it has no grants or cap).
    - The thread a write links to is the run's own; the model cannot choose it.
    - Everything else ledger_apply offers (a new project or goal, linking a chat) is unchanged: it is confirmed first.
    - DECISION FOR THE USER: in a scheduled run, a routine write under a standing grant MAY be content-originated (006 Clarification 11, by design: the origin is recorded with every granted action). The chat-only taint rule above does not apply there.
    - In a scheduled run, a routine write runs only under the agent's standing grant (006 FR-302).
    - Tests: `backend/tests/studio/test_chat_ledger_writes.py`.
- **FR-010**: Proposals MUST be shown as an in-chat card listing exactly what will be created or changed, editable before confirming. What is stored MUST equal what was confirmed.
- **FR-011**: The user MUST be able to attach a thread to a project, and detach it, from the thread and from the Project view.
- **FR-012**: The user MUST be able to promote items of a thread's agent todo list into project tasks. Each promoted task links to its thread and its todo item, and the thread's own list is not changed.
- **FR-013**: **Evidence never overwrites the plan.** A status change reported by an agent, a session or a workflow MUST be recorded as evidence on the task. It MUST NOT change the task's status. Only the user, or the assistant on the user's confirmation, changes a task's status.
- **FR-014**: The user MUST also be able to create and edit every ledger item directly in the UI, without chat.

### Evidence: general rules

- **FR-015**: Every evidence item MUST record its source, its time, the item it attaches to, and a label: **observed** (the system saw it happen: a commit exists, a run ended with this outcome, a record shows a file was written) or **claimed** (an agent or person said so: a todo marked completed, a message saying "tests pass").
- **FR-016**: A todo item marked completed by an agent MUST be labelled claimed, even when the tool call that marked it succeeded. A successful call confirms that the list changed, not that the work was done.
- **FR-017**: Evidence MUST be recorded once per source event, however many times the source is read.
- **FR-018**: Evidence collection MUST be read-only toward every source. It makes zero writes to session files, repositories, calendars or workflow records. This MUST be verifiable automatically.
- **FR-019**: Evidence text shown in any surface MUST pass display redaction. Text that cannot be safely redacted MUST be shown as **Withheld** (with source and time still visible). It is never shown unredacted and never dropped silently.

### Coding sessions: Claude Code and Codex

- **FR-020**: Codex sessions MUST appear in the same watcher tools, replies and pages as Claude Code sessions, each labelled with its agent. The set of watcher tools, their names and their arguments MUST NOT change (001 FR-018b, FR-023). The new agent shows up as more sessions in the same replies.
- **FR-021**: Codex sessions MUST be discovered under the Codex home (`CODEX_HOME` if set, otherwise the default), in its dated session folders. Archived sessions MUST NOT be read.
- **FR-022**: Codex sessions MUST be selected by file modification time, not by folder date. A repeated session header in one file MUST be read as a resume of the same session.
- **FR-023**: A Codex subagent rollout MUST be attached to its parent session. Both known link shapes MUST be read. A subagent rollout with neither link MUST count as drift.
- **FR-024**: Record types an adapter does not recognise, and complete lines that cannot be parsed, MUST be counted as drift per agent and shown where watcher health is shown. Record types known to carry nothing relevant MUST be listed as inert explicitly, not ignored by default.
- **FR-025**: For each session, the system MUST derive session id, working folder, agent, turn state (started, working, completed, aborted), tool activity (names only), and files changed. Codex turn state comes from its task-started, task-complete and turn-aborted events.
- **FR-026**: The Codex home MUST be made readable to the watcher read-only, by explicit user configuration. When it is not readable, Codex MUST be reported as "can't tell", not as "no Codex sessions".
- **FR-027**: The system MUST NOT add a background service or UI from the reference implementation. Its ideas are ported into the existing watcher.

### Coding sessions: the agents' own todo lists

- **FR-030**: The system MUST track each session's own todo list:
  - for Claude Code, from TodoWrite, TaskCreate and TaskUpdate;
  - for Codex, from `update_plan`.

  Titles and statuses only. Descriptions MUST be dropped at the point of reading.
- **FR-030a**: Todo lists MUST be derived from session records only. Claude Code's on-disk task store MUST NOT be read.
- **FR-031**: A todo change MUST be applied only after the matching tool result confirms success:
  - Claude: a result that is not an error.
  - Codex: an acknowledgement for `update_plan`, and the tool's own success signal otherwise.

  A failed, interrupted, or still-unanswered call MUST leave the last confirmed list in place. A call whose result never arrives is never applied.
- **FR-032**: Where a session's todo item is linked to a ledger task (FR-012 or by the user), its status changes MUST become claimed evidence on that task (FR-013, FR-016).

### Coding sessions: "waiting on you" and optional hooks

- **FR-033**: Without hooks, "waiting on you" MUST remain inferred as today, and labelled **inferred**.
- **FR-034**: The user MAY opt in to Claude Code hooks for permission prompts, idle prompts and task events. When enabled, a permission or idle prompt MUST mark the session as waiting on the user, labelled **observed**.
- **FR-035**: Enabling hooks MUST:
  - show the exact change before applying it, and apply it only on the user's confirmation;
  - add our entries alongside any existing hooks, never replacing or reordering them;
  - be fully reversible: disabling removes exactly what was added;
  - never block, slow or print to Claude Code. Handlers run in the background, produce no output, and exit successfully even when OmniHarness is unreachable.

  - send **only allowlisted fields**: event name, session id, working folder, notification type, and task id and title. Prompt, message and tool text MUST be dropped by the handler itself, before anything leaves the machine's Claude Code process;
  - be installed only by a command the user runs, never automatically;
  - uninstall with a single command that restores the previous settings exactly. If the user edited the settings after installing, uninstall removes only our entries and says so.

  Hook fields relied on MUST be checked against the current Claude Code hooks reference when this is built, and recorded with the date checked.

### Declared vs observed scope

- **FR-036**: A task marked **done** whose declared files (or, if none, its project's linked folders) are modified afterwards, by a linked session or a commit, MUST be flagged "done, but still changing", with the evidence behind it.
- **FR-037**: When a linked session changes files outside its task's declared files, the task MUST be flagged "work outside declared scope", listing the paths (redacted per FR-019).
- **FR-038**: Both flags MUST be labelled as inferences and MUST NOT change a task's status (FR-013). The user can dismiss a flag; dismissing it is recorded.

### Other evidence sources

- **FR-040**: The user MUST be able to link local repository folders to a project. A linked repository is read only with the user's explicit read-only access. A linked but unreadable repository MUST say so and why.
- **FR-041**: Commits on a linked repository MUST be recorded as observed evidence on the project, and on a task when the commit message names it by its short id. Author, time, subject and files changed are recorded; the body only after redaction (FR-019).
- **FR-042**: A workflow run that is linked or assigned to a task MUST record its outcome as observed evidence on that task, once.
- **FR-044**: Every evidence attachment MUST record **why** it was attached, in words the user can read: "matched repo omniHarness", "linked session", "commit names T-3", "promoted from thread". It is shown next to the item. When a source matches more than one project, it attaches to the most specific match, and ties attach to all of them. The user MUST be able to reassign an evidence item manually; the reassignment is recorded and shown as the new reason ("moved here by you").
- **FR-043**: Calendar events MUST be shown on a project when the user links them (an event, or a recurring series), and on Today when they are today. A calendar that is not connected or not reachable reads as "can't tell", not as an empty day.

### Today and the Project view

- **FR-045**: The sidebar MUST be: New chat · Chats · Today · Projects · Automations · Connections · Agents, then More in the footer. Today replaces Inbox in place, and the old Inbox address MUST lead to Today.
- **FR-046**: Today MUST show, in order:
  - **Waiting on you**: approvals pending, sessions waiting, alerts. This is everything the Inbox shows today, with the same count as the sidebar badge.
  - **Due**: overdue first, then due today.
  - **Moved**: evidence since the user last opened Today, or the last 24 hours if never. Each item labelled observed or claimed.
- **FR-047**: The Project view MUST show the project's why and status; its goals with progress; its tasks (grouped by status, each with owner, due date and flags); its evidence (newest first, filterable by source and by observed or claimed); its linked chats, sessions, workflows and repositories; and its decisions.
- **FR-048**: Every action in the Project view and on Today MUST be one click from the item it acts on. Each screen has one solid primary action ("New project", "Add task"); the rest are outline or ghost.
- **FR-049**: The UI MUST use the existing theme tokens only, in light and dark, and pass the AA-contrast check for every new page and state. It MUST be minimal: no decoration that carries no information, plain-text bodies, muted metadata, and no pills styled as code.
- **FR-050**: **Empty vs can't-tell.** Every section that reads a source MUST distinguish "there is nothing" from "this source could not be read", and say which source and why. A source that has never been connected says so once, with how to connect it.
- **FR-051**: Today and the Project view MUST be usable within the same budget as the existing pages: usable in under 500 ms on a direct load with a warm cache, and no heavy library on first load.

### Automations from chat

- **FR-060**: The assistant MUST be able to propose an automation from a chat request (a schedule, what it does, where it is delivered) as an in-chat card. The card states the schedule in words, and FR-008 to FR-010 apply.
- **FR-061**: A confirmed automation MUST be written through the existing Automations write path: the same validation, atomic write and stale-edit refusal, appearing on the Automations page. It MUST NOT be written any other way.
- **FR-062**: A request that the trigger engine cannot express MUST be refused with the reason. It MUST NOT be approximated silently.
- **FR-063**: A scheduled automation MUST run at most once per scheduled time, across workers and restarts.
- **FR-064**: Briefs created this way MUST read the ledger at run time. When the ledger cannot be read, the brief MUST say so.

### Triggers and policy

- **FR-065**: The morning brief, overdue alerts and "blocked on you" alerts MUST read the ledger through the gateway's API (Article I), and follow quiet hours, coalescing and presence routing (Article VII).
- **FR-066**: Any action the assistant takes on the user's behalf from the ledger (running an assigned workflow, creating an MCP connector, writing an automation) MUST go through the policy layer like every other tool call (Article II).
- **FR-067**: When a project needs a data source that does not exist, the assistant MAY propose building an MCP connector for it through the existing MCP Suite. The proposal is a Tier 3 plan, and building is subject to the Suite's own checks.

### Carried-forward engineering rules

- **FR-070**: **Wiring gate from day one.** Every public definition this feature adds MUST be reached from production code, or listed in the wiring whitelist with a reason that is not "unwired". The feature MUST merge with zero new "unwired" entries, and MUST resolve the 10 entries it inherits (`plan-inputs.md`): each one wired, or deleted with a reason.
- **FR-071**: **Integration through the production composition root.** At least one test per user story MUST build the system the way production builds it:
  - the gateway through its real application factory and startup;
  - the watcher through its real server wiring;
  - the trigger engine through its real loop builder.

  It must not hand-assemble components. Each such test MUST name the structural difference it defends against (Article XI).
- **FR-072**: **Empty vs can't-tell** (FR-050) applies to every API response this feature adds, not only to pages. A response that could not read a source MUST say so in a field, and MUST NOT return an empty list.
- **FR-073**: **Withheld for redaction** (FR-019) applies to every surface that shows evidence text, session text, commit text or calendar text, including chat replies that quote it.
- **FR-074**: Every check this feature adds MUST be seen failing once, by a sabotage, before it is trusted (Article XII).
- **FR-075**: Anything a requirement depends on (default inert-type lists, default mounts, hook templates) MUST ship tracked in the repository (Article XIV).
- **FR-076**: Ported ideas from sodiumsun/agenttrail MUST be credited in a tracked third-party notice with its MIT licence text and copyright line.

### Key Entities

- **Project**: something the user is working toward. It has a name, a why, a status, standing context for agents, linked repositories and folders, and goals, tasks, notes and links.
- **Goal**: a milestone of a project, with a definition of done and an optional target date. Progress is derived from its tasks.
- **Task**: a unit of work. It has a title, status, owner, due date, a parent (task or goal), declared files, flags, evidence and links. Its status changes only by the user, or on the user's confirmation.
- **Evidence**: something seen or said about a task or project. It has a source (git, Claude Code session, Codex session, workflow run, calendar, chat), a time, observed or claimed, a summary, and a reference back to the source. It is append-only.
- **Note / Decision**: what was decided and why, when, and from which conversation.
- **Link**: an explicit connection from a project or task to a thread, workflow, coding session, repository or external id.
- **Session todo list**: a coding session's own list (titles and statuses) as of its last confirmed update. It is not a ledger task until promoted or linked.
- **Flag**: an inference about a task ("done, but still changing", "outside declared scope"). It cites its evidence, can be dismissed, and never changes status.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can capture a project with a goal and three tasks from one chat message and one confirmation, in under a minute.
- **SC-002**: Today shows everything waiting on the user that the Inbox showed before the change: no item is lost in the move, verified against the same fixture.
- **SC-003**: Codex sessions appear in the same session list as Claude Code sessions. The watcher's tool set is unchanged, verified by comparing tool names and arguments before and after.
- **SC-004**: In a fixture where 3 of 10 todo updates fail or never get a result, the displayed list matches the last confirmed state in 10 of 10 checks.
- **SC-005**: Every evidence item shown anywhere carries an observed or claimed label: 100% in an automated sweep of every evidence surface.
- **SC-006**: With every evidence source disconnected or unreadable, no section of Today or the Project view reads as empty. Each names the source it could not read.
- **SC-007**: Enabling and then disabling the hooks upgrade leaves the user's Claude Code settings byte-identical to before.
- **SC-008**: A scheduled automation fired twice for the same time by two workers produces one run.
- **SC-009**: Zero writes to any observed session file, repository or calendar during the whole test suite, verified automatically.
- **SC-010**: Today and the Project view load usably in under 500 ms on a direct load, and pass the AA-contrast check in both themes.

## Assumptions

- Single user. Projects are the user's own; there is no sharing or multi-user permissions in this feature.
- The gateway's database holds the ledger, like the rest of the platform's state. A fresh clone starts with an empty ledger.
- "The user's time zone" is the one the platform already uses for quiet hours and schedules.
- Calendar access uses the calendar connection the user already has in Connections. Without one, calendar evidence is "not connected".
- A commit names a task by the task's short id (for example `T-12`). Nothing is matched by title.
- Codex and Claude Code record formats are as observed on this machine on 2026-10-19 and in the hooks reference fetched that day. Changes are caught as drift, not assumed away.

## Out of Scope (later features)

- Dispatching agents into worktrees to work on tasks.
- Remote approval of coding-agent permission prompts (Article IV: every prompt reaches the human at the machine).
- Importing ChatGPT or Claude conversation history.
- Two-way sync with GitHub, Linear or Notion (Feature 006).
- Hooks for Codex (Codex is read from its files only in 005).
- Sharing projects with other people.

## Clarifications

### Session 2026-10-19

- Q: Is two-way sync with GitHub, Linear or Notion part of 005? → A: No. It is Feature 006 and stays out of 005.
- Q: Evidence matching two projects' linked folders or repositories? → A: Attach to the most specific match; ties attach to both. Every attachment stores and shows **why** it was attached (for example "matched repo omniHarness"), and the user can reassign it manually (FR-044).
- Q: Where are hooks installed? → A: At user level, on five conditions (FR-035):
  - fail-silent with a short timeout, never blocking or slowing a session;
  - merged with the user's existing hooks, never replacing them;
  - only allowlisted fields are sent, never prompt or message text;
  - one uninstall command restores the previous settings exactly;
  - installed only by a command the user runs, never automatically.
- Q: Does Today replace Inbox? → A: Yes. "Blocked on me" is Today's top section, and the badge moves to Today.
- Q: Should Claude Code's on-disk task store be read? → A: No. Only session records are read, and `~/.claude/tasks` MUST NOT be read (FR-030a).
- Q: Does Codex get hooks in 005? → A: No. Codex stays file-only in 005.
