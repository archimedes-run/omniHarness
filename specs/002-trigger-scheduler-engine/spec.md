# Feature Specification: Trigger & Scheduler Engine

**Feature Branch**: `002-trigger-scheduler-engine`

**Created**: 2026-08-21

**Status**: Draft

**Input**: User description: "A rule engine that lets the assistant speak first. Rules evaluate on a clock tick or on an inbound event; when a rule fires, it injects a synthetic user turn into a target thread. Because a fired trigger is just a turn, the existing agent core handles it with all its current machinery — skills, tools, memory — and no new execution path is introduced."

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

- **A rule's target thread does not exist**: the failure is reported against that rule; other
  rules are unaffected.
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
- **A trigger fires for a thread that is mid-exchange, and the exchange never ends**: the queued
  turn does not accumulate unbounded; a stated limit applies and its expiry is recorded.
- **Quiet hours span midnight**: a window from evening to morning is honoured as one window.
- **Two rules match the same event**: both fire, and their results coalesce per Story 3.
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
- **FR-012**: Each fired rule MUST record an outcome — delivered, suppressed, queued, or failed
  — with the reason.

**Politeness (Article VII)**

- **FR-013**: The system MUST suppress delivery during a globally configured quiet-hours window,
  and MUST record that the suppression happened and why.
- **FR-014**: A rule MAY be marked urgent to override quiet hours. The override MUST be explicit
  per rule; there MUST be no implicit escalation.
- **FR-015**: Results from rules firing within a coalescing window MUST be delivered as a single
  message rather than several.
- **FR-016**: The system MUST NOT interrupt an in-progress exchange between the user and the
  assistant on the target thread. A proactive turn arriving mid-exchange MUST wait and proceed
  after the exchange completes.
- **FR-017**: A rule that has fired for a given event MUST NOT fire again for that same event.
  Re-firing on an unchanged condition is a defect, not a tuning matter.
- **FR-018**: Each scheduled time MUST yield at most one fire, including across restarts, sleep
  and wake, and clock adjustments.

**Routing and presence**

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
- **SC-003**: A scheduled rule delivers exactly once per scheduled time across a seven-day run,
  with zero missed and zero duplicated deliveries.
- **SC-004**: A scheduled time that passes while the engine is stopped or the machine is asleep
  produces exactly one delivery after resumption, in 100% of trials.
- **SC-005**: Three rules firing within the coalescing window produce exactly one delivered
  message containing all three results, in 100% of trials.
- **SC-006**: A non-urgent rule firing inside quiet hours delivers nothing and records the
  suppression with its reason, in 100% of trials; the same rule marked urgent delivers.
- **SC-007**: A rule firing while the user is mid-exchange is delivered only after that exchange
  completes, and never during it, in 100% of trials.
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
- **SC-015**: A trigger-targeted thread has the tools its prompt requires available at the moment
  the injected turn is processed, in 100% of trials.
- **SC-016**: Presence resolves from the last inbound user turn and is unaffected by the engine
  host's own idle state, verified by leaving that host idle while the user remains active.

## Assumptions

- Feature 001 is complete and its waiting-on-user event is available to consume. This feature
  is the consumer that FR-010 and FR-025 of that feature anticipated.
- The agent core exposes a way to inject a turn and observe the resulting reply through its
  public gateway surface. The exact mechanism is a planning question; that one exists is assumed
  because the whole design rests on it. If it does not, the design changes rather than the
  requirement being softened.
- The remote channel is the existing Telegram integration; this feature adds no new channel.
- "Recently active" for presence uses a configurable threshold with a stated default; the value
  is a starting point rather than a researched figure.
- The coalescing window and quiet-hours window are configurable with stated defaults.
- A single user is assumed. Multi-user rule scoping, per-user quiet hours, and per-user presence
  are out of scope.
- Rules are authored by the user by hand. No rule-authoring UI is in scope.
- The target thread for a rule is expected to exist; thread creation semantics for triggers are
  a planning question flagged for clarification rather than assumed here.
- Delivery is best-effort with recorded outcome: this feature does not implement guaranteed
  delivery, acknowledgement, or retry-until-received.
- The engine runs alongside the gateway process where practical, but the design must not assume
  it — FR-028 governs.
