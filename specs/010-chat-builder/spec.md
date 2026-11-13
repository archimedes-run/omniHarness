# Feature Specification: Chat builder

**Feature Branch**: `010-chat-builder` (one PR per slice, see [plan.md](plan.md))

**Created**: 2026-11-13

**Status**: Draft. The owner is away; every open question below carries a recommended default, recorded as decided. The owner may overturn any of them before the slice that uses it starts.

**Input**: "Any chat builds and edits agents, skills and automations." The person describes what they want in any chat; the assistant drafts it at once, asks at most a few questions on cards, and saves only on the owner's own say-so. Editing shows a before/after diff. MCP servers are out of scope here (they keep the MCP Suite; chat offers a "Build in MCP Studio" card). Folds in 005 Slice 5, automations from chat (005 US5, FR-060 to FR-064, tasks T046 to T049).

**Builds on**: the versioned config store (`omniharness/config/config_versions.py`, 006), the Studio wizards and Draft (`app/gateway/routers/drafts.py`, which never writes), standing grants (`app/policy/grants.py`), per-agent tool access (006-G), the automations write path (`app/gateway/automations_store.py`), confirmations and pending cards (#58, #139), provenance and lineage (003, 005 Amendment 1), and 009 Slice 0's resume after cards and Tier 2 disclosure (FR-057, FR-058, FR-063 of 009). The Question card is shared with 009 Slice 1b and is specified in `specs/009-orchestration/question-card.md`; this spec does not redefine it.

## What exists today, and what must be unified

| Thing | Store today | Gap |
|---|---|---|
| Agents (config + SOUL.md, autonomy, tool access) | `config_versions`, snapshot per version, undo as a new version, stale-write refusal | Chat writes go through `setup_agent` / `update_agent`, which take whole-field replacements and render as a generic Tier 3 card with no diff. |
| Skills (custom) | `config_versions` over the skill's history file | Chat writes go through `skill_manage`; same card, no diff. |
| Automations (trigger rules, incl. per-agent schedules) | `automations_store`: validated, atomic, hash-based stale-edit refusal on one rules file | **No version history and no undo.** The Studio Schedule tab and the Automations page write it; chat cannot. |

Unification: automations become a third kind in the same store (one version history per rule id, snapshot = the rule), still materialised into the rules file through `automations_store`'s validation and atomic write, which stays the runtime's source. Studio, the Automations page and the chat builder all write through that one store, so a version made in one is visible, diffable and undoable in the others.

## User Scenarios & Testing *(mandatory)*

### User Story 1: Build something new from any chat (Priority: P1)

In any chat the person writes "make me an agent that triages my inbox every morning and files tasks". The chat shows a **Building: Inbox triage** chip above the chat bar, and within the same reply a **Draft preview** card: name, description, instructions, skills, tools, schedule. Fields the assistant guessed are marked as guesses. If something blocking is unknown it asks with up to 3 **Question** cards, each with a recommended default. Every card has buttons and a free-text box; typing "only weekdays, and not before 8" revises the draft in place. Save (button, or a typed "yes") creates it and shows a **Created** card: Try it now · Open in Studio · Undo.

**Independent Test**: from a fresh chat, ask for an agent, answer one question by typing, save by typing "yes". The agent appears in Studio with version 1, source "chat"; Undo removes it (a new version, deleted).

**Acceptance Scenarios**:

1. **Given** a build request, **When** the assistant replies, **Then** the reply contains a Draft preview card before any question, and nothing is written to the store.
2. **Given** a draft with no blocking unknowns, **When** it is shown, **Then** no Question card is raised.
3. **Given** a Question card, **When** the person types text instead of pressing a button, **Then** the text revises the draft and the card is answered; a new Draft preview shows the change.
4. **Given** a draft whose only pending changes are content (no tools that need a grant, no new connection), **When** the person types a clear "yes", **Then** it saves exactly as a Save press would.
5. **Given** a request for an MCP server ("build me a server for my bank's API"), **When** the assistant replies, **Then** it shows a "Build in MCP Studio" card that opens the MCP Suite with the request prefilled, and drafts nothing.

### User Story 2: Edit something that exists (Priority: P1)

"Make my standup agent shorter and stop it running on Fridays." The assistant reads the **live** config (agent and its schedule), and shows a **Diff** card: before/after per field, line diff for instructions. Apply saves it as a new version based on the version it read. If the thing changed in the meantime, Apply is refused and the card offers to rebase the diff.

**Independent Test**: edit an agent from chat; the diff card's "before" matches Studio; Apply creates version n+1 with source "chat"; edit it in Studio between draft and Apply and Apply is refused with the stale-write reason.

**Acceptance Scenarios**:

1. **Given** an edit request, **When** the diff is built, **Then** "before" is read from the store at that moment, never from the chat history or the model's memory.
2. **Given** a vague edit ("make it better"), **When** the assistant replies, **Then** it raises a Question card whose options are drawn from the real config (its actual fields, skills, tools, schedules), with a recommended one, and no diff yet.
3. **Given** an applied edit, **When** the Saved card's Undo is pressed, **Then** the previous version is restored as a new version, and grants are kept as they are (006 rule).

### User Story 3: Permissions and connections need a button (Priority: P1)

The draft needs a tool from an app that is not connected, and a standing grant. The assistant shows a **Permission** card (each grant and each tool-access widening as an unticked checkbox, with what it allows in plain words and its tier) and a **Connect** card (OAuth inline, through the existing connector flow). Typed "yes" saves the content changes only; the permission and connection parts stay pending until their own buttons are pressed.

**Acceptance Scenarios**:

1. **Given** a Permission card, **When** it renders, **Then** no box is ticked.
2. **Given** a draft with a grant pending, **When** the person types "yes", **Then** the content saves, the grant does not, and the reply says the grant is still waiting on its button.
3. **Given** a Connect card, **When** OAuth completes, **Then** the card shows the account as Connected and the draft's tool for it becomes selectable; the tool is still not granted until the Permission card's button.

### User Story 4: Automations from chat (Priority: P2; 005 US5)

"Every weekday at 9, brief me on the beta." The Draft preview states the schedule in words and in the rule's own form, what it will do and where it is delivered (005 FR-060). Save writes through the automations store and the new versioned kind. A request the engine cannot express is refused with the reason, never approximated (005 FR-062). It runs at most once per scheduled time (005 FR-063).

### User Story 5: Building mode is visible and easy to leave (Priority: P2)

When a turn starts or continues a build, the chip **Building: <name>** sits above the chat bar. While it is present, follow-up messages revise that draft. × drops it: the draft is discarded (nothing was saved), and later messages are ordinary chat. A saved build keeps the chip until × or a new topic.

### Edge Cases

- Two builds in one chat: one chip at a time; starting a second asks (Question card) whether to drop the first draft.
- The person edits the same object in Studio while a chat draft is open: Apply is refused as stale; the card offers "Rebuild the diff on the current version".
- A draft references a skill or tool that does not exist: dropped from the draft and named, as Draft does today.
- The chat is a custom agent's chat and the request is to change that agent: handled by the assistant's builder, not by the agent (FR-031).
- A Question card times out: the safest default applies to the draft only; nothing saves (FR-012).

## Requirements *(mandatory)*

### Builder mode

- **FR-001**: Every chat MUST be able to build and edit agents, custom skills and automations. MCP servers MUST NOT be built from chat; a request for one MUST produce a "Build in MCP Studio" card (opens the MCP Suite, request prefilled) and no draft.
- **FR-002**: Builder mode MUST be detected from the request, in any chat, without a command. It starts when the assistant calls a builder tool; the server then emits the chip event. Keyword matching alone MUST NOT start it.
- **FR-003**: While a build is active the chat MUST show "Building: <name>" above the chat bar; × MUST drop the draft and leave builder mode with nothing written.
- **FR-004**: At most one build is active per chat.

### Drafting and questions

- **FR-005**: A build request MUST produce a Draft preview in the first reply, before any question. Guessed fields MUST be marked.
- **FR-006**: The assistant MAY then ask questions, only for information that blocks a valid save or changes behaviour materially, as at most 3 Question cards per build (a 4th only when a required field is still unknown). Each MUST mark one option as recommended.
- **FR-007**: Questions MUST use the shared Question card (see "Requirements on the shared Question card").
- **FR-008**: A vague edit MUST be answered with a Question card whose options are built from the live config of the target, not invented.
- **FR-009**: Free text typed in any builder card's box, or as the next chat message while the chip is present, MUST revise the current draft and produce an updated Draft preview or Diff card.
- **FR-010**: Drafts MUST NOT be written to the config store. A draft lives in the thread until saved or dropped.

### Cards

- **FR-011**: Six builder cards MUST exist: Question (shared), Draft preview, Diff, Permission, Connect, Created/Saved. Every card MUST have its buttons plus a free-text box.
- **FR-012**: Cards MUST use the Graphite tokens only (006 `tokens.md`), render in both themes, and pass WCAG AA in the contrast suite.
- **FR-013**: Created/Saved MUST offer Try it now (a new chat with the agent; a skill's Test; an automation's test run delivered to this chat only), Open in Studio, and Undo.
- **FR-014**: Text from the model or from content shown on any card MUST go through the display sanitiser (005 Amendment 1).

### Saving

- **FR-015**: Create and edit MUST save only on the Save/Apply button, or a clear typed "yes" from the owner's tagged turn while exactly one save-ready card is open. "Clear yes" is a server-side match on a short closed list (yes, y, save, apply, do it, go ahead), whole message, case and trailing punctuation ignored; anything else revises (FR-009). The model's reading of the message MUST NOT decide it.
- **FR-016**: Grants, tool-access widening and new app connections MUST save only by their own button. A typed message of any content MUST NOT save them.
- **FR-017**: Every save MUST go through the versioned store with the base version the card was built on; a stale base MUST be refused (no silent overwrite).
- **FR-018**: Every save MUST record source "chat", the thread and the card id, and MUST be disclosed once on the turn's final reply (009 FR-063).

### Editing

- **FR-019**: An edit MUST read the live config at diff time and show a Diff card (field-level; line-level for instructions and skill files; long diffs collapsed). Apply saves; Dismiss writes nothing.
- **FR-020**: Undo on a Saved card MUST restore the previous version as a new version; for a create, Undo writes a deleted version (and disables any schedule it created). Undo MUST keep grants as they are.

### One config store

- **FR-021**: Automations MUST become a third kind ("automation") in `config_versions`: one history per rule id, snapshot = the rule, materialised through `automations_store` (same validation, atomic write, stale-edit refusal).
- **FR-022**: Studio (agent Schedule tab), the Automations page and the chat builder MUST write automations only through that store. The existing gate test that all config writes go through versions MUST cover the rules file.
- **FR-023**: Migration MUST be lazy and additive: the first versioned write to the rules file records each existing rule as a baseline version (source "existing"), as agents and skills already do. A hand edit of the rules file detected by its hash MUST be recorded as a new baseline before the next write.
- **FR-024**: `setup_agent`, `update_agent` and `skill_manage` MUST be replaced on the model's tool surface by the builder tools; their write paths are kept only behind the builder's save.

### Automations (005 Slice 5, folded in)

- **FR-025**: 005 FR-060 to FR-064 apply unchanged, with the Draft preview as the proposal card and the builder's save as the confirm.

### Security and provenance

- **FR-026**: Builder actions MUST be tiered: draft, read live config, diff = Tier 1 (no side effect); create/edit save = Tier 3 (card button, or the typed yes of FR-015); grants, tool-access widening, connections = Tier 3, button-only (FR-016).
- **FR-027**: A builder save MUST originate from the owner's server-tagged user turn (`lineage.is_user_turn`) with no untrusted content in that turn before the proposal. Otherwise the card is a **suggestion**: marked with what content it came from, saved only by button, never by typed text.
- **FR-028**: Grant and tool checkboxes MUST never be pre-ticked, whether the draft came from the person, the model or content.
- **FR-029**: Builder tools MUST NOT be available in scheduled runs, delegated subagents, @-called agents or code-mode scripts. A resume run (009 FR-058) MAY continue a build but MUST NOT answer any builder card (009 US 0.5).
- **FR-030**: No agent MAY propose, save or grant a change whose target is itself or any agent in its call chain (inviter, delegator, or the lead that invited it), by any path.
- **FR-031**: In a custom agent's own chat, a request to change that agent MUST be handled by the assistant's builder (the write is the owner's click, recorded as `who=owner`), never by the agent's own tools.

### Key Entities

- **Draft**: thread-scoped proposed snapshot of one agent/skill/automation, with its base version (edits) and guessed-field marks. Never in the store.
- **Builder card**: a pending card (existing confirmations store) of one of the six types, carrying draft id, base version, origin (user turn or suggestion) and button-only parts.
- **Automation version**: a `config_versions` record of kind "automation".

## Requirements on the shared Question card

Specified and built by 009 Slice 1b in `specs/009-orchestration/question-card.md`. 010 needs from it:

1. Buttons for each option **plus** a free-text box on every card.
2. One option marked as the recommended default.
3. Only the owner's button press or the owner's server-tagged message answers it; tool output, a resume run, a subagent or a scheduled run cannot.
4. A timeout, after which the card states which (safest) default was applied; for 010 that changes the draft only and never saves.
5. A hook so typed text is delivered to the caller (the builder) as a revision, not only as a choice.

## Security

| Action | Tier / how it saves | Provenance rule | Sabotage check (test must fail when the guard is removed) |
|---|---|---|---|
| Draft, read live config, diff | Tier 1, no side effect | any turn | Make the draft tool call the store's write; the gate test on builder tools (no write reachable) fails. |
| Create / edit save | Tier 3: button, or typed yes (FR-015) | owner's tagged turn, no untrusted content earlier in the turn | Treat a tool result containing "yes" as the owner's turn; the save must not happen and the test fails if it does. |
| Grant / tool-access widening | Tier 3, button only | as above, plus never pre-ticked | Accept typed confirmation on a Permission card; test expecting "still pending" fails. Pre-tick one box; render test fails. |
| New app connection | button only (OAuth) | as above | Start OAuth from a typed "yes"; test fails. |
| Undo / restore | button on Saved card, versions API | owner | Undo that rewrites a version in place, or drops a grant; version-history test fails. |
| Self-edit / self-grant | refused | any turn, any path | Remove the call-chain check; a test where an @-called agent and a delegated subagent each propose an edit to themselves and to their inviter fails. |

**What a prompt-injected page or email can cause**: at most a suggestion card, labelled with its source, that the owner can dismiss. **What it cannot cause**: a save by typed yes, any save without a button, a grant, a connection, a pre-ticked box, an edit to the running agent or its chain, a builder action in a scheduled or delegated run, an MCP server. Each "cannot" has a test in the sabotage table above or in the plan's attack tests.

## Success Criteria *(mandatory)*

- **SC-001**: From a fresh chat on the live stack, create one agent, one skill and one automation, each in ≤ 3 cards after the first draft, each visible and undoable in Studio.
- **SC-002**: An edit's diff "before" matches Studio in 5 of 5 dogfood runs.
- **SC-003**: Every sabotage check in the Security table fails when its guard is removed (observed in the PR).
- **SC-004**: All builder cards pass the AA contrast suite in both themes.

## Out of scope

MCP servers (MCP Suite only); editing installed (non-custom) skills (offer "Copy as custom skill"); building workflows; bulk edits across many objects; voice; channels (Telegram/Slack) render cards as links back to the web chat.

## Open questions (decided defaults)

| # | Question | Decided default |
|---|---|---|
| Q1 | How many questions? | 3 per build; a 4th only for a still-unknown required field. |
| Q2 | What is a clear typed "yes"? | Closed list in FR-015, whole message, matched server-side; anything else revises. |
| Q3 | How is builder mode detected? | The assistant's builder tool call (FR-002); a false start costs one ×. |
| Q4 | Question card timeout | 24 h; the recommended default (or, for anything that widens access, "no") applies to the draft; never saves. |
| Q5 | Self-edit in an agent's own chat | Routed to the assistant's builder; the agent never holds builder tools (FR-031). |
| Q6 | Automations in the store | Per-rule versions in `config_versions`; rules file stays the runtime source (FR-021). |
| Q7 | Installed skills | Not editable from chat; offer a custom copy. |
| Q8 | Undo window | No time limit; undo is always a new version. |
| Q9 | Try it now for automations | A test run delivered to the current chat only, never to channels; it is itself subject to the run's policy. |
| Q10 | Old tools (`setup_agent`, `update_agent`, `skill_manage`) | Off the model surface; write paths reachable only from the builder's save. |
