# Feature Specification: Read-Only Coding-Session Watcher

**Feature Branch**: `001-coding-session-watcher`

**Created**: 2026-08-20

**Status**: Draft

**Input**: User description: "Feature 001: Read-Only Coding-Session Watcher — a session watcher module that discovers and monitors Claude Code sessions already running on the user's machine (started in VS Code or a terminal) and exposes their status to the agent core, so the user can ask about them from any channel, including Telegram on their phone."

## Clarifications

### Session 2026-08-20

- Q: What should make the watcher call a session "idle" rather than "working"? → A: Marker
  first, inactivity timeout as fallback. An observed end-of-turn record makes a session idle
  immediately; absent one, a configurable inactivity period (default 5 minutes) does. The two
  paths MUST stay distinguishable — **completed** (marker observed) vs **stalled** (timeout
  inferred) — because they are different facts prompting different user action, and Article X
  forbids reporting an inference as an observation.

- Q: Where should the model that writes the one-line activity summaries run — on the user's
  machine, or in the cloud? → A: On the machine. A local model may be loaded on demand and
  released afterward; where none is configured, a mechanical derivation is used. The mechanical
  path is a first-class default, not a degraded error state. Cloud summarization is explicit
  opt-in only. Every summary records whether it was model-generated or mechanical.

- Q: If the user asks for session status while the watcher process is not running or has fallen
  behind, what should the assistant tell them? → A: Answer live when the watcher is healthy.
  When it is down or stale, state that first and then offer last-known data explicitly labelled
  as last-known with its age. Liveness is measured by heartbeat (default every 30 seconds) with
  a staleness threshold (default 90 seconds), both configurable. Recorded reason: a silently
  dead watcher returns an empty registry, and an empty registry renders as "you have no sessions
  running" through an entirely normal code path — a false negative that reads as fact and sends
  the user away from a machine that is still working.

- Q: On its first start, how far back into previously recorded session history should the
  watcher reach? → A: A configurable recency window on last activity, defaulting to 24 hours,
  governs what is listed. Any session observed active while the watcher runs is listed
  regardless of when it started, and its membership is sticky — it stays in the registry until
  it reaches a terminal state or the retention reset, rather than being re-tested against the
  window on each query. Candidate records are selected by modification time before any are
  parsed, so the window bounds what is read as well as what is listed. Startup cost is bounded
  in two parts: structurally, the count of records opened and parsed scales with the window
  rather than the directory; and visibly, the first status query is answerable within 5 seconds
  of launch regardless of history size. The structural half is asserted on files opened, not
  elapsed time, because a wall-clock-only bound passes on fast hardware even when a full scan
  has been reintroduced.

- Q: Before a session summary or last message is sent out to a remote channel, should its
  content be redacted? → A: Yes, channel-aware. The redactor runs on every outbound reply
  including local ones — channel awareness governs how aggressive it is, not whether it runs.
  Remote channels additionally shorten paths and trim code fragments. The filter removes
  *recognized* secret patterns and the spec claims nothing stronger. Redaction failure suppresses
  the send rather than passing content through. Redactions appear as visible markers, never as
  silent removals.

- Q: Does the gateway support external tool registration, as FR-018 assumed? → A: No. Verified
  by reading the code on 2026-08-20: there is no registration API, and tools reach the agent from
  exactly two sources — `local:<server>` (MCP) and `connector:<SLUG>` (Composio). The watcher
  therefore integrates as an MCP server declared in `extensions_config.json`. It MUST be reachable
  over SSE rather than stdio, because a stdio server is spawned as a subprocess of the backend and
  so cannot read the host's session directory when the backend runs in a container — which would
  collide with FR-021. This strengthens Article I rather than weakening it: an MCP server imports
  nothing from core at all. The spec's intent was correct; only its wording named a mechanism that
  does not exist.

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
3. **Given** one session is actively working and another recorded its end-of-turn an hour ago,
   **When** the user asks for a roll-up, **Then** each session's state is reported distinctly,
   and the finished session is described as completed rather than as running or as stalled.

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

1. **Given** a running session is killed abruptly and writes no end-of-turn record, **When** the
   inactivity period has elapsed and the user asks for status, **Then** that session is reported
   as idle/stalled, described as possibly stalled or killed rather than as finished.
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
- **A session's last message contains a recognized credential pattern**: the pattern is replaced
  with a visible marker on every channel, and the reply is still delivered.
- **A session's last message contains a secret in an unrecognized shape**: it passes through.
  This is a stated limitation of pattern matching, not a defect to be papered over with a
  stronger claim in the docs.
- **The redactor itself errors while preparing a reply**: the send is suppressed with an explicit
  "can't safely relay this, check locally"; no partially-redacted or unredacted text goes out.
- **A reply is bound for a local channel**: redaction still runs, at lower aggressiveness — paths
  and code fragments are preserved, recognized secret patterns are not.
- **The watcher is not running when the user asks**: the assistant states that session state
  cannot currently be observed, and never reports an empty or stale registry as "no sessions
  running".
- **The watcher is running but its heartbeat has aged past the staleness threshold**: replies
  lead with the staleness caveat and its age, then give last-known data so labelled.
- **The watcher recovers between two questions**: the second answer is live and carries no
  caveat, without the user taking any action.
- **A machine with months of accumulated session history**: startup selects only records whose
  modification time falls inside the recency window; the remainder are never parsed.
- **A long-running session that goes quiet past the recency window mid-run**: remains listed,
  because its membership was earned by observed activity and is sticky until it terminates.
- **A session that started before the window but is still active**: appears in the roll-up as
  soon as it shows any activity while the watcher is running.
- **A session with no activity for a long period**: once the inactivity period elapses with no
  end-of-turn record, reported as idle/stalled rather than as actively working — and never as
  completed, since no completion was observed.
- **A legitimately quiet session** (long build, slow test suite): not reported as stalled until
  the configured inactivity period elapses; raising that period is the supported remedy.
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
- **No local summarization model is configured**: summaries are produced mechanically and
  status is fully answerable; this is an ordinary operating mode, not a failure, and the
  assistant does not warn about it or silently escalate to a cloud provider.
- **A local model is configured but fails to load or errors mid-summarization**: the system falls
  back to mechanical derivation for that summary and marks it as such, rather than omitting the
  line or fabricating one.

## Requirements *(mandatory)*

### Functional Requirements

**Discovery and registry**

- **FR-001**: The system MUST discover coding-agent sessions that were started outside the
  assistant — in an editor or a terminal — without the user registering them.
- **FR-002**: The system MUST maintain a live registry of discovered sessions, each carrying at
  minimum: a stable session identifier, the project it belongs to, its current state, its most
  recent message, its start time, and its last activity time.
- **FR-003**: The system MUST classify each session into exactly one of: working,
  waiting-on-user, idle, failed, or unknown.
- **FR-003a**: A session in the idle state MUST additionally record how it reached that state:
  **completed** — an end-of-turn or stop record was observed — or **stalled** — the inactivity
  period elapsed with no such record, so the session may have finished, crashed, or been killed.
  A summary reply MAY roll both up as idle, but the underlying distinction MUST be retained and
  MUST be available on request.
- **FR-004**: The system MUST update a session's state and last activity time as the session
  progresses, without requiring a restart of the watcher.
- **FR-005**: The system MUST discover sessions that begin after the watcher has started, and
  MUST retain sessions that end while the watcher is running, reporting their terminal state.
- **FR-005a**: The set of sessions the system lists MUST be bounded by a configurable recency
  window on last activity, defaulting to 24 hours. Sessions quieter than the window are not
  listed.
- **FR-005b**: Any session observed active while the watcher is running MUST be listed
  regardless of when it started, and MUST NOT be excluded by the recency window.
- **FR-005c**: Registry membership earned under FR-005b MUST be sticky: once a session has been
  observed active, it MUST remain in the registry until it reaches a terminal state (per FR-006a)
  or until the retention reset, and MUST NOT be re-tested against the recency window on
  subsequent queries. Rationale: re-evaluating the window per query lets a long-running session
  that goes quiet during a slow build age out mid-run and vanish from the roll-up while still
  alive — the exact failure FR-005b exists to prevent.
- **FR-005d**: At startup the system MUST select candidate session records by modification time
  before parsing any of them, so that the recency window bounds the volume of data read and not
  merely the set of sessions listed.
- **FR-005e**: The number of session records opened and parsed at startup MUST scale with the
  recency window rather than with the size of the session directory. This MUST be verified by
  asserting on the count of records opened, not on elapsed time: a wall-clock-only bound passes
  on fast hardware even when a full directory scan has been reintroduced.
- **FR-006**: The system MUST report a session whose state cannot be determined as unknown rather
  than defaulting it to any confident state.
- **FR-006a**: The system MUST resolve working-to-idle by marker first and time second: on
  observing an end-of-turn or stop record it MUST mark the session idle/completed immediately,
  and only where no such record is observed MUST it fall back to marking the session
  idle/stalled once the inactivity period has elapsed.
- **FR-006b**: The inactivity period MUST be user-configurable, with a documented default of 5
  minutes. Rationale: long builds and slow test suites legitimately produce quiet stretches, and
  a fixed short timeout would misreport them as stalled.

**Event normalization**

- **FR-007**: The system MUST normalize raw session activity into a common event vocabulary:
  started, progress, question, completed, failed.
- **FR-008**: Each normalized event MUST carry a one-line human-readable summary, produced at low
  cost, suitable for direct inclusion in a status reply.
- **FR-008a**: Summary generation MUST happen on the user's machine by default. Session content
  MUST NOT be transmitted to any third-party provider unless the user has explicitly opted in.
  Where a local model is used it MUST be loaded for the summarization and released afterward
  rather than held resident, so that idle resource use stays within the daemon's budget.
- **FR-008b**: Where no local model is configured, the system MUST derive the summary
  mechanically, and this path MUST be treated as a first-class default rather than an error
  state. Mechanical derivation MUST take the most recent assistant message, strip code blocks
  and terminal control sequences, and clip at a sentence boundary — never at a raw character
  count that can sever a word or leave a dangling fragment.
- **FR-008c**: Every summary MUST record whether it was model-generated or mechanically derived,
  and that provenance MUST be readable by downstream consumers, so that a future consumer — for
  example one speaking summaries aloud — can treat the two differently.
- **FR-009**: The system MUST skip activity entries it cannot interpret, recording them at debug
  level, and MUST continue processing subsequent entries for the same session.
- **FR-010**: When a session enters the waiting-on-user state, the system MUST emit an event that
  a future trigger consumer can subscribe to. Nothing in this feature is required to consume it.

**User-facing querying**

- **FR-011**: The assistant MUST be able to answer, on request from any connected channel, a
  roll-up of all known sessions with project, state, and last activity.
- **FR-011a**: The system MUST distinguish "no sessions are running" from "session state cannot
  currently be observed", and the assistant MUST NOT render the second as the first. Rationale: a
  silently dead watcher returns an empty registry, and an empty registry renders as "you have no
  sessions running" through an entirely normal code path — a false negative that reads as fact
  and sends the user away from a machine that is still working.
- **FR-011b**: When the registry is stale, the assistant's reply MUST lead with the health
  caveat and only then give last-known data, labelled as last-known with its age — "I haven't
  seen your sessions for 20 minutes; as of then, two were working", never the reverse ordering.
  Ordering is a requirement rather than presentation polish: a later phase will speak these
  replies aloud, and a caveat that arrives after the data can be acted on before it is heard.
- **FR-011c**: Session-derived content MUST pass through a redaction filter before inclusion in
  any outbound reply, on every channel including local ones. Channel trust governs the filter's
  aggressiveness, not whether it runs: remote channels additionally shorten file paths and trim
  code fragments. Rationale for running it locally too — a filter exercised only on the remote
  path is a filter whose failures surface first in front of the least recoverable audience.
- **FR-011d**: The redaction filter removes **recognized secret patterns**. Neither the spec, the
  documentation, nor any user-facing message may describe it as removing secrets. Per Article X
  that is a guarantee pattern matching cannot honour, and stating it would be the fake precision
  the article names as a defect. Its stated limitation is that unrecognized shapes pass through.
- **FR-011e**: If redaction fails or errors for any part of a reply, the system MUST suppress
  that send and say so explicitly — for example "can't safely relay this, check locally". It MUST
  NOT fall back to sending unredacted content. The filter fails closed.
- **FR-011f**: Every redaction MUST be visible in the delivered text as an explicit marker (for
  example `[redacted]`), never a silent removal. Rationale: a silently dropped credential yields
  a message that reads as complete but is not — the same false-confidence failure as an empty
  registry rendering as "no sessions running" in FR-011a.
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
- **FR-016a**: When reporting an idle session, the assistant MUST convey which of the two paths
  applies, in wording that marks the observed case as fact and the inferred case as inference —
  e.g. "finished 10 minutes ago" for completed, versus "hasn't moved in 12 minutes; may have
  stalled or been killed" for stalled. It MUST NOT present a stalled session as completed.
- **FR-017**: When a user's project reference matches more than one session, the assistant MUST
  ask which one rather than selecting one.

**Boundaries and operational behavior**

- **FR-018**: The system MUST expose its capabilities to the agent core as an MCP server
  declared in `extensions_config.json`, surfaced to the agent as a `local:<name>` tool source. It
  MUST NOT import from or otherwise depend on agent-core internals. Rationale: the gateway
  exposes no external tool-registration API — tools reach the agent only as `local:<server>`
  (MCP) or `connector:<SLUG>` (Composio) — and an MCP server satisfies Constitution Article I
  more strongly than a registration API would, since a separate process speaking a standard
  protocol imports nothing from core by construction.
- **FR-018a**: The system MUST be reachable over SSE at a host-local address, and MUST NOT be
  integrated as a stdio MCP server. Rationale: a stdio server is spawned as a subprocess of the
  backend, so when the backend runs in a container it cannot read the host's session directory —
  directly colliding with FR-021. The existing `github-issue-connector` entry in
  `extensions_config.json`, an SSE server reached at `http://host.docker.internal:<port>/sse`, is
  the precedent shape.
- **FR-018b**: The MCP tool surface MUST remain the system's only integration point with the
  agent core. No capability may be added by a path that bypasses it.
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
  of a new adapter rather than a change to the registry, event model, or exposed tool surface.
  The MCP tool surface described in FR-018 is the stable contract: adding an adapter MUST NOT
  change the set of tools the agent sees, their names, or their arguments — a second observed
  agent appears as additional sessions in the same replies, not as new tools.
- **FR-024**: The system MUST survive machine sleep and wake, resuming observation of all
  previously known sessions without user action.
- **FR-024a**: The system MUST emit a liveness heartbeat on a configurable interval, defaulting
  to 30 seconds, and the query path MUST treat the registry as stale when the most recent
  heartbeat is older than a configurable threshold, defaulting to 90 seconds. Both values carry
  stated defaults so that "lagging" is a testable condition rather than a judgment call deferred
  into implementation.
- **FR-025**: The system MUST NOT proactively push session status to the user in this phase;
  status is delivered only in response to a user question.

### Key Entities

- **Session**: One coding-agent run observed on the machine. Attributes: stable identifier,
  project it belongs to, current state (working / waiting-on-user / idle / failed / unknown),
  idle reason where the state is idle (completed = end-of-turn observed, stalled = inactivity
  inferred), most recent message, start time, last activity time. Sessions are discovered, never
  created by this feature.
- **Session Event**: A normalized occurrence within a session — started, progress, question,
  completed, or failed — carrying a timestamp, a one-line summary, and that summary's provenance
  (model-generated or mechanically derived). Events belong to exactly one Session and are ordered
  within it.
- **Session Source Adapter**: The boundary that knows how one kind of coding agent records its
  activity and turns that record into Sessions and Session Events. Exactly one adapter is in
  scope for this feature; the boundary exists so others can be added without reworking the rest.
- **Session Registry**: The live collection of all known Sessions, answering both the roll-up and
  the single-session query. Carries its own liveness: the time of the most recent heartbeat, and
  therefore whether its contents are current or stale, so that an empty registry and an
  unobservable one are never conflated.

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
- **SC-004a**: A session that records an end-of-turn is reported as completed, and a session
  killed without one is reported as possibly stalled, with the two never conflated, in 100% of
  trials.
- **SC-004b**: A session that goes quiet for longer than a short interval but less than the
  configured inactivity period is still reported as working, in 100% of trials — verifying that
  legitimately slow work is not misreported as stalled.
- **SC-004c**: With no cloud provider opted into, no session content leaves the machine during a
  full observation-and-query cycle, verified by observing outbound traffic, in 100% of trials.
- **SC-004d**: With no local model configured, every session still yields a readable one-line
  summary containing no code-block or terminal-control residue and no mid-word truncation, in
  100% of trials.
- **SC-004e**: With the watcher stopped while sessions are running, a status question yields a
  reply that states the sessions cannot currently be observed, and never states that no sessions
  are running, in 100% of trials.
- **SC-004f**: Every reply drawn from a stale registry presents the health caveat before any
  session data, and states the data's age, in 100% of trials.
- **SC-004g**: With a history directory containing sessions far older than the recency window,
  only sessions inside the window (plus any observed active) are listed, in 100% of trials.
- **SC-004h**: A session observed active and then quiet beyond the recency window remains listed
  for the rest of its run, in 100% of trials.
- **SC-004i**: Against a synthetic history directory holding several thousand sessions of which
  only a handful fall inside the recency window, the number of session records opened and parsed
  at startup remains proportional to the handful, not to the several thousand — asserted on
  records opened rather than on elapsed time.
- **SC-004j**: The watcher answers its first status query within 5 seconds of launch regardless
  of session-history size, comfortably inside the SC-001 answer budget.
- **SC-004k**: With recognized credential patterns seeded into session content, no such pattern
  appears in any delivered reply on any channel, and each is replaced by a visible marker rather
  than silently dropped, in 100% of trials.
- **SC-004l**: With the redactor forced to error, the reply is suppressed with an explicit
  can't-relay message and no session-derived content is delivered, in 100% of trials.
- **SC-004m**: Replies to remote channels contain no full filesystem paths and no multi-line code
  fragments, while replies to local channels retain them, in 100% of trials.
- **SC-005**: With malformed and truncated activity entries injected into an observed session,
  the watcher continues to answer status for that session and every other session, and does not
  terminate, in 100% of trials.
- **SC-006**: Across a machine sleep/wake cycle, the watcher resumes and answers correctly for
  all previously known sessions with no user action, in 100% of trials.
- **SC-007**: Observed session records are byte-for-byte unchanged after a full observation cycle
  — zero writes — verified automatically on every change to the codebase.
- **SC-008**: The watcher introduces no measurable dependency on agent-core internals, verified
  automatically on every change to the codebase.
- **SC-008a**: The watcher's capabilities are reachable by the agent solely through its declared
  MCP tool source; disabling that source removes them entirely, with no residual path, in 100% of
  trials.
- **SC-008b**: With the backend running in a container, the watcher reads the host's session
  directory and answers status correctly — the case a stdio integration could not satisfy.
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
- The default heartbeat interval of 30 seconds and staleness threshold of 90 seconds are
  starting values chosen to tolerate two missed heartbeats before declaring staleness; both are
  configurable for machines where that proves too tight or too loose.
- The 5-minute default inactivity period is a starting value, not a researched one; it is
  configurable precisely because the right value depends on the user's typical build and test
  durations.
- Sessions are read where the coding agent already writes them; the watcher stores no copy of
  session content beyond what its live registry needs to answer questions.
- Historical sessions from before the watcher first ran may be discovered; retention and pruning
  of long-past sessions follow ordinary local-cache practice and are not user-configurable in
  this phase.
- Answering a roll-up may involve summarizing recent activity; summarization is expected to be
  cheap and is not required to be perfect, only honest about what it saw.
- Redaction is pattern-based and therefore best-effort by construction; the spec's claims about
  it are deliberately scoped to recognized patterns so that no user-facing surface overstates
  what it can do.
- The gateway's tool surface is fixed at two sources (MCP and Composio connectors); this was
  verified against the code rather than assumed, after an earlier draft of this spec named a
  registration API that does not exist.
- Remote channels (for example Telegram) transit third-party infrastructure, which is why
  content reduction on those channels is a default rather than an option.
- A machine with no local model configured is a supported, unremarkable configuration; the
  mechanical summary path is expected to be the common case rather than a rare fallback.
