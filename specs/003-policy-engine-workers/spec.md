# Feature Specification: Permission Policy Engine & Real-World Workers

**Feature Branch**: `003-policy-engine-workers`

**Created**: 2026-08-23

**Status**: Draft

**Input**: User description: Feature 003 — a policy layer that classifies every tool call before dispatch, plus the first tools that can affect the user's life outside their own machine (email drafting, calendar, browser), plus calendar-sourced triggers. Amended before drafting with four verified corrections (see Verified Preconditions).

## Overview

Until now every tool the assistant could reach was read-only and local. Feature 001 observed coding sessions; Feature 002 let the assistant speak first. Neither could change anything the user would miss.

This feature is the first where a mistake costs the user something real — a deleted meeting, a declined invitation, a submitted form. The guardrail therefore ships in the same slice as the capability, not after it. The policy engine is not a feature bolted beside the workers; it is the precondition for having them at all.

Constitution Article II defines three tiers of action. This feature makes them operational and applies them to every tool in the system, including those Features 001 and 002 already exposed.

## Verified Preconditions

*This section records mechanisms confirmed against the running code before this spec was written, following the project convention that a plan may not rest on an unverified assumption. Each was checked; two were found broken and one has been repaired.*

- **VP-001 — A single tool-dispatch chokepoint exists.** Four of five agent-construction sites converge on one shared middleware assembly, and the agent framework exposes a tool-call interception hook at which a call may be inspected, allowed, or refused without executing. Refusal is expressible: the interceptor may decline to run the tool and return a result in its place.
- **VP-002 — All tool sources normalise to one shape.** Built-in tools, MCP-server tools, third-party connector tools, and agent-to-agent tools are all assembled into a single list and executed through the same path. There is no tool category that reaches execution by another route.
- **VP-003 — The synthetic-turn marker is readable at dispatch (REPAIRED).** Feature 002 marks trigger-injected turns structurally, where message content cannot forge it. That marker was **not** readable at the dispatch chokepoint: the interception hook receives no run configuration, and the only container it can read had stopped being populated from the one the marker lives in. This broke silently on a dependency upgrade, with no test failing, because nothing was reading it yet. It has been repaired and is now guarded by a test that reads the marker from inside the interception hook. **FR-004 depends on this and must not re-verify it by assumption.**
- **VP-004 — Tool-surface filtering is server-granular, not per-tool (GAP).** Tools can be included or excluded a whole server at a time; there is no per-tool allow or deny capability in the server configuration. FR-012's requirement is therefore *written*, not *configured* — see FR-013.
- **VP-005 — Feature 002 is not currently running (BLOCKING for Part 3).** The trigger engine has no consumer outside itself and its own tests; nothing starts it, and its audit log is never constructed in production. A repo-level gate now guards this. Wiring it is a separate change that must land before this feature's Part 3 and FR-011 can be demonstrated. See Dependencies.
- **VP-006 — A fifth agent-construction path bypasses the chokepoint.** One agent factory assembles its own interception chain and does not pass through the shared one. It is public API with no production consumer. Anything built through it would escape classification entirely — see FR-003.
- **VP-007 — The redactor is consumed as an injected callable, not a static import.** Feature 002 receives redaction as a supplied function and fails closed when it errors. The owning package is a declared dependency of the consuming one, and the import ban runs the other direction. Reuse this shape rather than duplicating patterns — see FR-018.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Nothing irreversible happens without me saying so (Priority: P1)

The user asks the assistant to do something with real-world consequences. Before anything happens, the assistant states plainly what it intends to do — naming the specific items, not describing the category — and waits. Nothing executes until the user confirms. When the user confirms, exactly what was described happens, and nothing else.

If the user never answers, the pending action expires rather than lingering forever or firing on timeout.

**Why this priority**: This is the entire justification for the feature shipping as one slice. Without it, the workers in User Story 3 are a liability rather than a capability. It is also independently valuable: it applies retroactively to every tool Features 001 and 002 already exposed.

**Independent Test**: Fully testable using only existing tools, before any worker exists. Classify an existing tool as Tier 3, ask the assistant to use it, and confirm it states a plan and waits; confirm and observe exactly that plan execute; let a second one expire unanswered and observe it not execute.

**Acceptance Scenarios**:

1. **Given** a tool classified Tier 3, **When** the assistant decides to call it, **Then** no call occurs, and the user is shown a statement of the specific action intended.
2. **Given** a stated Tier 3 plan, **When** the user explicitly confirms, **Then** the stated action executes and no action outside the stated plan executes.
3. **Given** a stated Tier 3 plan, **When** the configured expiry interval passes with no answer, **Then** the action does not execute and the user can see that it expired rather than silently vanishing.
4. **Given** a tool classified Tier 1, **When** the assistant calls it, **Then** it executes with no interruption and no confirmation prompt.
5. **Given** a tool classified Tier 2, **When** the assistant calls it, **Then** it executes without prior confirmation and the reply discloses that it happened.

---

### User Story 2 - A confirmation can only come from me (Priority: P1)

The assistant is waiting on a Tier 3 confirmation. Two things that are not the user attempt to supply one: a proactive turn generated by the trigger engine, and text that arrived inside a tool result — a calendar event description, a web page, an email body. Neither satisfies the confirmation, and neither can initiate a Tier 3 action on its own.

**Why this priority**: A confirmation gate that anything can satisfy is not a gate. This is the difference between a guardrail and the appearance of one, and it is the specific attack the feature's own capabilities create — the browser and email workers introduce attacker-controlled text directly into the assistant's context.

**Independent Test**: Testable without any worker. Stage a pending Tier 3 action; attempt confirmation from a trigger-injected turn and observe it rejected; separately, stage a tool result whose content reads as a confirmation and observe it rejected.

**Acceptance Scenarios**:

1. **Given** a pending Tier 3 action, **When** a trigger-injected turn supplies text that would otherwise confirm it, **Then** the action does not execute.
2. **Given** a pending Tier 3 action, **When** content originating inside a tool result supplies text that would otherwise confirm it, **Then** the action does not execute.
3. **Given** a web page or email body containing an instruction to perform a Tier 3 action, **When** the assistant reads it, **Then** no Tier 3 action is initiated by that content.
4. **Given** the same pending action, **When** the user confirms through a normal interactive turn, **Then** it executes.

---

### User Story 3 - The assistant becomes useful in my day (Priority: P1)

The user can ask the assistant to do real work: find a time everyone is free and hold it, draft an invitation, read a page, clear a cluttered day. Reading is silent. Reversible changes happen and are disclosed. Anything irreversible or outbound is stated and confirmed first.

Email is read-and-draft only. The assistant cannot send mail — not because sending is guarded, but because the capability is absent from what it can reach at all.

**Why this priority**: This is the user-visible point of the feature. It is P1 alongside the policy engine because the two only make sense together, but it is sequenced after it.

**Independent Test**: Demonstrable end to end without the trigger engine running. Ask for a mutual free slot, a hold, and a draft invitation; verify the hold exists, the draft is saved, and nothing was sent.

**Acceptance Scenarios**:

1. **Given** two calendars, **When** the user asks for a mutual free slot and a hold, **Then** the hold is created, the assistant discloses it, and no confirmation was required.
2. **Given** a request to draft an invitation, **When** the assistant completes it, **Then** a draft exists and nothing has been sent.
3. **Given** a cluttered day, **When** the user asks the assistant to clear it, **Then** the assistant names each meeting it would decline or delete before acting, executes nothing until confirmed, and then executes exactly that set.
4. **Given** any request to send email, **When** the assistant attempts it, **Then** no send capability exists to attempt — the limitation is visible as an absent capability, not a refusal.
5. **Given** a browsing task, **When** the assistant reads and navigates, **Then** no confirmation is required; **When** it would submit a form or complete a purchase, **Then** it states the plan and waits.

---

### User Story 4 - A new tool is dangerous until I say otherwise (Priority: P2)

The user connects a new tool source. Its tools were not in the classification config when it was written. Every one of them is treated as Tier 3 until the user classifies them, including tools that appear after the config was last edited.

**Why this priority**: P2 because it protects against a future action rather than enabling a present one, but it is the property that keeps the policy engine correct as the system grows. A default of "allow" would silently erode every guarantee above.

**Independent Test**: Connect a tool source with a tool matching no rule and observe the assistant state a plan and wait before using it.

**Acceptance Scenarios**:

1. **Given** a tool matching no classification rule, **When** the assistant calls it, **Then** it is treated as Tier 3.
2. **Given** a tool source connected after the classification config was last written, **When** its tools are called, **Then** they are treated as Tier 3 without any config change.
3. **Given** a tool whose tier depends on its arguments, **When** it is called with arguments matching a declared exception, **Then** the exception's tier applies rather than the tool's default tier.

---

### User Story 5 - I am told about a meeting before it starts (Priority: P3)

A configured interval before a calendar event, the assistant proactively says who the meeting is with and what it is about, drawing on memory for anything relevant about that person or topic.

**Why this priority**: P3 and explicitly last, because it depends on a precondition outside this feature (VP-005). It is specified in full so it can be built the moment that dependency lands, but nothing in User Stories 1–4 may wait on it.

**Independent Test**: Testable only once the trigger engine runs (see Dependencies). Configure a rule, create an event, and observe one pre-alert at the stated interval.

**Acceptance Scenarios**:

1. **Given** a rule and an upcoming event, **When** the configured interval before it is reached, **Then** one pre-alert is delivered naming the attendees and subject.
2. **Given** the same event, **When** the engine evaluates repeatedly before it starts, **Then** exactly one pre-alert is delivered.
3. **Given** the calendar source, **When** it is added, **Then** the existing trigger engine's core requires no change to accommodate it.

---

### Edge Cases

- A Tier 3 action is confirmed after its expiry interval has passed — the confirmation is not honoured, and the user is told why rather than seeing silence.
- The classification config is edited while a Tier 3 action is pending — the tier in force at the time the plan was stated governs, so a reclassification cannot retroactively downgrade an action already awaiting confirmation.
- A tool result contains text resembling a plan statement, attempting to make the user believe the assistant proposed something it did not.
- Two Tier 3 actions are pending simultaneously and the user confirms ambiguously — an ambiguous confirmation satisfies neither.
- The classification config is missing, unreadable, or malformed — every tool is Tier 3 rather than every tool being unclassified.
- Redaction fails on worker output crossing to a remote channel — delivery is suppressed rather than sent unredacted.
- A calendar event is deleted between the pre-alert firing and its delivery.
- The browser is asked to navigate to a site the user has granted no login for.

## Requirements *(mandatory)*

### Functional Requirements — Policy Engine

- **FR-001**: Every tool call MUST be classified before it executes. A tool call that reaches execution without classification is a defect, not a degraded mode.
- **FR-002**: There MUST be exactly one dispatch path through which tool calls are classified. A second path that bypasses classification MUST fail the build, not be caught in review.
- **FR-003**: The single-path guarantee MUST cover every agent-construction site, including the one identified in VP-006 that currently assembles its own interception chain. That site MUST either be routed through the shared path or removed from the public surface. A gate covering only the convergent sites does not satisfy FR-002, because its scope boundary would be exactly where the bypass lives.
- **FR-004**: A Tier 3 confirmation MUST be rejected when the turn supplying it is marked as machine-generated rather than user-originated. This MUST be determined from the turn's structural marker as described in VP-003, never from the text of the message.
- **FR-005**: A Tier 3 confirmation MUST be rejected when the content supplying it originated inside a tool result. This MUST be determined from the lineage of the content in the conversation, never from the text of the message. *(FR-004 and FR-005 are deliberately separate requirements with separate mechanisms: one answers "who is speaking", the other "where did this content come from". The constitution states them in one sentence; in code they are two, and as a single requirement one of them gets half-implemented.)*
- **FR-006**: Content originating inside a tool result MUST NOT initiate a Tier 3 action, independently of whether it could confirm one.
- **FR-007**: Classification MUST be declarative and user-owned — expressed in configuration the user can read and edit, not in code.
- **FR-008**: Classification MUST support matching on tool name by pattern, and MUST support per-argument exceptions where a tool's tier depends on what it is being asked to do.
- **FR-009**: A tool matching no classification rule MUST be treated as Tier 3. This MUST hold for tools that did not exist when the configuration was written, and when the configuration is missing or unreadable.
- **FR-010**: Every tool already exposed by Features 001 and 002 MUST be classified. No tool anywhere in the system may be unclassified.
- **FR-011**: Every Tier 3 execution MUST be recorded in the audit log, including the actor it acted as, the plan exactly as stated to the user, and the confirmation that authorised it. *(Depends on the precondition in VP-005 — see Dependencies.)*
- **FR-019**: An unconfirmed Tier 3 action MUST expire after a stated, configurable interval. It MUST NOT wait indefinitely and MUST NOT execute on expiry.
- **FR-020**: Tier behaviour MUST be: Tier 1 executes silently; Tier 2 executes and is disclosed in the reply; Tier 3 states its plan, waits for confirmation, then executes.
- **FR-021**: A stated Tier 3 plan MUST name the specific items it will affect, not the category of action. Confirming a plan MUST authorise exactly the stated items and nothing else.

### Functional Requirements — Workers

- **FR-012**: The email send capability MUST be absent from the set of tools the assistant can call. This is a stronger guarantee than classifying it Tier 3, and its acceptance is by inspection of what the assistant can actually reach, not by the presence of a policy rule.
- **FR-013**: Satisfying FR-012 requires a per-tool allow/deny capability in tool-source configuration, which does not exist today (VP-004). This mechanism MUST be built as part of this feature. *(The rest of the worker configuration is declarative; this one item is written, not configured. The framing correction is deliberate — treating it as configuration would leave FR-012 unmet and appearing met.)*
- **FR-014**: Email tools MUST be limited to reading and drafting. A saved draft is its own confirmation gate: nothing leaves until the user sends it themselves.
- **FR-015**: Calendar tools MUST be classified as: reading events and free/busy is Tier 1; creating a tentative hold is Tier 2; deleting events, declining invitations, and modifying meetings owned by others are Tier 3.
- **FR-016**: Browser tools MUST be classified as: reading and navigating are Tier 1; submitting a form, completing a purchase, or any interaction that writes to a remote system is Tier 3.
- **FR-017**: The browser MUST use a dedicated profile that is logged into nothing by default. Its storage MUST be verifiably isolated from the user's everyday browser profile — demonstrated by test, not asserted by convention. The user grants logins per site deliberately.
- **FR-018**: Any worker output crossing to a remote channel MUST pass through redaction, including page content and email bodies. Redaction MUST fail closed: when it cannot complete, delivery is suppressed rather than sent unredacted. It MUST be consumed as an injected dependency in the shape described in VP-007, rather than statically imported or reimplemented.
- **FR-022**: Redaction patterns MUST be assessed against the input shapes this feature introduces. Page content and email bodies are wider and less structured than the session records and agent output earlier features tuned for. Where patterns are widened, the widening MUST be covered by the redactor's own tests so a change here cannot silently weaken Features 001 or 002.
- **FR-023**: The assistant MUST describe its own limits honestly. Where a capability is absent (FR-012) or an action requires confirmation, the user-facing wording MUST say what is actually true and MUST NOT imply a capability the assistant does not have.

### Functional Requirements — Calendar Triggers

- **FR-024**: A calendar trigger type MUST fire a stated interval before a calendar event. *(Depends on VP-005 — see Dependencies.)*
- **FR-025**: The calendar trigger MUST be a new event source feeding the existing trigger engine. It MUST NOT require changes to that engine's core. If building it reveals that engine changes are required, that is a finding to report before building, not a change to make quietly.
- **FR-026**: A pre-alert MUST name who the meeting is with and what it is about, drawing on memory for relevant context about that person or topic.
- **FR-027**: Exactly one pre-alert MUST be delivered per event occurrence, however many times the engine evaluates the rule beforehand.

### Key Entities

- **Tier**: One of three levels of consequence — read, reversible write, irreversible/outbound/spawning — determining whether a call executes silently, executes with disclosure, or requires confirmation first.
- **Classification Rule**: A user-authored, declarative statement mapping a tool-name pattern to a tier, optionally with per-argument exceptions. Absence of a matching rule is itself meaningful (FR-009).
- **Pending Action**: A Tier 3 call that has been stated to the user and is awaiting confirmation. Carries the exact plan as stated, the tier in force when stated, and an expiry.
- **Confirmation**: A user response authorising a specific Pending Action. Has an origin — which turn it came from and whether that content originated in a tool result — and is valid only from a trusted origin (FR-004, FR-005).
- **Turn Provenance**: The structural marker distinguishing a user-originated turn from a machine-generated one. Established by Feature 002; readable at dispatch per VP-003.
- **Content Lineage**: Whether a piece of conversation content originated from the user or arrived inside a tool result. Distinct from Turn Provenance and determined by a different mechanism.
- **Worker**: An external tool source (email, calendar, browser) with an associated tier map.
- **Audit Entry**: A record of a Tier 3 execution — the actor, the plan as stated, and the authorising confirmation.
- **Browser Profile**: An isolated storage context for assistant-driven browsing, holding only logins the user granted deliberately.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A Tier 3 action confirmed by a machine-generated turn does not execute. Verified by observing the action not occur, not by observing a rejection message.
- **SC-002**: A Tier 3 action confirmed by content that originated inside a tool result does not execute. Verified separately from SC-001, against the separate mechanism.
- **SC-003**: A tool matching no classification rule is treated as Tier 3, including a tool introduced after the configuration was last edited, and including when the configuration is unreadable.
- **SC-004**: The email send capability is absent from what the assistant can call — verified by inspecting the assistant's available capabilities, not by the presence of a policy rule.
- **SC-005**: Asking the assistant to clear a cluttered day produces a plan naming each meeting it will decline or delete, executes nothing before confirmation, and after confirmation executes exactly that set and nothing else.
- **SC-006**: Finding a mutual free slot, holding it, and drafting an invitation completes with the hold created, the draft saved, and nothing sent.
- **SC-007**: A browser session started by the assistant carries none of the user's everyday browser cookies or sessions, demonstrated by test.
- **SC-008**: An unconfirmed Tier 3 action expires within the configured interval and does not execute.
- **SC-009**: No dispatch path bypasses classification. Verified by deliberately introducing a bypassing path and observing the build fail — including a bypass introduced at the agent-construction site named in VP-006.
- **SC-010**: 100% of tools exposed anywhere in the system resolve to a tier, including those from Features 001 and 002.
- **SC-011**: Every Tier 3 execution appears in the audit log with actor, stated plan, and authorising confirmation. *(Gated — see Dependencies.)*
- **SC-012**: A meeting starting soon produces exactly one pre-alert through the existing trigger engine, with no change to that engine's core. *(Gated — see Dependencies.)*
- **SC-013**: Worker output crossing to a remote channel is redacted, and when redaction cannot complete, nothing is delivered.

## Dependencies

- **DEP-001 (BLOCKING for FR-011, FR-024–FR-027, SC-011, SC-012)**: The Feature 002 trigger engine must be started by the running product, with its audit log constructed in production. It is not today (VP-005). This is being resolved by a separate change — single-runner election via a database advisory lock — that lands before implementation of this feature begins.

  **This dependency MUST NOT block Parts 1 and 2.** User Stories 1–4 and SC-001 through SC-010 and SC-013 must be independently demonstrable while User Story 5 is pending. Phase ordering must make this true rather than assuming it.

  Where FR-011's audit requirement cannot yet be satisfied, the correct response is to sequence it behind DEP-001 — not to record Tier 3 executions somewhere else in the meantime, which would leave two audit trails to reconcile.

- **DEP-002**: The provenance repair described in VP-003 has landed. FR-004 depends on it and must exercise it, not assume it.

## Assumptions

- The three tiers are as the constitution defines them; this feature makes them operational rather than redefining them.
- The user is a single individual, not an organisation with roles. Classification is owned by that one user.
- Email, calendar, and browser capabilities are reached as external tool sources configured by the user, who supplies their own credentials. Provider account setup is the user's responsibility and outside this feature.
- Confirmation happens in the same conversation as the stated plan. Out-of-band confirmation channels are out of scope.
- The default expiry interval for an unconfirmed Tier 3 action is assumed to be a small number of hours — long enough to survive a meeting, short enough that a forgotten action does not linger for days. **This is a starting guess, not a measured value**, and is stated as such in the configuration so it does not acquire false authority.
- "Reversible" for a calendar hold means the assistant can delete what it created. Reversibility is assessed against what the assistant can itself undo, not against what the provider technically permits.
- Memory content used in pre-alerts (FR-026) is already available from earlier work; this feature reads it rather than building it.
- Redaction covers recognised patterns only. It reduces exposure and does not guarantee that no sensitive content crosses a channel — user-facing wording must not claim otherwise.

## Out of Scope

- Sending email. Deliberately absent, not deferred (FR-012).
- Multi-user or role-based permissions.
- Confirmation through a channel other than the conversation where the plan was stated.
- Provider account provisioning and credential issuance.
- Any trigger type beyond the calendar source named here.
- Undo of an executed Tier 3 action. The gate is before execution; this feature does not add rollback.
