# Feature Specification: Read-Only Coding-Session Watcher

**Feature Branch**: `001-coding-session-watcher`

**Created**: 2026-08-20

**Status**: Draft

**Input**: User description: "Feature 001: Read-Only Coding-Session Watcher — a session watcher module that discovers and monitors Claude Code sessions already running on the user's machine (started in VS Code or a terminal) and exposes their status to the agent core, so the user can ask about them from any channel, including Telegram on their phone."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ask what my coding sessions are doing (Priority: P1)

The user has left one or more coding-agent sessions running on their machine and has walked away
from it. From a remote channel — Telegram on their phone — they ask "what are my sessions doing?"
and receive a short, accurate roll-up: one line per live session naming the project, what state it
is in, and what it last did.

**Why this priority**: This is the entire daily value of the phase — visibility into agent work
without walking back to the machine. Shipped alone, it is already a useful product.

**Independent Test**: Start two coding sessions in different projects, ask the roll-up question
from a remote channel, and confirm both appear with the correct project name and state. Delivers
value with no other story implemented.

**Acceptance Scenarios**:

1. **Given** two coding sessions are running in different projects, **When** the user asks "what
   are my sessions doing?" from a remote channel, **Then** the assistant returns one status line
   per session naming the project, the current state, and the last activity, within seconds.
2. **Given** no coding sessions have ever run on the machine, **When** the user asks for a
   roll-up, **Then** the assistant states plainly that no sessions were found rather than
   inventing one.
3. **Given** one session is actively working and another finished an hour ago, **When** the user
   asks for a roll-up, **Then** each session's state is reported distinctly and the finished
   session is not described as running.

---

### User Story 2 - Spot the session that is blocked on me (Priority: P1)

The user wants to know whether any session has stopped and is waiting on a question, so they know
whether it is worth returning to the machine. They ask "is anything stuck waiting on me?" and the
assistant names the waiting sessions and the question each is waiting on.

**Why this priority**: A session silently blocked on a question is the single most expensive
failure mode the watcher exists to prevent — the difference between a run finishing and an hour
of nothing. It shares P1 with Story 1 because the roll-up is materially incomplete without it.

**Independent Test**: Drive one session into a state where it asks the user a question, then ask
the blocked-session question from any channel and confirm the correct session and its pending
question are named.

**Acceptance Scenarios**:

1. **Given** one session is waiting on a user question and another is working, **When** the user
   asks "is any session stuck waiting on a question?", **Then** only the waiting session is
   named, along with the question it is waiting on.
2. **Given** a session that was waiting receives an answer at the machine and resumes, **When**
   the user asks again, **Then** that session is no longer reported as waiting.
3. **Given** a session is waiting on a question, **When** the user asks the assistant to answer
   it or intervene, **Then** the assistant states plainly that externally-started sessions are
   observe-only in this version and does not attempt to reply into the session.

---

### User Story 3 - Ask about one session in detail (Priority: P2)

The user, having seen the roll-up, drills into a single session by project name: how long it has
been running, what it has done so far, and what its most recent message was.

**Why this priority**: Depends on the roll-up existing to be useful, but converts "something is
happening" into "here is what is happening" — the follow-up question the roll-up always provokes.

**Independent Test**: With one session running, ask about it by project name and confirm the
elapsed time, recent activity summary, and last message are accurate.

**Acceptance Scenarios**:

1. **Given** a session has been running for a known duration, **When** the user asks how long it
   has been running and what it has done, **Then** the elapsed time and an ordered summary of its
   recent activity are returned.
2. **Given** the user names a project that has no matching session, **When** they ask for its
   status, **Then** the assistant says no such session was found rather than guessing at a
   similar one.

---

### User Story 4 - Status stays correct as sessions come and go (Priority: P2)

Sessions are killed, complete on their own, and are started fresh while the watcher runs. The
user's next question reflects reality without anyone restarting the watcher.

**Why this priority**: Without this, the feature degrades into confidently-wrong status within a
working day — a direct Article X defect. It is P2 only because Stories 1–3 must exist to observe
it.

**Independent Test**: While the watcher runs, kill one session, let another complete, and start a
third; then ask for the roll-up and confirm all three are represented correctly.

**Acceptance Scenarios**:

1. **Given** a running session is killed abruptly, **When** the user next asks for status,
   **Then** that session is no longer reported as actively working.
2. **Given** a session completes normally, **When** the user next asks, **Then** it is reported
   as completed, not as working or failed.
3. **Given** a new session starts after the watcher is already running, **When** the user next
   asks, **Then** the new session appears without any watcher restart.
4. **Given** the machine sleeps and wakes with sessions on disk having advanced, **When** the
   user asks after wake, **Then** status reflects the post-wake reality.

---

### Edge Cases

- **Malformed or truncated log entries**: a partially-written or unparseable entry is skipped
  with a debug-level log; the session's other entries still produce status, and the watcher never
  crashes or drops the session.
- **Unrecognized entry types**: entries in a shape the watcher does not know are ignored, not
  treated as errors, and do not change session state.
- **Log format drift after a coding-agent upgrade**: if entries stop parsing entirely, the
  affected sessions are reported as being of unknown state rather than silently reported as idle.
- **Very large or long-running session logs**: status remains answerable without re-reading the
  entire history on every question.
- **A session with no activity for a long period**: distinguished as idle rather than reported as
  actively working.
- **Concurrent sessions in the same project directory**: each is reported as a distinct session
  and is individually addressable.
- **Session records for projects that no longer exist on disk**: still listed, with the project
  identified as it was recorded.
- **Machine sleep/wake and clock changes**: elapsed times remain plausible; the watcher resumes
  observation without restart.
- **The watcher process is started while sessions are mid-run**: pre-existing sessions are
  discovered and reported, not ignored until their next activity.
- **Ambiguous project reference in a user question**: the assistant asks which one rather than
  picking arbitrarily.
- **The observed agent's own summarization is unavailable**: status is still returned using the
  raw last message, with the summary omitted rather than fabricated.

## Requirements *(mandatory)*

### Functional Requirements

**Discovery and registry**

- **FR-001**: The system MUST discover coding-agent sessions that were started outside the
  assistant — in an editor or a terminal — without the user registering them.
- **FR-002**: The system MUST maintain a live registry of discovered sessions, each carrying at
  minimum: a stable session identifier, the project it belongs to, its current state, its most
  recent message, its start time, and its last activity time.
- **FR-003**: The system MUST classify each session into exactly one of: working,
  waiting-on-user, idle, completed, failed, or unknown.
- **FR-004**: The system MUST update a session's state and last activity time as the session
  progresses, without requiring a restart of the watcher.
- **FR-005**: The system MUST discover sessions that begin after the watcher has started, and
  MUST retain sessions that end while the watcher is running, reporting their terminal state.
- **FR-006**: The system MUST report a session whose state cannot be determined as unknown rather
  than defaulting it to any confident state.

**Event normalization**

- **FR-007**: The system MUST normalize raw session activity into a common event vocabulary:
  started, progress, question, completed, failed.
- **FR-008**: Each normalized event MUST carry a one-line human-readable summary, produced at low
  cost, suitable for direct inclusion in a status reply.
- **FR-009**: The system MUST skip activity entries it cannot interpret, recording them at debug
  level, and MUST continue processing subsequent entries for the same session.
- **FR-010**: When a session enters the waiting-on-user state, the system MUST emit an event that
  a future trigger consumer can subscribe to. Nothing in this feature is required to consume it.

**User-facing querying**

- **FR-011**: The assistant MUST be able to answer, on request from any connected channel, a
  roll-up of all known sessions with project, state, and last activity.
- **FR-012**: The assistant MUST be able to answer, on request, the status of a single session
  identified by session identifier or by project name.
- **FR-013**: The single-session answer MUST include elapsed running time, current state, most
  recent message, and a summary of recent activity.
- **FR-014**: Both query capabilities MUST be classified Tier 1 (read) under the action policy
  and execute without confirmation.
- **FR-015**: When the user asks the assistant to answer, intervene in, or otherwise act on an
  observed session, the assistant MUST state plainly that externally-started sessions are
  observe-only in this version, and MUST NOT attempt the action.
- **FR-016**: The assistant MUST NOT report an elapsed time, state, or activity it has not
  observed. Absent information is stated as absent.
- **FR-017**: When a user's project reference matches more than one session, the assistant MUST
  ask which one rather than selecting one.

**Boundaries and operational behavior**

- **FR-018**: The system MUST expose its capabilities to the agent core exclusively through the
  public gateway interface, and MUST NOT depend on agent-core internals.
- **FR-019**: The system MUST perform zero writes to any observed session record. This MUST be
  verifiable automatically.
- **FR-020**: The system MUST operate correctly on both macOS and Windows file path conventions.
- **FR-021**: The system MUST run on the host machine rather than requiring a container, since it
  reads files in the user's home directory.
- **FR-022**: The system MUST consume negligible resources while no session is active, using
  operating-system change notification where available and falling back to infrequent polling
  where it is not.
- **FR-023**: The system MUST isolate all knowledge of the observed agent's record format behind
  a single adapter boundary, so that supporting an additional coding agent later is the addition
  of a new adapter rather than a change to the registry, event model, or query capabilities.
- **FR-024**: The system MUST survive machine sleep and wake, resuming observation of all
  previously known sessions without user action.
- **FR-025**: The system MUST NOT proactively push session status to the user in this phase;
  status is delivered only in response to a user question.

### Key Entities

- **Session**: One coding-agent run observed on the machine. Attributes: stable identifier,
  project it belongs to, current state (working / waiting-on-user / idle / completed / failed /
  unknown), most recent message, start time, last activity time. Sessions are discovered, never
  created by this feature.
- **Session Event**: A normalized occurrence within a session — started, progress, question,
  completed, or failed — carrying a timestamp and a one-line summary. Events belong to exactly
  one Session and are ordered within it.
- **Session Source Adapter**: The boundary that knows how one kind of coding agent records its
  activity and turns that record into Sessions and Session Events. Exactly one adapter is in
  scope for this feature; the boundary exists so others can be added without reworking the rest.
- **Session Registry**: The live collection of all known Sessions, answering both the roll-up and
  the single-session query.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With two coding sessions running in an editor, a user asking "what are my sessions
  doing?" from a remote channel receives an accurate one-line-per-session status within 10
  seconds of asking.
- **SC-002**: When at least one session is waiting on a question, the roll-up identifies which
  session is waiting in 100% of trials.
- **SC-003**: Across a test cycle in which one session is killed, one completes, and one starts
  fresh, the next status answer represents all three correctly without any restart of the
  watcher, in 100% of trials.
- **SC-004**: A session's reported state reflects a change in the underlying session within 10
  seconds of that change.
- **SC-005**: With malformed and truncated activity entries injected into an observed session,
  the watcher continues to answer status for that session and every other session, and does not
  terminate, in 100% of trials.
- **SC-006**: Across a machine sleep/wake cycle, the watcher resumes and answers correctly for
  all previously known sessions with no user action, in 100% of trials.
- **SC-007**: Observed session records are byte-for-byte unchanged after a full observation cycle
  — zero writes — verified automatically on every change to the codebase.
- **SC-008**: The watcher introduces no measurable dependency on agent-core internals, verified
  automatically on every change to the codebase.
- **SC-009**: While no session is active, the watcher's ongoing resource consumption is
  indistinguishable from idle over a 1-hour observation window.
- **SC-010**: When the user asks the assistant to act on an observed session, the assistant states
  the observe-only limitation in 100% of trials and never simulates having acted.
- **SC-011**: Adding support for a second kind of coding agent later requires changes confined to
  a new adapter, with no change to the registry, event model, or query capabilities.

## Assumptions

- The user is the sole operator of the machine; all discovered sessions belong to them, and no
  multi-user access control is in scope.
- The observed coding agent records its activity locally in a readable form under the user's home
  directory, and that record is complete enough to infer the six session states.
- The observed agent's record format is not a stable public interface and may change without
  notice; tolerating drift is a requirement of the feature rather than an exceptional case.
- Exactly one coding agent is supported in this phase. A second (Codex) is deliberately out of
  scope because its local record story differs; the adapter boundary is the accommodation for it.
- Remote querying reaches the assistant through channels that already exist (Telegram, web UI,
  local voice); this feature adds no new channel.
- Proactive notification of a waiting session is out of scope and belongs to the next phase; this
  feature only emits the event such a consumer would subscribe to.
- Sessions are read where the coding agent already writes them; the watcher stores no copy of
  session content beyond what its live registry needs to answer questions.
- Historical sessions from before the watcher first ran may be discovered; retention and pruning
  of long-past sessions follow ordinary local-cache practice and are not user-configurable in
  this phase.
- Answering a roll-up may involve summarizing recent activity; summarization is expected to be
  cheap and is not required to be perfect, only honest about what it saw.
