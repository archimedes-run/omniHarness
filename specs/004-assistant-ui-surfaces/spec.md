# Feature Specification: Assistant UI Surfaces

**Feature Branch**: `004-assistant-ui-surfaces`

**Created**: 2026-08-25

**Status**: Draft

**Input**: User description: Four browser surfaces that make Features 001, 002 and 003 visible and operable — pending confirmations (interactive), coding sessions, trigger activity, and a policy inspector. Desktop browser only.

## Preconditions Discovered During Specification

The input states that three of the four surfaces are "read-only views over data that
already exists". Checking each against the running code found that **two of the three
claims hold and one does not**. This section records what was verified, because a
requirement written against data that is not recorded produces a surface that renders
a blank column and a test that asserts the blank is correct.

| Claim in the input | Verified | Evidence |
|---|---|---|
| Session states distinguish observed from inferred | **Holds** | `SessionState`/`IdleReason` model COMPLETED as an observed fact and STALLED as an inference, and say so in the source |
| Watcher health is representable | **Holds** | The registry defines LIVE / STALE / never-observed, with a staleness age |
| Firings record suppression and queueing with reasons | **Holds** | `Outcome.SUPPRESSED` and `Outcome.QUEUED` are both resolved with a mandatory reason |
| Policy can answer "what tier, and which rule" without executing | **Holds** | `explain()` calls the same `classify()` used at dispatch |
| Pending actions are listable and atomically claimable | **Holds** | `open_actions()`, `claim()` returning the claimed action |
| Firings record **when a rule was last evaluated** | **DOES NOT HOLD** | Nothing anywhere records an evaluation. The audit log records firings only |
| Coalesced firings record **what they were merged with** | **DOES NOT HOLD** | Every survivor of a merge is audited individually as DELIVERED; nothing links them |
| An HTTP path exists for confirming outside chat | **DOES NOT HOLD** | The gateway registers no confirmation route; the `/confirm` endpoint used by the cross-worker test belongs to a purpose-built test app |

Three consequences, carried into the requirements rather than worked around:

1. **The trigger surface requires a backend addition before it can be built.** A rule
   that has evaluated five hundred times without firing is, in the current record,
   indistinguishable from one that has never been evaluated. That is precisely the
   distinction the input says "makes a silently-broken rule findable", and it is the
   distinction the calendar lead-time bug fell into. Recording evaluations is
   therefore in scope (FR-020), not a follow-up.

2. **Coalescing is not a sixth outcome.** A coalesced firing *is* delivered; the merge
   affects how many messages the user received, not whether the firing succeeded.
   Modelling it as an outcome alongside DELIVERED would misrepresent it and would put
   a lie in the audit log. It is represented instead as shared batch identity across
   delivered firings (FR-021), which is both truthful and sufficient to show what a
   firing was merged with.

3. **"The existing confirmation path" means the existing recognition, claim and
   resolution logic — not an existing route.** Confirming in chat happens inside the
   middleware. This feature adds the first HTTP confirmation entry point, and its
   correctness requirement is that it calls the same `recognise` / `claim` / `resolve`
   functions rather than reimplementing them (FR-004).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Confirm or decline a Tier 3 action from a control (Priority: P1)

A Tier 3 action is awaiting confirmation. Rather than typing an exact phrase from a
closed set into chat, the user opens the pending list, reads the plan as it was
stated and the specific targets that confirming would authorise, and presses Confirm
or Decline.

**Why this priority**: This is the only interactive surface and the reason the feature
exists rather than being deferred again. Exact string matching was chosen deliberately
because interpretation was rejected as a security property; the same decision named an
explicit affordance as the alternative. This is that affordance, and it is the control
the user touches several times a day.

**Independent Test**: Create a Tier 3 pending action, open the surface, press Confirm,
and observe the action execute exactly once with an audit entry naming the worker that
claimed it. Delivers the whole value of the feature on its own.

**Acceptance Scenarios**:

1. **Given** a pending Tier 3 action created by one gateway worker, **When** the user
   presses Confirm on a page served by a different worker, **Then** the action executes
   exactly once and the audit entry records which worker claimed it.
2. **Given** a pending action, **When** the user presses Decline, **Then** the action is
   resolved as declined, is not executed, and the outcome is as deterministic as a
   confirmation — no path leaves it pending.
3. **Given** a pending action displayed with time remaining, **When** its expiry passes
   while the page is open, **Then** it becomes visibly expired without a reload and its
   controls stop being operable rather than appearing to work.
4. **Given** a pending action whose resolved targets have drifted since the plan was
   stated, **When** the user presses Confirm, **Then** the same decline-and-restate
   behaviour as chat occurs, and the surface states that the targets changed.
5. **Given** the same pending action open in the UI and referenced in chat, **When**
   both confirmations arrive at once, **Then** the action executes once, not twice.
6. **Given** a pending action requested by a subagent, **When** it is displayed, **Then**
   the delegation chain is shown, not merely the immediate requester.

---

### User Story 2 - Find out why a trigger produced nothing (Priority: P2)

A user expected a proactive message and did not receive one. They open trigger activity
and see which rules are loaded, when each was last evaluated and last fired, and a
chronological log of firings with what happened to each.

**Why this priority**: This is the scenario named in the feature's motivation. When a
lead-time bug meant calendar alerts fired approximately never, there was nothing to
look at. A rule that silently does not fire is indistinguishable from one with nothing
to fire on, and only this surface separates them.

**Independent Test**: Load a rule that cannot fire, let the engine run, and confirm the
surface shows it evaluating and never firing — visibly different from a rule that has
never been evaluated at all.

**Acceptance Scenarios**:

1. **Given** a rule that has been evaluated repeatedly and never fired, **When** the
   rules panel is viewed, **Then** it is visibly distinguishable from a rule that has
   never been evaluated and from one that fired recently.
2. **Given** a firing suppressed by quiet hours, **When** the log is viewed, **Then** it
   is distinguishable from a delivered firing and from a rule that never evaluated, and
   the recorded reason is shown rather than replaced by a status word.
3. **Given** several firings merged into one delivered message, **When** the log is
   viewed, **Then** each shows that it was delivered as part of a batch and which other
   firings shared it.
4. **Given** a firing that expired at release because its condition no longer held,
   **When** the log is viewed, **Then** the outcome and its reason are shown distinctly
   from a failure.

---

### User Story 3 - See what the coding sessions are doing (Priority: P3)

The session watcher's registry is rendered: each session's project, state, last
activity, and most recent summary line, with the watcher's own health shown first.

**Why this priority**: Read-only over data that exists and is already correctly
modelled. Valuable but not blocking; the watcher already answers when asked in chat.

**Independent Test**: Start sessions in two projects, open the surface, and confirm each
appears with the right state; stop the watcher and confirm the surface says sessions
cannot be seen.

**Acceptance Scenarios**:

1. **Given** a session inferred to be waiting on the user, **When** the list is viewed,
   **Then** it is visually distinguishable from one observed to have finished, without
   reading the text.
2. **Given** a session that stalled and one that completed, **When** the list is viewed,
   **Then** the two remain distinct, as they are in the underlying data.
3. **Given** the watcher stopped, **When** the surface is opened, **Then** it states that
   sessions cannot be seen and does not render an empty list that reads as "nothing is
   running".
4. **Given** a stale watcher, **When** the surface is opened, **Then** the staleness and
   its age are shown alongside the last-known contents.
5. **Given** an observe-only session, **When** it is displayed, **Then** it is labelled
   as observe-only, so the absence of controls is legible as a property rather than a
   missing feature.

---

### User Story 4 - Learn a tool's tier without triggering it (Priority: P4)

The loaded classification rules are listed, and the user can ask what tier a named tool
call would receive and which rule decided it.

**Why this priority**: The smallest surface and the least frequently used, but it
removes the current situation where the only way to learn a tier is to trigger it.

**Independent Test**: Enter a tool name, receive a tier and the deciding rule, and
confirm by inspection that the tool was not executed.

**Acceptance Scenarios**:

1. **Given** a tool name matching an explicit rule, **When** the tier is checked,
   **Then** the tier and the name of the deciding rule are both returned, and the tool
   is not executed.
2. **Given** a tool with no matching rule, **When** the tier is checked, **Then** the
   result is Tier 3 and is marked as coming from the default rather than from an
   explicit rule.
3. **Given** a tool matched by more than one rule, **When** the tier is checked, **Then**
   the rule that determined the outcome is named, not merely the set that matched.
4. **Given** recent Tier 3 executions in the audit log, **When** they are viewed,
   **Then** each shows the actor, the plan as stated, and the confirmation that
   authorised it.

---

### Edge Cases

- An action expires between the page rendering it and the user pressing Confirm.
- An action is claimed by another route in the instant between render and press: the
  surface must report that it was already resolved, not that the press failed.
- Two browser tabs display the same pending action and both press Confirm.
- The pending store cannot be read at all: the surface must distinguish "no actions
  are pending" from "we cannot tell what is pending".
- A pending action's plan or targets contain content that fails redaction.
- A rule's audit entries exist but the rule has since been removed from the loaded set.
- The trigger audit log contains entries written before evaluation recording and batch
  identity existed, so both fields are absent for historical rows.
- The audit log is large enough that rendering all of it is not sensible.
- A session's most recent summary line fails redaction.
- The policy rule set fails to reload, leaving the previous rules in force: the
  inspector must describe the rules actually deciding, not the file on disk.

## Requirements *(mandatory)*

### Functional Requirements — Pending confirmations (Surface 1)

- **FR-001**: The system MUST list Tier 3 actions awaiting confirmation, across all
  gateway workers, not only actions created by the worker serving the page.
- **FR-002**: Each pending action MUST show what was requested, the plan exactly as it
  was stated to the user, the resolved specific targets the confirmation authorises,
  the requesting agent including the delegation chain when a subagent asked, and the
  time remaining before expiry.
- **FR-003**: Users MUST be able to confirm and to decline each pending action, with
  declining as available and as deterministic as confirming.
- **FR-004**: Confirmation and decline through this surface MUST go through the same
  recognition, atomic claim and resolution logic used when confirming in chat. A second
  confirmation route that reimplements the claim would allow one confirmation to
  execute twice, and this is the requirement that forbids it.
- **FR-005**: An action that expires while displayed MUST become visibly expired without
  a page reload, and its controls MUST become inoperable rather than remaining pressable.
- **FR-006**: Confirming an action whose resolved targets have drifted MUST produce the
  same decline-and-restate behaviour as chat, and the surface MUST state that the
  targets changed rather than reporting a generic failure.
- **FR-007**: A confirmation for an action already resolved by any route MUST be
  reported as already resolved, naming the outcome, distinctly from a failure to submit.
- **FR-008**: The surface MUST distinguish "no actions are pending" from "the pending
  set could not be read".

### Functional Requirements — Coding sessions (Surface 2)

- **FR-010**: The system MUST display each known session's project, state, last activity
  time, and most recent summary line.
- **FR-011**: Inferred states MUST be visually distinguishable from observed ones,
  without relying on the reader parsing the wording.
- **FR-012**: Completed and stalled MUST remain distinct in the display, as they are in
  the underlying data.
- **FR-013**: Watcher health MUST be displayed first-class as live, stale with its age,
  or unavailable, and MUST NOT be inferable only from an empty list.
- **FR-014**: When the watcher is unavailable, the surface MUST state that sessions
  cannot be seen, and MUST NOT render an empty list that reads as "no sessions running".
- **FR-015**: Observe-only sessions MUST be labelled as such.

### Functional Requirements — Trigger activity (Surface 3)

- **FR-016**: The system MUST display the currently loaded rules with, for each, its id,
  type, enabled state, when it was last evaluated, and when it last fired.
- **FR-017**: A rule that has never fired MUST be visibly different from one that fired
  recently, and a rule that has never been evaluated MUST be visibly different from one
  evaluated repeatedly without firing.
- **FR-018**: The system MUST display a chronological log of firings showing which rule,
  what triggered it, and the outcome, with delivered, suppressed, queued, expired and
  failed each distinguishable.
- **FR-019**: Where a record carries a reason, that reason MUST be shown rather than
  summarised into a status word.
- **FR-020**: The trigger engine MUST record when each rule was last evaluated.
  *This is a new backend capability, not a read over existing data.* Without it FR-017
  cannot be satisfied, and the distinction it provides is the one the calendar lead-time
  bug fell into.
- **FR-021**: Firings delivered together after coalescing MUST carry a shared batch
  identity, and the surface MUST show each coalesced firing alongside the others in its
  batch. *This is a new backend capability.* Coalescing MUST NOT be represented as an
  outcome: a coalesced firing was delivered, and recording otherwise would put a false
  statement in the audit log.
- **FR-022**: Records written before FR-020 and FR-021 existed MUST render as "not
  recorded" for those fields, distinctly from a recorded absence such as "never fired".

### Functional Requirements — Policy inspector (Surface 4)

- **FR-023**: The system MUST display the loaded classification rules.
- **FR-024**: Users MUST be able to ask what tier a named tool call would receive.
- **FR-025**: The tier check MUST NOT execute the call it is asked about, and MUST use
  the same classification path used at live dispatch.
- **FR-026**: The result MUST name the rule that decided the tier, not only the tier.
- **FR-027**: A tier arising from the default rather than an explicit rule MUST be marked
  as such, since unclassified-defaults-to-Tier-3 and explicitly-classified-as-Tier-3
  are identical in the result and different in meaning.
- **FR-028**: The system MUST display recent Tier 3 executions from the audit log
  showing the actor, the plan as stated, and the confirmation that authorised each.
- **FR-029**: The inspector MUST describe the rules actually in force, including after a
  failed reload has left previous rules active.

### Functional Requirements — Cross-cutting

- **FR-030**: The three read surfaces MUST perform no writes, provable by test.
- **FR-031**: Content rendered from session records, page content or email bodies MUST
  pass the existing redactor, and a redaction failure MUST suppress display rather than
  falling through to unredacted content.
- **FR-032**: No surface or its tests may read from a gitignored file (Article XIV).
- **FR-033**: Every surface MUST take its colours from the existing theme tokens and
  MUST NOT hardcode a colour value or literal colour utility.
- **FR-034**: The six accessibility lint rules currently set to warn MUST be promoted to
  error, so new UI is held to them from the start rather than retrofitted.
- **FR-035**: Acceptance criteria for this feature MUST assert rendered output — what
  the user sees — and not component props alone.
- **FR-036**: This feature MUST NOT include a rule editor for triggers or for policy.
  Writes remain conversational, proposed by the assistant and written after approval
  through the existing Tier 3 gate.

### Key Entities

- **Pending action**: A Tier 3 action awaiting confirmation. Carries the plan as stated,
  resolved targets, requesting agent and delegation chain, expiry, and — once claimed —
  the claimant. Resolvable exactly once.
- **Session record**: A watched coding session. Carries project, state, whether that
  state was observed or inferred, idle reason where idle, last activity, and latest
  summary.
- **Watcher health**: Live, stale with an age, or unavailable. A property of the
  observer, not of any session, and displayed separately for that reason.
- **Rule (trigger)**: Id, type, enabled state, last evaluated, last fired.
- **Firing**: A rule's response to an event. Carries the rule, the triggering event, the
  outcome, a reason where the outcome is not plain delivery, and batch identity where it
  was delivered with others.
- **Rule (policy)**: A pattern and the tier it assigns. Rules may overlap; the highest
  tier wins.
- **Tier decision**: A tier, the rule that decided it, and whether it came from an
  explicit rule or from the default.
- **Audit entry (Tier 3 execution)**: Actor, plan as stated, targets, outcome, and the
  confirmation that authorised it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A Tier 3 action confirmed through the UI executes exactly once, and the
  audit entry names the worker that claimed it.
- **SC-002**: The same action confirmed simultaneously through the UI and through chat
  executes once, not twice.
- **SC-003**: An action expiring while displayed becomes visibly expired without a
  reload, and cannot then be confirmed.
- **SC-004**: Confirming an action with drifted targets is declined and restated, and
  the user is told the targets changed.
- **SC-005**: A pending action created on one worker is confirmable from a page served
  by any other worker, at the worker count production runs.
- **SC-006**: With the watcher stopped, the sessions surface states that sessions cannot
  be seen; it does not render an empty list.
- **SC-007**: A session waiting on a question is distinguishable from one that finished
  without reading the text.
- **SC-008**: A rule suppressed by quiet hours is distinguishable in the firings log
  from one that fired and from one that never evaluated.
- **SC-009**: A rule evaluated repeatedly without firing is distinguishable from a rule
  never evaluated.
- **SC-010**: Firings coalesced into one message each show the others they were
  delivered with.
- **SC-011**: The policy inspector returns a tier and a deciding rule for a tool name,
  with no side effect on that tool.
- **SC-012**: A tier arising from the default is marked as such and is distinguishable
  from an explicit Tier 3 classification.
- **SC-013**: Toggling dark mode changes the computed background colour of every surface
  in this feature, asserted in CI against a rendered page.
- **SC-014**: No surface writes to any store, demonstrated by a test that fails if a
  read surface issues a write.
- **SC-015**: A record whose display fails redaction is suppressed, and the suppression
  is visible as such rather than as absent data.
- **SC-016**: No test in this feature reads a gitignored path.
- **SC-017**: The six accessibility rules are set to error and the build fails on a
  deliberate violation.

## Assumptions

- **Desktop browser only.** Mobile layouts are explicitly out of scope, as stated in
  the input. Surfaces are not required to be usable below desktop widths.
- **The surfaces live inside the existing authenticated workspace shell**, reusing its
  navigation, component library and theme tokens. No new authentication model is
  introduced; whoever can reach the workspace can reach these surfaces.
- **Pressing an explicit Confirm control is itself the deliberate act** that exact
  string matching was standing in for, and no additional typed phrase is required.
  Article XIII is satisfied because initiation and confirmation remain separate acts by
  separate parties — the assistant proposes, the user presses. Recorded as an assumption
  because it is a security-relevant judgement and the cheapest place to overrule it is
  here.
- **Liveness is achieved by client-side countdown plus periodic refresh**, not by a
  streaming connection. The expiry requirement in FR-005 concerns what the user sees, so
  a refresh interval short enough to satisfy it is sufficient; the streaming path that
  once existed was removed.
- **Read APIs for these four surfaces do not exist yet and are part of this feature.**
  The gateway currently registers no routes for sessions, triggers, policy or pending
  actions.
- **The audit logs are append-only files** and are read directly rather than through a
  query layer. Volume is assumed to be small enough that a bounded recent window is
  sufficient; no pagination beyond a recent-N window is required.
- **Historical audit rows will lack the fields added by FR-020 and FR-021**, and are
  rendered as "not recorded" rather than backfilled.
- **The existing redactor is reused unchanged.** This feature adds callers, not
  redaction rules.
- **Feature 003's browser worker remains out of scope**, as recorded in the roadmap. It
  is a follow-up feature and not part of these surfaces.
