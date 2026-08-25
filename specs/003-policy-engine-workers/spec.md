# Feature Specification: Permission Policy Engine & Real-World Workers

**Feature Branch**: `003-policy-engine-workers`

**Created**: 2026-08-23

**Status**: Draft

**Input**: User description: Feature 003 — a policy layer that classifies every tool call before dispatch, plus the first tools that can affect the user's life outside their own machine (email drafting, calendar, browser), plus calendar-sourced triggers. Amended before drafting with four verified corrections (see Verified Preconditions).

## Overview

Until now every tool the assistant could reach was read-only and local. Feature 001 observed coding sessions; Feature 002 let the assistant speak first. Neither could change anything the user would miss.

This feature is the first where a mistake costs the user something real — a deleted meeting, a declined invitation, a submitted form. The guardrail therefore ships in the same slice as the capability, not after it. The policy engine is not a feature bolted beside the workers; it is the precondition for having them at all.

Constitution Article II defines three tiers of action. This feature makes them operational and applies them to every tool in the system, including those Features 001 and 002 already exposed.

## Clarifications

### Session 2026-08-23

- Q: When a Tier 2 action executes and must be disclosed in the reply, is that disclosure produced by the system, or is the model expected to mention it? → A: B — the system records each Tier 2 execution and GUARANTEES the disclosure appears, appending it when the model's own text omits it; the model may phrase it but cannot skip it. Two things pinned: (1) the coverage check is BIASED TOWARD APPENDING — when uncertain whether the model's text already discloses the action, append, because a redundant disclosure is clumsy while a missing one is the defect the requirement exists to prevent; (2) appended disclosures are generated FROM THE RECORDED EXECUTION, never from the model's account of it.
- Q: When a per-argument exception applies to a tool call, may it move that call to a LOWER tier than the tool's default, or only to a higher one? → A: A — exceptions may only RAISE a tier, never lower it; making something safer than its default requires editing the tool's default, which is a visible change rather than a narrow exception. One addition: provide a way to inspect the effective tier of a hypothetical call WITHOUT executing it, showing which rule decided it — raise-only is safe but opaque, and without a way to see why a call was raised the pressure to add lowering exceptions returns. Options B and D (either direction; either direction with lowering rules marked) were considered and REJECTED: both put the central guarantee behind a casually-edited config where one over-broad rule disables it silently, and D's marking only helps a reader who looks, while the failure mode is a rule nobody re-reads.
- Q: What form must a user's confirmation take for a Tier 3 action to execute — free-form agreement the model interprets, or a specific act the system recognises without interpretation? → A: B — the system recognises confirmation DETERMINISTICALLY and the model never adjudicates it; ambiguous replies are re-asked, not interpreted. Two additions: (1) an unrecognised reply is re-asked with the PLAN RESTATED IN FULL, not merely re-prompted; (2) recognised DECLINE must be as deterministic as recognised confirm. Option C (free-form interpretation over user-lineage text only) was considered and REJECTED: it closes the injection path but leaves the gate resting on model judgment for ambiguous replies, so the check stays interpretive where B makes it mechanical.
- Q: When the lead agent delegates to a subagent and that subagent calls a tool, does the policy layer classify that call, and who confirms a Tier 3 hit? → A: A — classified identically; a Tier 3 hit suspends the subagent and asks the USER through the lead agent's conversation. Delegation grants no authority the delegator did not have. Two additions: (1) suspend/resume was VERIFIED against the runtime and DOES NOT currently work for subagents — see VP-008, which this feature must fix rather than plan around; (2) the confirmation names the requester and the delegation chain. Option D (a confirmed delegation covering all subsequent Tier 3 calls) was considered and REJECTED: it makes delegation a privilege escalation, one confirmation buying unlimited authority.
- Q: When the assistant states a Tier 3 plan and waits, where does that pending action live — and does it survive the process that created it? → A: A — durable store, same mechanism as Feature 002's pending firings; any worker can find, confirm and expire it, and it survives restart. Two additions: (1) the record stores the RESOLVED, SPECIFIC targets, not a description, and a confirmation whose recorded targets no longer match current reality is declined and restated rather than approximated; (2) claiming a confirmed pending action is ATOMIC — one confirmation, one execution.

## Verified Preconditions

*This section records mechanisms confirmed against the running code before this spec was written, following the project convention that a plan may not rest on an unverified assumption. Each was checked; two were found broken and one has been repaired.*

- **VP-001 — A single tool-dispatch chokepoint exists.** Four of five agent-construction sites converge on one shared middleware assembly, and the agent framework exposes a tool-call interception hook at which a call may be inspected, allowed, or refused without executing. Refusal is expressible: the interceptor may decline to run the tool and return a result in its place.
- **VP-002 — All tool sources normalise to one shape.** Built-in tools, MCP-server tools, third-party connector tools, and agent-to-agent tools are all assembled into a single list and executed through the same path. There is no tool category that reaches execution by another route.
- **VP-003 — The synthetic-turn marker is readable at dispatch (REPAIRED).** Feature 002 marks trigger-injected turns structurally, where message content cannot forge it. That marker was **not** readable at the dispatch chokepoint: the interception hook receives no run configuration, and the only container it can read had stopped being populated from the one the marker lives in. This broke silently on a dependency upgrade, with no test failing, because nothing was reading it yet. It has been repaired and is now guarded by a test that reads the marker from inside the interception hook. **FR-004 depends on this and must not re-verify it by assumption.**
- **VP-004 — Tool-surface filtering is server-granular, not per-tool (GAP).** Tools can be included or excluded a whole server at a time; there is no per-tool allow or deny capability in the server configuration. FR-012's requirement is therefore *written*, not *configured* — see FR-013.
- **VP-005 — Feature 002 is running (RESOLVED).** The engine had no consumer outside itself and its own tests; nothing started it and its audit log was never constructed in production. It is now started by the gateway under single-runner election, with a durable pending set and an audit log carrying a required actor. A repo-level gate keeps any module under `app/` from becoming orphaned the same way. Part 3 and FR-011 rest on a live mechanism.
- **VP-006 — A fifth agent-construction path bypasses the chokepoint.** One agent factory assembles its own interception chain and does not pass through the shared one. It is public API with no production consumer. Anything built through it would escape classification entirely — see FR-003.
- **VP-008 — Subagents cannot currently be suspended and resumed (GAP, must be fixed here).** FR-031 requires suspending a subagent mid-run and resuming it with a tool result after an arbitrary wait. Measured against the runtime:

  | Shape | Behaviour |
  |---|---|
  | With a checkpointer (the lead agent's shape — one is attached at run time) | suspends, resumes, and the tool then runs |
  | Without a checkpointer (the subagent's shape — none is ever attached) | the run **ends** at the suspension point; the tool never runs and there is nothing to resume from |

  It does not raise. A subagent asked to confirm would simply stop, having done nothing, which is indistinguishable from a correct refusal in any test that never confirms. That is the failure this verification existed to catch. The fix is small and known — attach a checkpointer to the subagent agent as the run worker already does for the lead agent — but it is a TASK, not an assumption.

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
- A subagent requests a Tier 3 action, the user is asked, and the user does not answer before the pending action expires — the subagent resumes with a refusal rather than hanging or being abandoned mid-run.
- A tool result contains text resembling a plan statement, attempting to make the user believe the assistant proposed something it did not.
- Two Tier 3 actions are pending simultaneously and the user confirms ambiguously — an ambiguous confirmation satisfies neither, and both plans are restated.
- The user replies with something that is neither a recognised confirmation nor a recognised decline — the plan is restated in full and re-asked, rather than being interpreted or silently dropped.
- A confirmation arrives after the world has moved: an event in the stated plan has already been deleted, or a held slot has been taken. The recorded targets no longer match, so the action is declined and restated rather than executed against a different reality than the one approved.
- Two workers read the same confirmed Pending Action at the same moment — exactly one claims it and executes; the other finds it already claimed and does nothing.
- The process that stated a plan restarts before the user answers — the pending action is still there, still confirmable, and still expires on its original schedule.
- The classification config is missing, unreadable, or malformed — every tool is Tier 3 rather than every tool being unclassified.
- The model claims in its reply to have done something it did not do, or describes a Tier 2 action inaccurately — the appended disclosure is generated from the execution record, so what the user reads about the action is what happened.
- Several Tier 2 actions occur in one turn and the model mentions some but not others — the unmentioned ones are appended.
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
- **FR-011**: Every Tier 3 execution MUST be recorded in the audit log, including the actor it acted as, the plan exactly as stated to the user, and the confirmation that authorised it. *(Depends on Feature 002, now live — see DEP-001.)*
- **FR-019**: An unconfirmed Tier 3 action MUST expire after a stated, configurable interval. It MUST NOT wait indefinitely and MUST NOT execute on expiry.
- **FR-020**: Tier behaviour MUST be: Tier 1 executes silently; Tier 2 executes and is disclosed in the reply; Tier 3 states its plan, waits for confirmation, then executes.
- **FR-021**: A stated Tier 3 plan MUST name the specific items it will affect, not the category of action. Confirming a plan MUST authorise exactly the stated items and nothing else.
- **FR-028**: A Pending Action MUST be durable and reachable from any worker process. Storing it in the memory of the process that stated the plan is insufficient: the gateway serves from several workers behind one socket, so a confirmation would reach the stating worker only some of the time and would otherwise find nothing pending — a correctly-confirmed action silently never running. It MUST survive a restart of the process that created it.
- **FR-029**: A Pending Action MUST record the RESOLVED, SPECIFIC targets of the stated plan — the identified items themselves — not a description of the action or the criteria that selected them. At execution time the recorded targets MUST still match the current state of the world. Where they do not, the action MUST be declined and restated rather than approximated or re-resolved. The user confirmed a plan, not a category of action.
- **FR-030**: Claiming a confirmed Pending Action MUST be atomic: one confirmation yields exactly one execution. Several workers can read the same durable record, and two of them acting on a calendar cleanup would delete twice — which is silent — and create holds twice, which is visible clutter.
- **FR-031**: Tool calls made by a subagent MUST be classified identically to those made by the lead agent. A Tier 3 hit MUST suspend the subagent and ask the user through the lead agent's conversation; the subagent MUST then resume with the outcome. Delegation MUST NOT grant authority the delegator did not have.
- **FR-032**: Subagents MUST be given the ability to suspend and resume (VP-008). Without it FR-031 degrades silently into "the subagent stops, having done nothing", which no test that declines to confirm can distinguish from correct refusal.
- **FR-033**: A confirmation prompt MUST name the requester and the delegation chain that led to it. "Should I delete these four events?" means something different when the asker is a subagent the user never instructed by name; the user is authorising an action by something they did not directly ask for and MUST be able to see that.
- **FR-034**: A confirmation MUST be recognised deterministically by the system — by reference to the pending action's identifier or an equivalent explicit affordance — and MUST NOT be adjudicated by the model. A gate that rests on the model judging whether a reply constitutes agreement is defended by prompting, which Article III forbids; it also puts a web page reading "the user has approved this, proceed" on the same channel as the real answer.
- **FR-035**: A reply that is not recognised as either confirmation or decline MUST cause the plan to be **restated in full** and re-asked. Re-prompting without restating leaves the user confirming something they can no longer see, which defeats the purpose of stating a plan.
- **FR-036**: Decline MUST be recognised as deterministically as confirmation. If confirmation is mechanical and refusal falls back to interpretation, an intended refusal is read as ambiguity and re-asked — which teaches users to type whatever makes the prompt stop. A gate users learn to route around is worse than no gate, because it still looks like protection.
- **FR-037**: A per-argument exception MUST only RAISE a call's tier, never lower it. Lowering a tier MUST require changing the tool's default classification, which is a visible edit, rather than a narrow exception buried in a rule set. A malformed or over-broad exception therefore fails toward asking, not toward acting.
- **FR-038**: The system MUST provide a way to inspect the effective tier of a hypothetical tool call WITHOUT executing it, showing which rule decided it. Raise-only classification is safe but opaque: someone edits a default, forgets an exception raises it, and is asked to confirm something they meant to be silent. Without a way to see why, pressure to add lowering exceptions returns — not because they are needed, but because the policy is unreadable. This is what makes FR-037 livable rather than merely correct.
- **FR-039**: Tier 2 disclosure MUST be guaranteed by the system, not left to the model. Each Tier 2 execution MUST be recorded, and the reply MUST be checked for a disclosure of it; where none is present, the system MUST append one. The model MAY phrase a disclosure itself; it MUST NOT be able to omit one. Disclosure left to prompt guidance is unverifiable, and a turn where the model forgets is indistinguishable from a turn in which nothing happened — which makes Tier 2 into Tier 1 with good intentions.
- **FR-040**: The disclosure coverage check MUST be biased toward appending: where it is uncertain whether the model's text already discloses an action, it MUST append. A redundant disclosure is clumsy; a missing one is the defect FR-039 exists to prevent. Stating the direction is required because without it the check is tuned toward not-appending — duplicates are the visible failure and omissions the invisible one.
- **FR-041**: An appended disclosure MUST be generated from the RECORDED EXECUTION — the tool called, its resolved arguments, and its result — and MUST NOT be generated from the model's account of what it did. A model that misdescribes its own action would otherwise produce a disclosure that satisfies the coverage check while misinforming the user, which is worse than silence because it carries the system's authority rather than the model's.

### Functional Requirements — Workers

- **FR-012**: The email send capability MUST be absent from the set of tools the assistant can call. This is a stronger guarantee than classifying it Tier 3, and its acceptance is by inspection of what the assistant can actually reach, not by the presence of a policy rule.
- **FR-013**: Satisfying FR-012 requires a per-tool allow/deny capability in tool-source configuration, which does not exist today (VP-004). This mechanism MUST be built as part of this feature. *(The rest of the worker configuration is declarative; this one item is written, not configured. The framing correction is deliberate — treating it as configuration would leave FR-012 unmet and appearing met.)*
- **FR-014**: Email tools MUST be limited to reading and drafting. A saved draft is its own confirmation gate: nothing leaves until the user sends it themselves.
- **FR-015**: Calendar tools MUST be classified as: reading events and free/busy is Tier 1; creating a tentative hold is Tier 2; deleting events, declining invitations, and modifying meetings owned by others are Tier 3.
- **FR-016**: ~~Browser tools MUST be classified as: reading and navigating are Tier 1; submitting a form, completing a purchase, or any interaction that writes to a remote system is Tier 3.~~ **CUT FROM 003 — 2026-08-24.** See *Cut from this feature* below.
- **FR-017**: ~~The browser MUST use a dedicated profile that is logged into nothing by default...~~ **CUT FROM 003 — 2026-08-24.** The requirement is right and unchanged; it cannot be *verified* here. See below.
- **FR-018**: Any worker output crossing to a remote channel MUST pass through redaction, including page content and email bodies. Redaction MUST fail closed: when it cannot complete, delivery is suppressed rather than sent unredacted. It MUST be consumed as an injected dependency in the shape described in VP-007, rather than statically imported or reimplemented.
- **FR-022**: Redaction patterns MUST be assessed against the input shapes this feature introduces. Page content and email bodies are wider and less structured than the session records and agent output earlier features tuned for. Where patterns are widened, the widening MUST be covered by the redactor's own tests so a change here cannot silently weaken Features 001 or 002.
- **FR-023a**: *(Applies when the browser worker lands — see Cut from this feature.)* The browser worker's disk cost MUST be stated to the user as a **measured** figure, not an estimate: a Chromium build is **356 MB** and its headless shell **196 MB** — roughly **550 MB of disk** — measured 2026-08-24 from an installed bundle, not projected. The browser runs on demand and is not resident, so Article VI's idle-memory budget is unaffected; the disk cost is nonetheless real and MUST NOT be omitted from setup guidance because it is inconvenient (Article X).
- **FR-023**: The assistant MUST describe its own limits honestly. Where a capability is absent (FR-012) or an action requires confirmation, the user-facing wording MUST say what is actually true and MUST NOT imply a capability the assistant does not have.

### Functional Requirements — Calendar Triggers

- **FR-024**: A calendar trigger type MUST fire a stated interval before a calendar event. *(Depends on Feature 002, now live — see DEP-001.)*
- **FR-025**: The calendar trigger MUST be a new event source feeding the existing trigger engine. It MUST NOT require changes to that engine's core. If building it reveals that engine changes are required, that is a finding to report before building, not a change to make quietly.
- **FR-026**: A pre-alert MUST name who the meeting is with and what it is about, drawing on memory for relevant context about that person or topic.
- **FR-027**: Exactly one pre-alert MUST be delivered per event occurrence, however many times the engine evaluates the rule beforehand.

### Key Entities

- **Tier**: One of three levels of consequence — read, reversible write, irreversible/outbound/spawning — determining whether a call executes silently, executes with disclosure, or requires confirmation first.
- **Classification Rule**: A user-authored, declarative statement mapping a tool-name pattern to a tier, optionally with per-argument exceptions that may only raise the resulting tier (FR-037). Absence of a matching rule is itself meaningful (FR-009). Which rule decided a given call is inspectable without executing it (FR-038).
- **Pending Action**: A Tier 3 call that has been stated to the user and is awaiting confirmation. Records the requester and delegation chain when the call originated in a subagent (FR-033). Durable and reachable from any worker (FR-028). Carries the exact plan as stated, the **resolved specific targets** it will act on (FR-029), the tier in force when stated, an expiry, and a claim state that exactly one confirmation can take (FR-030).
- **Confirmation**: A deterministically recognised user act authorising a specific Pending Action — never a model judgement about whether a reply meant agreement (FR-034). Decline is recognised the same way (FR-036). Has an origin — which turn it came from and whether that content originated in a tool result — and is valid only from a trusted origin (FR-004, FR-005).
- **Turn Provenance**: The structural marker distinguishing a user-originated turn from a machine-generated one. Established by Feature 002; readable at dispatch per VP-003.
- **Content Lineage**: Whether a piece of conversation content originated from the user or arrived inside a tool result. Distinct from Turn Provenance and determined by a different mechanism.
- **Worker**: An external tool source (email, calendar, browser) with an associated tier map.
- **Audit Entry**: A record of a Tier 3 execution — the actor, the plan as stated, and the authorising confirmation.
- **Execution Record**: What a Tier 2 action actually did — the tool, its resolved arguments, its result. The sole source for an appended disclosure (FR-041), and distinct from the model's narration of the same event.
- **Browser Profile**: An isolated storage context for assistant-driven browsing, holding only logins the user granted deliberately.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A Tier 3 action confirmed by a machine-generated turn does not execute. Verified by observing the action not occur, not by observing a rejection message.
- **SC-002**: A Tier 3 action confirmed by content that originated inside a tool result does not execute. Verified separately from SC-001, against the separate mechanism.
- **SC-003**: A tool matching no classification rule is treated as Tier 3, including a tool introduced after the configuration was last edited, and including when the configuration is unreadable.
- **SC-004**: The email send capability is absent from what the assistant can call — verified by inspecting the assistant's available capabilities, not by the presence of a policy rule.
- **SC-005**: Asking the assistant to clear a cluttered day produces a plan naming each meeting it will decline or delete, executes nothing before confirmation, and after confirmation executes exactly that set and nothing else.
- **SC-006**: Finding a mutual free slot, holding it, and drafting an invitation completes with the hold created, the draft saved, and nothing sent.
- **SC-007**: ~~A browser session started by the assistant carries none of the user's everyday browser cookies or sessions, demonstrated by test.~~ **CUT FROM 003 — 2026-08-24**, because it cannot be demonstrated here and this is not a claim to make on reasoning.
- **SC-008**: An unconfirmed Tier 3 action expires within the configured interval and does not execute.
- **SC-009**: No dispatch path bypasses classification. Verified by deliberately introducing a bypassing path and observing the build fail — including a bypass introduced at the agent-construction site named in VP-006.
- **SC-010**: 100% of tools exposed anywhere in the system resolve to a tier, including those from Features 001 and 002.
- **SC-011**: Every Tier 3 execution appears in the audit log with actor, stated plan, and authorising confirmation. *(Depends on Feature 002, now live — see DEP-001.)*
- **SC-012**: A meeting starting soon produces exactly one pre-alert through the existing trigger engine, with no change to that engine's core. *(Depends on Feature 002, now live — see DEP-001.)*
- **SC-013**: Worker output crossing to a remote channel is redacted, and when redaction cannot complete, nothing is delivered.
- **SC-014**: A plan stated by one worker can be confirmed through another and executes exactly once. Verified with the gateway running its real worker count, not a single process (Article XI).
- **SC-015**: A confirmation whose recorded targets no longer match current reality does not execute, and the user is told what changed rather than seeing a silent no-op or an approximated action.
- **SC-016**: Concurrent confirmation attempts against one Pending Action produce exactly one execution.
- **SC-017**: A Tier 3 action requested by a subagent does not execute until the user confirms it, and the subagent then resumes and completes. Verified by confirming AFTER a delay, not immediately — an instant confirmation cannot distinguish suspend-and-resume from stop-and-abandon (VP-008).
- **SC-018**: A confirmation prompt originating in a subagent names the requester and the delegation chain.
- **SC-019**: A reply that is not a recognised confirmation or decline results in the full plan being restated, and no execution.
- **SC-020**: A recognised decline stops the action without re-asking, and is distinguishable in the audit record from an expiry and from an ambiguous reply.
- **SC-021**: An exception that would lower a call's tier does not lower it, and the discrepancy is visible to the user rather than silently ignored.
- **SC-022**: The effective tier of a hypothetical call, and the rule that decided it, can be inspected without the call executing.
- **SC-023**: Every Tier 2 execution is disclosed in the reply that caused it, including when the model's own text omits it.
- **SC-024**: An appended disclosure matches the recorded execution, and does not match a contradicting claim in the model's text.

## Dependencies

- **DEP-001 — RESOLVED 2026-08-23.** The Feature 002 trigger engine is now started by the gateway under single-runner election, its audit log is constructed in production with a required `actor` field, and pending firings are durable across the death of the worker holding them. Feature 002 is live, so FR-011 and FR-024–FR-027 rest on a running mechanism rather than a planned one.

  Two properties of that resolution carry into this feature and MUST NOT be re-derived:
  - **The engine runs in one elected worker; the policy layer does not.** A policy decision happens in whichever worker handles the run, which is why FR-028 requires the Pending Action to be durable and worker-independent rather than reusing the engine's election.
  - **In-memory state belonging to one worker is lost when that worker dies.** This was resolved for the engine's deferrals by persisting them; FR-028 applies the same conclusion to Pending Actions rather than rediscovering it.

- **DEP-002**: The provenance repair described in VP-003 has landed. FR-004 depends on it and must exercise it, not assume it.

## Assumptions

- The three tiers are as the constitution defines them; this feature makes them operational rather than redefining them.
- The user is a single individual, not an organisation with roles. Classification is owned by that one user.
- Email, calendar, and browser capabilities are reached as external tool sources configured by the user, who supplies their own credentials. Provider account setup is the user's responsibility and outside this feature.
- Confirmation happens in the same conversation as the stated plan. Out-of-band confirmation channels are out of scope.
- The default expiry interval for an unconfirmed Tier 3 action is assumed to be a small number of hours — long enough to survive a meeting, short enough that a forgotten action does not linger for days. **This is a starting guess, not a measured value**, and is stated as such in the configuration so it does not acquire false authority.
- "Reversible" for a calendar hold means the assistant can delete what it created. Reversibility is assessed against what the assistant can itself undo, not against what the provider technically permits.
- Memory content used in pre-alerts (FR-026) is already available from earlier work; this feature reads it rather than building it.
- The browser's ~550 MB disk footprint is measured (FR-023a), not estimated. Where any other resource figure appears in user-facing guidance it must be measured too, or labelled as a guess the way the Tier 3 expiry interval is.
- Redaction covers recognised patterns only. It reduces exposure and does not guarantee that no sensitive content crosses a channel — user-facing wording must not claim otherwise.

## Cut from this feature — the browser worker (2026-08-24), REOPENED (2026-08-25)

> **REOPENED. The cut stands for Feature 003; the REASONING no longer does.**
>
> The worker was cut because SC-007 could not be demonstrated — a browser bundle
> could not be produced, and *"carries none of your daily cookies"* is not a
> claim to make on reasoning. That was correct on the information available.
>
> **The information has changed.** A standalone CI job now downloads a 369 MB
> Chromium bundle in about four seconds and runs rendering assertions,
> including a class-toggle-and-read-computed-style check. The 448 KB failure is
> **local and environmental**, not a limit on what can be verified.
>
> SC-007 is therefore verifiable — in CI. FR-016, FR-017 and SC-007 go back on
> the roadmap as a **follow-up feature**, not as part of Feature 004, and not as
> a silent reinstatement inside 003. What carries forward unchanged: the
> requirements themselves, the positive-control-first spike design (prove the
> profile persists a cookie BEFORE trusting that it excludes one), and the
> measured ~550 MB disk figure in FR-023a.
>
> Recorded here rather than only in the roadmap so the cut is never read with
> its original reasoning still standing.


**FR-016, FR-017 and SC-007 are cut from Feature 003.** Email and calendar are unaffected and remain in scope.

**Why**: SC-007 says the assistant's browser "carries none of the user's everyday browser cookies or sessions, **demonstrated by test**". It could not be demonstrated. A browser bundle cannot be produced in the development environment: after two clean removals and reinstalls, the Playwright browser directory is created and stays at **448 KB** against roughly 350 MB for a complete build — the download never progresses. Every launch attempt fails at process start, which a 448 KB bundle fully explains.

**What that is and is not.** It is a local tooling limitation, not a finding about the design. Whether a *complete* bundle would launch here is untested, because one cannot be obtained to test with. Nothing about FR-017 has been shown to be wrong.

**Why cut rather than deferred within 003**: shipping the browser worker would mean shipping FR-017 unverified. *"Carries none of your daily cookies"* is a claim about the user's private browsing state, and it is not one to make on reasoning — an isolation test that has never been seen detecting a leak is not evidence of isolation (Article XII). A worker that is present but whose central guarantee is unproven is worse than one that is absent, because the absence is visible and the unproven guarantee is not.

**What carries forward unchanged**: the requirements themselves, the positive-control-first spike design (prove the profile persists a cookie BEFORE trusting that it excludes one), and the measured ~550 MB disk figure in FR-023a. When a working bundle is available the probe runs as written.

## Considered and Rejected

- **Tier 2 disclosure by prompt instruction alone.** Rejected: unverifiable, and its failure is invisible — a forgotten disclosure looks exactly like a turn in which nothing happened.
- **Deferring Tier 2 disclosures to a digest or on-request report.** Rejected: the point of disclosure is that the user learns of a change while it is still connected to the request that caused it. A hold created and reported hours later is a surprise with a citation.
- **Per-argument exceptions that may lower a tier, in either direction.** Rejected: it puts the feature's central guarantee behind a config file the user edits casually, where a single over-broad rule disables it silently for exactly the case it exists to cover.
- **Lowering permitted but marked, and surfaced whenever the policy is displayed.** Rejected for the same reason. Marking helps a reader who looks; the failure mode is a rule nobody re-reads.
- **Free-form confirmation interpreted by the model, restricted to text of genuine user lineage.** Rejected: excluding tool-result lineage closes the injection path, but the gate still rests on model judgment for ambiguous replies. That leaves the check interpretive where FR-034 makes it mechanical, and the interpretive part is where it fails under adversarial input.
- **A confirmed delegation covering all subsequent Tier 3 calls by that subagent.** Rejected: it makes delegation a privilege escalation — one confirmation buys unlimited authority, and the broader the delegated task the more it buys. Every Tier 3 call is confirmed on its own terms (FR-031).
- **Restricting subagents to Tier 1 and 2 only.** Rejected as the default: it is safe but makes delegation useless for exactly the work this feature exists to enable. A per-spawn tier ceiling remains available as a later refinement.

## Out of Scope

- Sending email. Deliberately absent, not deferred (FR-012).
- Multi-user or role-based permissions.
- Confirmation through a channel other than the conversation where the plan was stated.
- Provider account provisioning and credential issuance.
- Any trigger type beyond the calendar source named here.
- Undo of an executed Tier 3 action. The gate is before execution; this feature does not add rollback.
