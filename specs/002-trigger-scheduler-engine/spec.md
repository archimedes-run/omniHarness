# Feature Specification: Trigger & Scheduler Engine

**Feature Branch**: `002-trigger-scheduler-engine`

**Created**: 2026-08-21

**Status**: Draft

**Input**: User description: "A rule engine that lets the assistant speak first. Rules evaluate on a clock tick or on an inbound event; when a rule fires, it injects a synthetic user turn into a target thread. Because a fired trigger is just a turn, the existing agent core handles it with all its current machinery — skills, tools, memory — and no new execution path is introduced."

## Clarifications

### Session 2026-08-21

- Q: What makes two trigger events "the same event", for the purpose of not firing twice? → A:
  Rule id + event identifier + a **state fingerprint**, so a changed condition counts as a new
  event. Two constraints pin it down. First, the fingerprint's inputs are enumerated explicitly
  and MUST contain only fields that change when the event genuinely changes — for a blocked
  session that is the question text, never elapsed time or a last-activity timestamp. A
  self-drifting input makes every evaluation produce a "new" event, which is option A's failure
  inverted and the worse of the two, because that is the version that gets the feature muted.
  Second, fingerprints are discarded on a daily reset: without it the store grows unbounded in a
  process that now shares the gateway's memory, and a fingerprint older than a day has no live
  event left to suppress.

- Q: Which thread does a fired rule's synthetic turn go into? → A: One stable thread per rule,
  created on first fire and reused thereafter — so a morning briefing remembers yesterday's,
  while unrelated rules stay out of each other's context. Two constraints. The thread carries a
  **rolling window of recent firings** with a stated default, because a rule thread's value is
  remembering the last few firings and not the last few hundred; beyond that it is
  context-window ballast degrading the continuity it exists to provide. And the rule-id →
  thread-id mapping **persists across restarts**, following the existing channel-manager pattern
  — without persistence, every restart orphans the thread and starts fresh, which looks like a
  stable thread in the spec and behaves like a fresh one in practice.

- Q: Does a proactive reply pass through Feature 001's redactor before delivery? → A: Yes, at
  the delivery boundary, for **every** destination and not only remote ones — same reasoning as
  001, so the path is exercised where failures are visible. Three things are stated as
  requirements rather than inherited. Redaction **fails closed**: an error suppresses delivery
  with the can't-relay message, which matters more here than in 001 because no human is waiting
  on the reply and a silent pass-through would be invisible. The **pattern set widens** in this
  feature, because agent output can carry shapes session records did not — cloud credentials,
  bearer tokens, private-key headers, env-style assignments. And the honesty wording carries
  forward unchanged: *recognized patterns*, never *secrets*. *Considered and rejected*:
  restricting proactive output to state and timing only. That would be safe and useless — "a
  session needs you", with no indication what it wants, sends the user to their laptop to find
  out, which is the exact trip this feature exists to prevent.

- Q: Is a non-urgent firing inside quiet hours dropped, or held until quiet hours end? → A:
  **Deferred with a re-check at release** — the condition is re-evaluated when the window opens
  and only items still true are delivered. This keeps the session that blocked overnight, which
  is the case the feature exists for, and drops the stale ones that cost trust. Two constraints.
  Event types with **no re-checkable condition** — cron and completion, which already happened
  and have no live state — MUST expire rather than deliver blind, so that "re-check" is never
  implemented as "deliver anything we cannot disprove"; the asymmetry is that a missed briefing
  is worthless by morning while a blocked session is not. And the release MUST go **through
  coalescing**: six surviving items arrive as one message, not six. That is a different code
  path from the several-rules-fired-within-30-seconds case and the one most likely to bypass
  coalescing by accident — a backlog flush arriving as a notification storm is exactly the
  behaviour that gets the feature muted.

- Q: What happens to a proactive turn queued behind an exchange that never ends? → A: **Bound
  the wait, then re-check and release through coalescing** — the same mechanism quiet-hours
  release uses, entered under a different condition, not a second implementation of the same
  idea. Two things are stated rather than left to the rationale. The bound's default is a
  **heuristic and the spec says so**: a user who closed the tab and one who is reading and about
  to type are indistinguishable, so any bound is an assumption about human behaviour, and
  Article X forbids presenting a guess as a derived value. And the case where the
  exchange-complete signal **never fires at all** — a hung or abandoned run may emit nothing —
  means the bound is not a fallback for a rare case but the **only** path that will ever release
  those items; it must be implemented as load-bearing rather than as an edge case.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Tell me a session is blocked while I'm away (Priority: P1)

The user has walked away from a coding session. It stops and asks a question. Without being
asked anything, the assistant messages them on their phone to say which session is waiting and
what it appears to be waiting on. It does this once — not once a minute until they answer.

**Why this priority**: This is the payoff for Feature 001, which already emits the event and has
nothing listening. It is also the single clearest expression of the product thesis: the
assistant tells you something you did not know to ask about.

**Independent Test**: Drive a watched session into a waiting state, confirm exactly one message
arrives on the remote channel naming that session, and confirm no further messages arrive while
the session stays blocked.

**Acceptance Scenarios**:

1. **Given** a rule matching waiting-on-user events and a watched session that becomes blocked,
   **When** the watcher emits the event, **Then** one message is delivered to the rule's output
   destination naming the session and its apparent question, within the stated bound.
2. **Given** that message has been delivered and the session remains blocked, **When** further
   evaluation cycles run, **Then** no additional message is delivered for the same block.
3. **Given** the session is answered and later blocks again on a different question, **When** the
   watcher emits a new event, **Then** a message is delivered — this is a new event, not a repeat.
4. **Given** a rule whose match criteria do not cover the emitted event, **When** the event
   arrives, **Then** that rule does not fire.

---

### User Story 2 - A briefing that arrives on its own schedule (Priority: P1)

The user has a rule that fires each weekday morning asking for a summary of what happened
overnight. It arrives at the configured time, once, every day — including on days the machine
slept through the scheduled moment.

**Why this priority**: Shares P1 with Story 1 because it exercises the other half of the engine:
clock-driven evaluation, which has entirely different failure modes (missed ticks, double
fires, drift) from event-driven evaluation. Either alone leaves the engine half-proven.

**Independent Test**: Configure a scheduled rule, run across several scheduled times including
a sleep/wake cycle, and confirm one delivery per scheduled time with none missed and none
duplicated.

**Acceptance Scenarios**:

1. **Given** a rule scheduled for a specific time, **When** that time arrives, **Then** the rule
   fires once and its reply is delivered.
2. **Given** the machine was asleep at the scheduled time, **When** it wakes, **Then** the rule
   fires once — a missed schedule is honoured late rather than skipped silently.
3. **Given** a rule has already fired for a scheduled time, **When** evaluation runs again within
   that same scheduled window, **Then** it does not fire a second time.
4. **Given** the engine restarts between two scheduled times, **When** the next time arrives,
   **Then** the rule fires normally and does not re-fire for times already served.

---

### User Story 3 - Several things happen at once and I get one message (Priority: P1)

Three rules fire within a short span. The user receives a single message covering all three,
not three notifications in a row.

**Why this priority**: Article VII makes this a requirement rather than a refinement, and it is
P1 because a proactive feature that is impolite gets muted — after which every other requirement
in this document is moot.

**Independent Test**: Cause three rules to fire inside the coalescing window and confirm exactly
one delivered message containing all three.

**Acceptance Scenarios**:

1. **Given** three rules fire within the coalescing window, **When** delivery occurs, **Then**
   one message is delivered and it contains all three results.
2. **Given** two rules fire far apart, **When** delivery occurs, **Then** two separate messages
   are delivered — coalescing must not delay unrelated items indefinitely.
3. **Given** a rule fires while a coalescing window is already open, **When** the window closes,
   **Then** that rule's result is included rather than starting a new window.

---

### User Story 4 - Don't wake me, and don't talk over me (Priority: P1)

Nothing non-urgent arrives during the user's configured quiet hours. Nothing arrives in the
middle of an exchange the user is already having with the assistant.

**Why this priority**: Also Article VII, and also P1. A message at 3am and a message that lands
mid-sentence are the two failures that end a proactive feature's life.

**Independent Test**: Fire a non-urgent rule inside quiet hours and confirm nothing is delivered
but the suppression is recorded; mark it urgent and confirm it is delivered. Separately, fire a
rule while an exchange is in progress and confirm delivery happens after it.

**Acceptance Scenarios**:

1. **Given** quiet hours are configured and a non-urgent rule fires inside them, **When**
   delivery is attempted, **Then** nothing is delivered and the reason is recorded.
2. **Given** the same rule marked urgent, **When** it fires inside quiet hours, **Then** it is
   delivered.
3. **Given** the user is mid-exchange on the target thread, **When** a rule fires, **Then** the
   proactive turn waits and is injected after the exchange completes.
4. **Given** a queued proactive turn and an exchange that ends, **When** the exchange completes,
   **Then** the queued turn proceeds without user action.

---

### User Story 5 - Change the rules without stopping the assistant (Priority: P2)

The user edits the rule file — adds a rule, changes a schedule, deletes one — and the change
takes effect without restarting anything.

**Why this priority**: P2 because Stories 1–4 deliver value with a fixed rule set. But rules are
the feature's whole interface, and a change that requires a restart makes experimenting with
them expensive enough that nobody does.

**Independent Test**: Add, modify, and remove rules while the engine runs, and confirm each
change takes effect on the next evaluation without a restart.

**Acceptance Scenarios**:

1. **Given** a running engine, **When** a rule is added to the config, **Then** it becomes
   eligible to fire without a restart.
2. **Given** a running engine, **When** a rule is removed, **Then** it stops firing.
3. **Given** a config edit that is invalid, **When** it is loaded, **Then** the previous valid
   configuration stays in effect and the error is reported — a typo must not disarm the engine.

---

### Edge Cases

- **A rule fires for the first time**: its thread is created and the mapping recorded, before
  the turn is injected.
- **A rule's recorded thread has been deleted out from under it**: treated as a first firing —
  a new thread is created and the mapping updated, rather than the rule failing permanently.
- **A rule is renamed or its id changes**: it is a different rule and gets a different thread;
  the old mapping is not silently inherited.
- **Two rules are configured with the same id**: rejected at load as an invalid configuration
  (FR-006), since the id is the mapping key.
- **The same condition is evaluated many times without changing**: exactly one firing, no
  matter how many cycles run.
- **A condition changes back to a previously-seen value** (a session blocks on question A, is
  answered, then blocks on question A again): this is a new event and fires, because the prior
  fingerprint for that event was consumed when the block was resolved.
- **A rule errors repeatedly**: it is reported and backed off rather than retried forever at
  full rate. Silent infinite retry is a defect.
- **One rule's failure**: never halts evaluation of other rules, and never stops the engine.
- **The event source is unreachable** (the session watcher is down or on the far side of a
  network partition): watcher-type rules do not fire, the condition is observable, and the
  engine does not report "nothing is happening" as though it had looked.
- **A scheduled time passes while the engine is stopped**: on restart it fires once, late,
  rather than either skipping silently or firing once per missed tick.
- **The clock jumps** (sleep/wake, NTP correction, DST transition): each scheduled time yields
  at most one fire.
- **A trigger fires for a thread that is mid-exchange, and the exchange never ends**: the bound
  releases it. This is the ordinary path for a hung run, not an exceptional one.
- **The user resumes the exchange just after the bound expires**: the item has already been
  released; it is not delivered twice.
- **An item's condition goes stale while queued**: re-check drops it at release, the same as for
  a quiet-hours deferral.
- **Quiet hours span midnight**: a window from evening to morning is honoured as one window.
- **Quiet hours end while the user is still asleep**: release proceeds; the window is the
  configured contract, not an inference about wakefulness.
- **A deferred item's rule is deleted before release**: the item expires rather than delivering
  for a rule that no longer exists.
- **Everything in the backlog fails re-check**: nothing is delivered and no empty message is
  sent — silence is the correct output when nothing survived.
- **Two rules match the same event**: both fire, and their results coalesce per Story 3.
- **A reply contains a credential in a shape the pattern set does not recognize**: it passes
  through. This is the stated limit of pattern matching, and the documentation says so rather
  than implying completeness.
- **Redaction errors while preparing a coalesced message**: the whole delivery is suppressed
  rather than partially delivered, since a partially-redacted message is worse than none.
- **The output destination is unavailable** (remote channel down): the failure is recorded
  against the delivery, not silently dropped, and does not mark the rule as having succeeded.
- **A rule's prompt template references an event field that is absent**: the rule does not fire
  with a half-rendered prompt; the mismatch is reported.
- **The engine and the event source are on different hosts with clocks that disagree**:
  de-duplication does not rely on the two clocks agreeing.
- **A trigger-injected turn attempts to satisfy a confirmation**: it cannot, regardless of the
  text it contains.

## Requirements *(mandatory)*

### Functional Requirements

**Rules and evaluation**

- **FR-001**: The system MUST evaluate rules declared in a configuration source, each carrying at
  minimum: a unique id, a trigger type, match criteria, a target thread, a prompt template, and
  an output destination.
- **FR-002**: The system MUST support three trigger types in this feature: **cron** (fires at
  scheduled times), **watcher** (fires on events emitted by the session watcher), and
  **completion** (fires when a long-running agent task finishes).
- **FR-003**: The rule schema MUST accommodate a future calendar trigger type without redesign.
  No calendar-sourced evaluation is implemented in this feature.
- **FR-004**: A rule's prompt template MUST be able to interpolate fields from the triggering
  event.
- **FR-005**: The system MUST reload rule changes — additions, edits, removals — without
  requiring a restart.
- **FR-006**: An invalid configuration MUST leave the previously valid configuration in effect
  and MUST report the error. A malformed edit must not disarm the engine.

**Firing and injection**

- **FR-007**: When a rule fires, the system MUST compose its prompt and inject it as a user turn
  on the rule's target thread, and MUST NOT introduce any execution path other than an ordinary
  turn. Rationale: reusing the turn contract is what gives a fired trigger the agent's existing
  skills, tools, and memory for free.
- **FR-008**: The assistant's reply to an injected turn MUST be delivered to the rule's output
  destination.
- **FR-009**: A synthetic turn MUST carry provenance distinguishing it from a turn sent by the
  user, and that distinction MUST be structural rather than a matter of content or convention.
- **FR-010**: Content injected by a trigger MUST NOT be capable of satisfying a confirmation
  that requires a trusted channel, regardless of what the content says (Article III).
- **FR-011**: A trigger-targeted thread MUST have available the tools its prompt requires. The
  mechanism by which a system-initiated turn acquires tools — which a human would otherwise
  attach by hand — MUST be determined against the real gateway surface and made to work.
- **FR-011a**: Each rule MUST target one stable thread of its own, created on first firing and
  reused for every subsequent firing of that rule. Rules MUST NOT share a thread, and a firing
  MUST NOT create a new thread when its rule already has one.
- **FR-011b**: The rule-id → thread-id mapping MUST persist across engine and gateway restarts.
  Rationale: a mapping held only in memory orphans the thread on every restart, which presents
  as a stable thread in the specification and behaves as a fresh one in practice — the failure
  is invisible until someone reads the conversation and finds it has no past.
- **FR-011c**: A rule thread MUST retain only a rolling window of its most recent firings, with
  a stated, configurable default. Beyond that window, history is context ballast that degrades
  the continuity the thread exists to provide.
- **FR-012**: Each fired rule MUST record an outcome — delivered, suppressed, queued, or failed
  — with the reason.

**Politeness (Article VII)**

- **FR-013**: The system MUST suppress delivery during a globally configured quiet-hours window,
  and MUST record that the suppression happened and why.
- **FR-013a**: A firing suppressed by quiet hours MUST be deferred rather than discarded, and
  released when the window ends.
- **FR-013b**: At release, each deferred item's condition MUST be re-evaluated. Only items whose
  condition still holds MUST be delivered; the rest MUST expire with the reason recorded.
- **FR-013c**: For trigger types carrying no re-checkable condition — cron and completion, which
  describe something that already happened — deferred items MUST **expire** rather than be
  delivered unverified. Rationale: without this, "re-check" degrades into "deliver anything we
  cannot disprove", and the asymmetry is real — a missed briefing is worthless by morning while
  a blocked session is still blocked and still worth knowing about.
- **FR-013d**: The quiet-hours release MUST pass through the same coalescing path as ordinary
  firings, so that a backlog is delivered as one message rather than several. A release that
  bypasses coalescing produces a notification storm at the moment the user wakes up, which is
  the single behaviour most likely to get the feature muted.
- **FR-014**: A rule MAY be marked urgent to override quiet hours. The override MUST be explicit
  per rule; there MUST be no implicit escalation.
- **FR-015**: Results from rules firing within a coalescing window MUST be delivered as a single
  message rather than several.
- **FR-016**: The system MUST NOT interrupt an in-progress exchange between the user and the
  assistant on the target thread. A proactive turn arriving mid-exchange MUST wait and proceed
  after the exchange completes.
- **FR-016a**: A queued proactive turn MUST be bounded by a maximum wait, with a stated,
  configurable default. The default MUST be documented as a **heuristic**, not as a derived or
  measured value: a user who has closed their browser mid-run and one who is reading a reply and
  about to type are indistinguishable to this system, so any bound is an assumption about human
  behaviour and Article X requires saying so.
- **FR-016b**: The system MUST NOT depend on an exchange-complete signal always arriving. A hung
  or abandoned run may emit nothing at all, in which case the FR-016a bound is the **only**
  mechanism that will ever release the queued item. It MUST therefore be implemented as the
  primary release path and not as a rarely-exercised fallback.
- **FR-016c**: On expiry, a queued item MUST be re-checked and released through the **same**
  re-check-then-coalesce mechanism used for quiet-hours release (FR-013b, FR-013d). Quiet hours
  and queue expiry are two entry conditions into one mechanism, not two implementations of the
  same idea. Rationale: a second implementation acquires its own defects in the path that runs
  least often and is observed least.
- **FR-017**: A rule that has fired for a given event MUST NOT fire again for that same event.
  Re-firing on an unchanged condition is a defect, not a tuning matter.
- **FR-017a**: Event sameness MUST be determined by the triple of rule id, event identifier, and
  a **state fingerprint** of the condition that caused the firing. A change in the underlying
  condition MUST therefore count as a new event and MUST fire.
- **FR-017b**: The fields contributing to a state fingerprint MUST be enumerated explicitly per
  trigger type, and MUST contain only values that change when the event genuinely changes. For a
  blocked session that is the pending question's text or a hash of it; elapsed time,
  last-activity timestamps, and any other continuously-drifting value MUST NOT contribute.
  Rationale: a drifting input makes every evaluation yield a "new" event, producing an alert per
  cycle. That is the inverse of the failure FR-017 guards against and is the worse of the two,
  because it is the version that gets the feature muted.
- **FR-017c**: Stored fingerprints MUST be discarded on a daily reset. A fingerprint older than
  a day has no live event left to suppress, and unbounded growth is unacceptable in a process
  shared with the gateway.
- **FR-018**: Each scheduled time MUST yield at most one fire, including across restarts, sleep
  and wake, and clock adjustments.

**Routing and presence**

- **FR-008a**: Session-derived and agent-composed content MUST pass through redaction at the
  delivery boundary before leaving the process, on **every** output destination including local
  and quiet ones. Rationale: a filter exercised only on the remote path is one whose failures
  first appear in front of the least recoverable audience.
- **FR-008b**: Redaction MUST fail closed. An error while redacting MUST suppress that delivery
  and say so explicitly, and MUST NOT fall back to delivering unredacted content. Rationale: no
  human is waiting on a proactive reply, so a silent pass-through on error would go unnoticed
  indefinitely — a stronger argument for failing closed than the one in Feature 001, not a
  weaker one.
- **FR-008c**: The recognized-pattern set MUST be widened in this feature beyond the shapes
  found in session records, to cover at minimum cloud credentials, bearer tokens, private-key
  headers, and environment-style assignments. Agent-composed output can contain anything the
  agent can reach.
- **FR-008d**: No user-facing surface, documentation, or message may describe redaction as
  removing *secrets*. It removes **recognized patterns**, and unrecognized shapes pass through.
  This limit is stated, not implied, and widening the pattern set (FR-008c) does not license
  strengthening the claim.
- **FR-019**: Output destinations MUST be an abstraction with at least two implementations in
  this feature: a remote channel and a quiet destination that records without delivering.
- **FR-020**: A local spoken destination MUST be addable later by registering against the same
  abstraction, with no change to rule evaluation, coalescing, or delivery.
- **FR-021**: A rule MAY specify automatic routing, which resolves to a local destination when
  the user is present and a remote destination otherwise. With no local destination registered,
  automatic MUST resolve to remote.
- **FR-022**: Presence MUST be derived from the time of the user's last inbound turn on any
  channel. It MUST NOT be derived from operating-system idle time, input-device activity, or any
  other signal local to the machine running the engine. Rationale: the engine is expected to run
  on a dedicated always-on host, where that machine's idleness says nothing about the user.
- **FR-023**: The presence signal MUST be observable — inspectable at runtime — even while only
  one destination type is registered, so that adding the local destination later requires no
  rework of presence itself.

**Boundaries and resilience**

- **FR-024**: The system MUST interact with the agent core exclusively through its public
  gateway surface and MUST NOT import from core packages. This MUST be verifiable automatically.
- **FR-025**: The failure of one rule MUST NOT stop the engine or affect the evaluation of any
  other rule.
- **FR-026**: A rule that fails repeatedly MUST be reported and its retry rate reduced. Silent
  indefinite retry at full rate is prohibited.
- **FR-027**: Scheduling MUST NOT busy-poll. Idle cost MUST remain negligible when no rule is
  due.
- **FR-028**: The system MUST NOT assume co-location with the user, with the user's machine, or
  with the event source. Rule evaluation, presence, and routing MUST all function with the event
  source on a separate host reachable over a network.
- **FR-029**: When the event source is unreachable, the system MUST treat that as an
  unobservable condition rather than as an absence of events, and MUST NOT report or act as
  though it had successfully observed nothing (Article X).

**Blast radius (the engine shares a process with the gateway)**

*Feature 001 got a crash boundary for free: the watcher is a separate process, so its failure
could not reach the assistant. This engine runs in-process with the gateway, which removes that
boundary. A rule that raises or blocks now takes down the whole assistant unless the isolation
is built deliberately. These requirements replace the boundary that process separation used to
provide.*

- **FR-030**: A failing rule MUST NOT be able to terminate, crash, or leave the gateway in an
  unusable state. Every rule evaluation MUST be isolated such that any exception it raises is
  contained and attributed to that rule.
- **FR-031**: Rule evaluation and delivery MUST NOT perform blocking work on the shared request
  path. A slow or hung rule MUST NOT delay, stall, or degrade the assistant's handling of
  ordinary user requests.
- **FR-032**: A rule that hangs indefinitely MUST be bounded, abandoned, and reported, rather
  than holding a shared resource until the process is restarted.
- **FR-033**: The isolation in FR-030 through FR-032 MUST be demonstrated by a deliberately
  crashing rule and a deliberately hanging rule, each proven not to affect the gateway or any
  other rule. An isolation claim that has never been tested against a real failure is not
  evidence.

### Key Entities

- **Rule**: A declared intent to speak first. Attributes: id, trigger type, match criteria,
  target thread, prompt template, output destination, urgency, enabled state.
- **Trigger Event**: The occurrence that causes evaluation — a scheduled time reached, a watcher
  event received, a task completion. Carries a stable identity used to guarantee at-most-once
  firing per event.
- **Firing**: One rule's response to one event. Carries the composed prompt, the target thread,
  the resulting reply, an outcome (delivered / suppressed / queued / failed), and a reason.
- **Output Destination**: Where a reply is delivered. An abstraction; a remote channel and a
  quiet destination exist in this feature, a local spoken destination arrives later.
- **Presence Signal**: The time of the user's last inbound turn on any channel, and the derived
  present/away state used by automatic routing.
- **Coalescing Window**: A span during which multiple firings accumulate into one delivery.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A watched session becoming blocked produces exactly one delivered message on the
  remote channel within 60 seconds of the event being emitted, in 100% of trials.
- **SC-002**: While a session remains blocked after its first message, no further message is
  delivered for that block, in 100% of trials.
- **SC-002a**: A session that blocks, is answered, then blocks again on a different question
  produces a second delivered message, in 100% of trials — a changed condition is a new event.
- **SC-002b**: Across 100 consecutive evaluation cycles against an unchanged blocked session,
  exactly one message is delivered — verifying that no continuously-drifting value contributes
  to the fingerprint.
- **SC-002c**: Stored fingerprints do not grow across a multi-day run; the count after the daily
  reset reflects only live events.
- **SC-003**: A scheduled rule delivers exactly once per scheduled time across a seven-day run,
  with zero missed and zero duplicated deliveries.
- **SC-004**: A scheduled time that passes while the engine is stopped or the machine is asleep
  produces exactly one delivery after resumption, in 100% of trials.
- **SC-005**: Three rules firing within the coalescing window produce exactly one delivered
  message containing all three results, in 100% of trials.
- **SC-006**: A non-urgent rule firing inside quiet hours delivers nothing and records the
  suppression with its reason, in 100% of trials; the same rule marked urgent delivers.
- **SC-006a**: A session that blocks during quiet hours and is still blocked when the window
  ends produces exactly one delivered message at release, in 100% of trials.
- **SC-006b**: A session that blocks during quiet hours and is resolved before the window ends
  produces no message at release, in 100% of trials.
- **SC-006c**: A cron firing suppressed by quiet hours expires and is not delivered at release,
  in 100% of trials.
- **SC-006d**: Six deferred items surviving re-check are delivered as exactly one message at
  release, not six, in 100% of trials.
- **SC-007**: A rule firing while the user is mid-exchange is delivered only after that exchange
  completes, and never during it, in 100% of trials.
- **SC-007a**: With an exchange that never completes and emits no completion signal, the queued
  item is released within the configured bound rather than waiting indefinitely, in 100% of
  trials.
- **SC-007b**: An item released by queue expiry passes through the same re-check and coalescing
  as one released by quiet hours, verified by asserting both paths reach the same mechanism.
- **SC-007c**: Multiple items queued behind one stalled exchange are delivered as a single
  coalesced message on release, not as one message each.
- **SC-008**: Rules can be added, edited, and removed with the change taking effect on the next
  evaluation and no restart, in 100% of trials.
- **SC-009**: An invalid configuration leaves the prior configuration active and reports the
  error, in 100% of trials.
- **SC-010**: A rule that raises an error does not prevent any other rule from being evaluated in
  the same cycle, in 100% of trials.
- **SC-011**: The engine introduces no dependency on agent-core internals, verified automatically
  on every change to the codebase.
- **SC-012**: With no rule due, the engine's ongoing resource consumption is indistinguishable
  from idle over a one-hour observation window.
- **SC-013**: With the event source made unreachable, watcher-type rules do not fire and the
  unreachable condition is observable; no reply states or implies that no events occurred.
- **SC-014**: A trigger-injected turn cannot satisfy a confirmation requiring a trusted channel,
  in 100% of trials, including when its content is crafted to resemble one.
- **SC-014a**: With recognized credential patterns seeded into the content a rule would deliver,
  no such pattern appears in any delivered message on any destination, in 100% of trials.
- **SC-014b**: With redaction forced to error, the delivery is suppressed with an explicit
  can't-relay message and no content is delivered, in 100% of trials.
- **SC-014c**: The widened pattern set catches at least cloud credentials, bearer tokens,
  private-key headers, and env-style assignments, each verified by a seeded case.
- **SC-015**: A trigger-targeted thread has the tools its prompt requires available at the moment
  the injected turn is processed, in 100% of trials.
- **SC-015a**: A rule fired on two consecutive days targets the same thread, and the second
  firing can reference the first, in 100% of trials.
- **SC-015b**: A rule's thread survives an engine restart: the firing after the restart targets
  the same thread as the firing before it, in 100% of trials.
- **SC-015c**: After more firings than the retention window allows, the thread holds only the
  configured number of recent firings.
- **SC-016**: Presence resolves from the last inbound user turn and is unaffected by the engine
  host's own idle state, verified by leaving that host idle while the user remains active.
- **SC-017**: With a rule that raises on every evaluation, the assistant continues to answer
  ordinary user requests normally and every other rule continues to be evaluated, in 100% of
  trials.
- **SC-018**: With a rule that hangs indefinitely, ordinary user requests are served with no
  measurable added latency, and the hung rule is abandoned and reported within a stated bound,
  in 100% of trials.

## Assumptions

- Feature 001 is complete and its waiting-on-user event is available to consume. This feature
  is the consumer that FR-010 and FR-025 of that feature anticipated.
- The agent core exposes a way to inject a turn and observe the resulting reply through its
  public gateway surface. The exact mechanism is a planning question; that one exists is assumed
  because the whole design rests on it. If it does not, the design changes rather than the
  requirement being softened.
- The remote channel is the existing Telegram integration; this feature adds no new channel.
- Several thresholds in this feature are **heuristics with stated defaults, not derived values**:
  the presence "recently active" window, the coalescing window, the queued-turn bound, and the
  fingerprint retention period. Each is configurable, each default is a starting point, and none
  should be presented to the user as though it were measured.
- The coalescing window and quiet-hours window are configurable with stated defaults.
- A single user is assumed. Multi-user rule scoping, per-user quiet hours, and per-user presence
  are out of scope.
- Rules are authored by the user by hand. No rule-authoring UI is in scope.
- The rule-id → thread-id mapping follows the pattern the channel manager already uses for IM
  conversations — a durable key-to-thread store, atomically written (`ChannelStore`, a
  JSON-backed map of channel/chat/topic to thread id). This feature needs the same shape with a
  different key, not a new mechanism.
- Delivery is best-effort with recorded outcome: this feature does not implement guaranteed
  delivery, acknowledgement, or retry-until-received.
- The engine runs alongside the gateway process where practical, but the design must not assume
  it — FR-028 governs. Verified 2026-08-21: in-process is currently the **only** working
  arrangement, because the gateway's internal-auth token is generated per process
  (`secrets.token_urlsafe(32)` at import) and is explicitly same-process. Running the engine
  separately would require a service-account credential concept that does not exist today; a
  7-day-expiry user JWT is not one. Recorded as future work, not as a task for this feature.
- Turn injection is verified to exist rather than assumed: the Telegram channel already drives
  runs server-side through the public SDK client, and the mechanism places no constraint on
  which thread may be targeted.
