# Feature Specification: Workspace Studio

**Feature Branch**: `006-workspace-studio` (Phase 1 docs on `006-p1-docs`)

**Created**: 2026-10-19

**Status**: Draft

**Input**: User description: the 006 brief (Graphite design: light and dark themes, app shell with a floating capsule and ⌘K, a new chat bar, multi-agent chat, Agent and Skill Studio, Tasks and Automations panels, MCP Suite and Settings). Design reference: [design/](design/) (10 screens plus an unused Direction B). Per-screen copy, values and every place a mockup disagrees with our data or rules: [design-notes.md](design-notes.md).

**Roadmap phase (Article IX)**: a UI feature over existing machinery. Each phase below ships alone and leaves the app usable.

## Order of work with Feature 005

| Step | What | Why here |
|---|---|---|
| A | **006 Phase 1**: themes, shell, capsule, ⌘K, chat bar | Every later screen is built on these tokens and this shell. |
| B | **005 Slice 3: Home**, built to Main.dc.html | Replaces 005's "Today". Inbox is removed in A; Home is where its items go. |
| C | **006 Phases 2 to 5** | Multi-agent chat, Studio panels, Tasks and Automations panels, MCP Suite and Settings. |
| D | **005 Slices 4 to 6**, with US6 in Slice 5 | Evidence, automations from chat (and ledger-aware triggers), drift and hooks. |

This supersedes 005's "Decision: where Today lives" and its FR-045 sidebar order. The sidebar is now New chat · Chats · MCP Suite, then Recent chats. Projects, Agents, Automations and Tasks are reached from the capsule and ⌘K. **New chat is Home.** Its badge is the count the Inbox badge shows today.

Between A and B, Home is an interim page. It shows the greeting, a **Waiting on you** list (pending approvals, plus alerts that are waiting or were missed, both from Inbox's current sources) and the chat bar. Nothing Inbox shows today is lost in the gap.

## User Scenarios & Testing *(mandatory)*

### Phase 1: Foundation

#### User Story 1: Light and dark themes (Priority: P1)

The user opens the app at night and it is dark, because their system is dark. In Settings → Appearance they pick Light, and the choice follows them to another browser after they sign in.

**Why this priority**: every other screen is drawn with these tokens.

**Independent Test**: switch the theme on each page and run the contrast check in both themes. Sign in from a clean browser and the saved theme loads.

**Acceptance Scenarios**:

1. **Given** no saved choice, **When** the app loads, **Then** it follows the system preference.
2. **Given** the user picks Light, Dark or System, **When** they sign in from another browser, **Then** the same choice applies. It is stored on the server.
3. **Given** any page in either theme, **When** the contrast check runs, **Then** every text and background pair meets WCAG AA.
4. **Given** the server cannot be reached, **When** the user changes the theme, **Then** it applies locally and the page says the choice was not saved.

#### User Story 2: App shell, capsule and ⌘K (Priority: P1)

The user sees a short sidebar. New chat shows "2", the number of things waiting on them, and MCP Suite shows "1", one failing source. A pill at the top centre reads Agents · Skills · Automations · Tasks · ⌘K. Clicking Tasks opens a large sheet over the chat. Its URL can be copied and shared, and closing it returns them to the same scroll position. ⌘K finds a project by name, or runs "Turn on dark theme".

**Independent Test**: on every page, open and close each panel, by mouse and by keyboard. Check the URL, focus return and timing. `/workspace/inbox` redirects to Home.

**Acceptance Scenarios**:

1. **Given** any page, **When** a capsule item is chosen, **Then** its panel opens as a dialog over the page in under 150 ms, and the URL names the panel.
2. **Given** an open panel, **When** Esc is pressed or the panel is closed, **Then** focus returns to the control that opened it, and the page underneath is unchanged.
3. **Given** a copied panel URL, **When** it is opened fresh, **Then** that panel is open over the page the URL names.
4. **Given** any page, **When** ⌘K is pressed, or "/" is pressed outside a text field, **Then** the palette opens. It searches chats, projects, tasks, agents, skills and automations, and runs actions.
5. **Given** the waiting count cannot be read, **When** the sidebar renders, **Then** the New chat badge says it cannot tell. It is not "0" and it is not hidden.
6. **Given** a bookmark to `/workspace/inbox`, **When** it is opened, **Then** Home opens.

#### User Story 3: The chat bar (Priority: P1)

In a chat, the user sees chips for the project, the agents in the chat, the integrations (as a stack of logos), the skills and the files. Each chip can be removed. "+" opens a picker with Projects, Agents, Integrations, Skills and Files tabs. Under Integrations, Gmail shows its logo, a status and a switch for "use in this chat". Slack reads "Not connected" and links to MCP Suite. Below the text field are Attach, Mode, Reasoning effort (only when the model supports it), Model and Send.

**Independent Test**: on Home and in a chat, toggle an integration for the chat, reload, and see the same selection. Check that the agent sees the same tools. Then check that everything the current input box does still works.

**Acceptance Scenarios**:

1. **Given** a connected integration, **When** its switch is turned on in the picker, **Then** this chat's tool selection includes it, and the logo appears in the Integrations chip.
2. **Given** a source that is unreachable or not connected, **When** the picker shows it, **Then** it has no switch. It has a link to MCP Suite, and an unreachable source shows its real error.
3. **Given** a model without reasoning-effort support, **When** the bar renders, **Then** the effort control is absent.
4. **Given** "@" is typed, **When** the agent list opens, **Then** it can be used with the arrow keys, Enter and Esc. **Given** "/" is typed at the start of the message, **Then** the command list opens.
5. **Given** the current input box's features (stop while streaming, attachments with previews, follow-up suggestions and the append-or-replace prompt, welcome suggestions, the tool count against the model's cap, the mode guide), **When** the new bar ships, **Then** each still works.

### Phase 2: Multi-agent chat

#### User Story 4: Several agents in one chat (Priority: P2)

The user types "@Researcher how do other tools link Codex subagents?" Researcher answers in the thread, under its own name and avatar, using its own instructions, tools, skills and permissions. Then "@Release manager" joins and answers too. The lead agent answers anything that is not addressed to an agent. The header and the chip list the participants, and removing one stops its replies.

**Acceptance Scenarios**:

1. **Given** two agents with different tools, **When** each is called, **Then** each uses only the tools that both it and the chat allow.
2. **Given** an agent is removed, **When** its name is typed, **Then** it does not reply.
3. **Given** "@unknown", **When** the message is sent, **Then** nothing breaks and the lead agent replies.
4. **Given** a called-in agent proposes a Tier 3 action, **When** the action is proposed, **Then** it shows on the same approval card with the same rules.

### Phase 3: Agent and Skill Studio

#### User Story 5: Agents panel (Priority: P3)

The panel has tabs: Overview, Instructions, Tools and skills, Autonomy, Schedule. On a large field the user types one sentence and presses Draft. The field fills in, and nothing is saved until they press Save. Building an agent by chatting still works, as a secondary path. Projects can be attached to an agent.

**Autonomy**: in scheduled runs, an agent may take the reversible actions the user has ticked:
- create and update tasks;
- add notes and decisions;
- archive stale tasks;
- draft messages, without sending them.

Irreversible actions always wait, and appear in Home → Waiting on you.

**Tiers decide first; Tier 3 always asks (review round 2, 2026-10-20; recorded as Amendment 1 to 005 FR-009, specs/005-project-ledger/spec.md v1.1: in chat a routine write runs and is disclosed with Undo only when it follows from the user's own message; one caused by content is a suggestion card).** The grantable ops are Tier 2 (run, then disclose): creating or updating a task (dropping one included) and adding a note. A grant never skips a confirmation. It only changes how those grant-governed Tier 2 calls behave in a scheduled run: there, one runs only when a granted class covers every change in it and the run's cap has room; otherwise it waits on Home → Waiting on you. In chat a grant changes nothing (Tier 2 runs and the reply says so). Everything Tier 3 (a new project or goal, linking a chat, anything irreversible or unclassified) asks every time, in chat and in scheduled runs, grant or not. Undo restores an agent's content only; its grants change only through the Autonomy tab's own Save.

**Acceptance Scenarios**:

1. **Given** a standing grant, **When** the same action is proposed in a chat run, **Then** the grant does not apply: it runs as Tier 2 and the reply discloses it.
2. **Given** a grant, **When** a tool classified as irreversible, or any Tier 3 call, is made in a scheduled run, **Then** the grant never covers it and it asks.
3. **Given** a grant is revoked, **When** the next call is made, **Then** the grant no longer applies.
4. **Given** a grant is used, **When** the audit log is read, **Then** that use is recorded. The grant is visible on Overview.
5. **Given** Draft is pressed, **When** the draft returns, **Then** nothing is saved until Save.

#### User Story 6: Skills panel (Priority: P3)

The panel has tabs: Details, Instructions, Files, Test. Test runs a message through the same selection that runtime uses, and says whether the skill was picked.

**Acceptance Scenarios**:

1. **Given** a test message, **When** Test runs, **Then** the result comes from the runtime's own selection path. It is checked against real runs.

### Phase 4: Tasks and Automations panels

#### User Story 7: Tasks panel (Priority: P4)

Projects are listed on the left, including a Personal project and All open tasks. Each project shows its goal and progress. Quick add has a Break down button: the agent proposes tasks and the user confirms them. Tasks are grouped into In progress, To do and Done this week. Each task shows its owner (a provider logo or an agent avatar) and an evidence line that says observed or reported. The data comes from the 005 ledger; there is no second store.

#### User Story 8: Automations panel (Priority: P4)

The panel lists automations with an on/off switch, and agent schedules too. Each has History and Edit tabs. History says what happened in words:
- delivered;
- held, then delivered, and why;
- delivered together with another;
- failed, and why;
- not retried.

It also provides the create-from-chat hook that 005 Slice 5 uses.

### Phase 5: App pages

#### User Story 9: MCP Suite and Settings (Priority: P5)

**Connected tab**:
- counts of live, unreachable and not connected sources;
- a failing source with its real reason, View log and Retry;
- app cards with logo, purpose, status and an "On in new chats" switch. That switch sets the default selection for new chats, which fixes "connected but not selected";
- category filters and search;
- MCP servers with transport, tool count and status. Agent-built servers are marked.

**Build tab**:
- the user describes a tool in one sentence;
- an agent builds and tests it in a sandbox;
- the user approves its first run. The screen shows the build steps, the tests passed and the secrets used (never shown to the model), with Approve, Discard and View code.

**Settings**: Memory, Safety, Activity log, Notifications, Account, Appearance and About, all in the new layout.

### Edge Cases

- Panel URL for something that no longer exists (deleted agent): the panel opens and says it is gone; it does not show a blank sheet.
- Theme preference saved on the server conflicts with a local one after offline change: the most recent change wins and is saved.
- A logo with no official asset: monogram fallback with the source's name as its accessible name.
- Narrow widths: capsule collapses to an icon row; every target is at least 44 px; panels become full-screen sheets.
- A tool source that has never been loaded: its state is "can't tell yet", never Live and never Off.

## Requirements *(mandatory)*

### Global (every phase)

- **FR-001** Themes: one set of semantic tokens, each with a light and a dark value (token table in the brief and in design-notes.md). No component hardcodes a colour.
- **FR-002** The theme defaults to the system preference. Settings → Appearance offers Light, Dark and System. The choice is stored per user on the server, with a local copy so the first paint is right.
- **FR-003** Every text and background pair passes WCAG AA in both themes. The contrast test covers every page and panel, new and existing, in BOTH themes. The hardcoded-colour test covers every component directory, including new ones.
- **FR-004** Type and shape:
  - Inter at weights 400, 500 and 600, with JetBrains Mono for ids, paths and code;
  - radii of 8, 10 and 14 px (pills and avatars fully round);
  - at most one solid primary button per screen; every other button is outline or ghost.
- **FR-005** Logos: one icon registry for every brand mark.
  - Provider marks (Anthropic for Claude Code sessions, OpenAI for Codex sessions) replace the text labels wherever a session or its owner appears.
  - Connector logos appear in the picker, the chat bar chips, MCP Suite and agent Tools.
  - Assets are OFFICIAL only and follow each brand's guidelines. An unknown source gets a monogram.
  - Each asset's source and licence is recorded in THIRD-PARTY-NOTICES.md.
  - Every logo has an accessible name.
- **FR-006** Accessibility:
  - capsule panels are dialogs: they trap focus, close on Esc and return focus;
  - tabs are real tablists, with arrow-key support;
  - ⌘K, and "/" outside a text field, work from anywhere;
  - the "@" and "/" menus work from the keyboard;
  - touch targets are at least 44 px at narrow widths.
- **FR-007** Performance, measured on the production build:
  - each page is usable in under 1 s;
  - a capsule panel opens in under 150 ms;
  - panels are lazy-loaded;
  - non-chat pages take on no new heavy library, enforced by the bundle test.
- **FR-008** Honesty (004 rules):
  - empty and can't-tell are never collapsed into one state;
  - text that fails redaction reads "Withheld";
  - observed, reported and inferred are said in words;
  - failing sources are visible.
  
  Where a mockup's copy breaks one of these rules, the rule wins (design-notes.md, "Disagreements").
- **FR-009** Engineering:
  - the wiring gate applies from day one;
  - each phase has at least one integration test through the production composition root (`create_app()` with its lifespan);
  - every new guard is sabotaged once;
  - every new screen has a rendering spec;
  - each phase ships as one PR, with CI green, measured speed, and screenshots in both themes.
- **FR-010** i18n: every new string exists in both shipped locales (en-US, zh-CN).

### Phase 1

- **FR-101** Tokens are applied, and every existing page is migrated to them and checked in both themes.
- **FR-102** The theme preference is readable and writable through the gateway for the signed-in user. The Appearance page uses it.
- **FR-103** Sidebar:
  - New chat (Home), with a badge showing the waiting count, or can't-tell when that count cannot be read;
  - Chats;
  - MCP Suite, with a badge showing the failing-source count;
  - a divider, then Recent chats;
  - a footer with the avatar and a More menu (Settings, Memory, Safety, Activity log, Appearance, About).
- **FR-104** Inbox is removed, and `/workspace/inbox` redirects to Home. The interim Home shows the greeting, Waiting on you (pending approvals plus waiting or missed alerts) and the chat bar. Its count equals the badge.
- **FR-105** Agents, Automations and Tasks leave the sidebar. Every route that exists today stays reachable, through the capsule, ⌘K or More.
- **FR-106** Capsule: a floating pill at the top centre of every page, reading Agents · Skills · Automations · Tasks · ⌘K.
  - Each item opens its panel as a large sheet over the page.
  - The URL names the open panel. Closing it restores the page and its scroll position.
  - In Phase 1, each panel hosts the existing page for that area. Phases 3 and 4 replace them.
- **FR-107** ⌘K palette:
  - search over chats, projects, tasks, agents, skills and automations;
  - actions, including New agent, Connect *app*, and Turn on dark / light theme;
  - navigation to every existing page.
- **FR-108** Chat bar on Home and in every chat:
  - removable context chips;
  - a "+" picker with Projects, Agents, Integrations, Skills and Files tabs;
  - Attach, Mode (Flash, Reasoning, Pro, Ultra), Reasoning effort (minimal, low, medium or high, shown only when the model supports it), Model and Send;
  - "@" opens the agent menu and "/" opens the command menu.
- **FR-109** The Integrations tab IS the existing per-thread tool selection, made visible. It shows each source's logo, its status and a per-chat switch. Status words follow design-notes.md §Status vocabulary, mapped from the gateway's tool-source states. Unreachable and not-connected rows link to MCP Suite.
- **FR-110** Nothing the current input box does is lost (US3 scenario 5).
- **FR-111** The logo registry is in place, with the THIRD-PARTY-NOTICES entries, including the 8 connector assets already in the repo.
- **FR-112** Screenshots are taken of every existing page, the shell, the capsule (closed and open) and the chat bar, in light AND dark.

### Phases 2 to 5

- **FR-201** Multi-agent: participants are stored per thread, and the lead agent is the default. "@Name" runs that agent with the thread's context. Its effective tools are the intersection of the chat's selection and the agent's own. Replies are labelled with the agent's name and avatar. Tier 3 actions use the same card and the same policy.
- **FR-301** Agent fields: display name, avatar, projects, schedule, autonomy. "Draft from one sentence" has one backend endpoint per field type. It returns text and never saves.
- **FR-302** Standing grants live in the 003 policy layer. Each is scoped to one agent, one action class and scheduled runs only. Each use is audited. A grant is revocable, effective from the next call, and never covers an irreversible action class. A grant only ever covers a reversible Tier 2 call; Tier 3 always asks (review round 2). The per-run cap counts ACTIONS, not calls (a ledger_apply with N changes is N), is reserved atomically before the call runs, and is stored durably per firing, so a retry of the same firing continues its count. Undo never changes grants.
- **FR-303** Skill Test calls the runtime's own skill-selection path, never a copy of it.
- **FR-310** (006-F) A trigger rule may name a custom agent (`agent`). Its firing runs AS that agent: the agent's instructions, tool groups, skills and model, through the same agent factory chat uses. A rule without `agent` runs as the lead agent, as before.
- **FR-311** (006-F) A firing as an agent uses that agent's own standing grants only (FR-302): never the lead's, never another agent's. An agent with no grants waits for every grant-governed write. Tier 3 always waits as a card; granted writes keep their source labels and Undo all per firing.
- **FR-312** (006-F) A rule naming an agent that does not exist is refused when written (with the reason), never fires, and is never run as the lead in its place: the engine settles such a firing as failed with that reason, and the gateway refuses the run. Deleting an agent disables its rules.
- **FR-313** (006-F) A firing as an agent is a scheduled, non-person run: its provenance comes only from the engine's single-use grant, it can never confirm or decline a card, and content it reads cannot change its agent or its grants.
- **FR-314** (006-F) The owner can create, edit and delete an agent's schedules from Studio: cron (presets or custom) and an IANA time zone, both validated; quiet hours are the engine's. The rule file stays the engine's source of truth, and a change takes effect without a restart.
- **FR-315** (006-F) Each schedule has two delivery toggles: send the result to Telegram (the existing channel delivery) and show it on Home. Quiet hours, mid-exchange holding and coalescing apply to agent firings exactly as to every firing (Article VII).
- **FR-316** (006-F) Studio's Next run and Recent runs for an agent come from that agent's own rules and firings; the Automations panel says which agent each automation runs as; a drafted schedule becomes a real one only when the person presses its button.
- **FR-401** The Tasks panel reads and writes the 005 ledger only. Break down is proposed by the agent and confirmed by the user through the existing confirmation path.
- **FR-402** Automations History states each firing's outcome in words, with the engine's recorded reason verbatim.
- **FR-501** "On in new chats" is a per-user default selection, applied when a thread is created.
- **FR-502** The Settings sections are re-laid out. The Tools and Skills sections move to MCP Suite and the Skills panel, and their old URLs redirect.

### Key Entities

- **Theme preference**: per user; one of light, dark or system.
- **Default tool selection** (P5): per user; the source ids applied to new threads.
- **Thread participants** (P2): per thread; agent names, with one lead.
- **Standing grant** (P3): agent, action class, scope (scheduled runs), created and revoked times, and an audit trail.

## Success Criteria *(mandatory)*

- **SC-001** In both themes, the contrast check finds 0 failures on every page and every panel.
- **SC-002** The hardcoded-colour test finds 0 new literals. Each sabotage fails it.
- **SC-003** On the production build, measured headless: every page is usable in under 1 s, and a capsule panel opens in under 150 ms (median of 5).
- **SC-004** The bundle test passes. No non-chat page carries a heavy-library marker.
- **SC-005** A theme saved in one browser applies in a fresh browser after sign-in.
- **SC-006** Toggling an integration in the picker changes what the agent receives on the next run, verified through `create_app()`.
- **SC-007** Every feature of the current input box has a passing rendering check against the new bar.
- **SC-008** Phase 2: two agents in one chat each call only their own permitted tools (integration test).
- **SC-009** Phase 3: each of the three standing-grant sabotages fails its test.

## Assumptions

- The mockups are references. Their sample data (names, counts, chats) is illustrative.
- Direction B (Home-B.dc.html) was not chosen. Its light colours do not override the token table.
- Panels in Phase 1 host existing screens. Their redesign is Phases 3 and 4.
- 005 Slice 3 delivers Home's full content (projects, coding sessions, upcoming, what moved). Phase 1 only lays the ground.

## Run history: storage rules and accepted limits

The run history (Automations history, 007 replay) keeps each automation run's full content locally. Rules:

- **Encrypted at rest.** Each run's content is sealed with its own data key. The data keys are kept, wrapped by a master key, in a key store beside the master key file, outside the run database, the project, the data dir and every agent sandbox mount (`~/.omni-harness-secrets/run-store/`, its own subdirectory, 0700; files 0600). Deleting or expiring a run destroys its data key. "Delete run history", and a purge that empties the store, also rotate the master key.
- **Backups.** No backup routine and no agent ever copies the key store or the master key file into the same backup as the run database.
- **Retention covers the automations' conversations.** A live automation whose conversation holds content older than the retention starts a fresh conversation (it forgets earlier runs). A conversation the person wrote in within the retention is kept, trimmed to the retention.

Accepted known limits:

- **Cross-worker busy detection.** With several gateway workers, a person chatting in an automation's conversation on another worker is not seen as busy by "Delete run history". The only guard is the check after the delete: a conversation written during its delete is reported as not deleted and retried. Engine firings on any worker are covered by a cross-process lock.
- **Old backups.** A backup that holds both an old copy of the run database and an old copy of the key store can still open a deleted run, until the master key is next rotated (delete-all, or a purge that empties the store). Hence the backup rule above.
- **Disk blocks.** Overwriting a file does not erase its old blocks on a copy-on-write or wear-levelled disk. Rotation, not overwriting, is the control.

## Clarifications

### Session 2026-10-20 (the user's answers to the open questions)

1. **Integration status, two stages**: "Connected" until a tool call from that source has succeeded, then "Live · last worked <time>". A source never checked stays "Not checked yet".
2. **Display name**: optional, set in Account. When unset it falls back to the part of the email before "@". The user is asked once, on their first Home visit.
3. **"Reported" everywhere**: 005's UI wording changes from "claimed" to "reported". Internal enum names may stay.
4. **Projects** are reached through the Tasks panel, the chat-bar Project chip, the Home block and ⌘K. A project view keeps its own linkable URL.
5. **Reversible/irreversible label**: each tool carries one, separate from its tier. Standing grants only ever cover reversible actions, and a sabotage proves an irreversible tool cannot be granted. Revised in review round 2: the grantable ledger ops are Tier 2, not Tier 3, so a grant never skips a confirmation.
6. **Skill Test**:
   - runs only on a button press;
   - uses the same model the runtime would;
   - makes a small number of tries;
   - reports what it observed ("loaded 2 of 3") and names the model.
7. **Removing a skill per chat**: yes, in Phase 3. Until then the Skills chip is read-only.
8. **The Phase 1 "@" behaviour** is accepted.
9. **Logos**: all eight existing app logos are replaced with official assets. A monogram is used only where a brand's terms forbid the use, and those brands are listed.
10. **Inbox removal**: items waiting go to Home → "Waiting on you"; alerts missed while away go to a dismissable Home block, "While you were away"; delivery history goes to Settings → Activity log.

11. **Standing grants and content origin (Phase 3)**:
    - Standing grants, which only ever cover reversible actions, DO apply in scheduled runs even when the run's origin is "derived from content".
    - They are capped per run: at most 20 granted reversible actions by default, counted per action (one ledger_apply with N changes is N), reserved before the call runs so parallel calls cannot overshoot, and kept per firing so a retry continues the count. Above that the run pauses and appears on Home → "Waiting on you".
    - Every granted action is listed in the run's history with its origin.
    - Required tests: the cap pauses the run at action 21, a content-derived scheduled run still uses its grant, and a chat run never does. Each has a sabotage.

The 33 resolutions in design-notes.md are accepted, including the solid-button and contrast fixes.

## Open Questions (answered 2026-10-20, see Clarifications)

1. **Connector status word.** For an authorised connector, the gateway knows only that Composio reports the connection ACTIVE. It has not seen a tool call succeed. The mockups say "Live", the word used for a local server that loaded. **Default: "Connected"** for connectors, and "Live" only for a source whose load was observed. Is that right, or should "Live" cover both?
2. **Your name.** The greeting ("Good evening, Rishabh") and the footer avatar need a name, but accounts store only an email. **Default:** add an optional display name in Settings → Account, stored with the theme preference. Until it is set, the greeting has no name and the avatar shows the email's first letter.
3. **"Reported" or "claimed".** 005 uses "claimed" for what an agent says about itself, while this brief and the mockups say "reported". **Default: "reported"** in all UI copy. 005's stored value keeps its name. Should 005's spec copy change to match?
4. **Projects leaving the sidebar.** 005 put Projects in the sidebar (FR-045), and this brief's sidebar has no Projects item. **Default:** projects are reached through the Tasks panel (projects on the left), ⌘K and Home's Projects block. Confirm that losing the sidebar entry is intended.
5. **Standing grants and `ledger_apply`.** "Create and update tasks" is done through `ledger_apply`, which is classified Tier 3 so that every assistant write is confirmed. A grant must cover it in scheduled runs, yet "never covers an irreversible tool". **Default:** add an action-class attribute (reversible or irreversible), separate from tier, to the tracked rules. Mark only the ledger create, update, note and archive classes, plus drafts, as reversible. Grants may cover only reversible classes. Agree?
6. **Skill Test is not deterministic.** At runtime, a skill is chosen by the model reading each skill's description in the lead prompt; no selection function exists. The mockup's "Loads" and "Doesn't load" imply a yes-or-no answer. **Default:** Test sends the message to the real model with the same skills section and reports what it observed per try (for example "picked in 3 of 3 tries"). Each try costs a model call. Acceptable?
7. **Skills chip per chat.** No per-thread skill selection exists. Skills are enabled globally, with a whitelist per agent. **Default:** in Phase 1 the chip shows, read-only, the skills this chat's agent may use. Removing a skill per chat waits for a per-thread skill allowlist in Phase 3. Is per-chat skill removal wanted at all?
8. **"@" before Phase 2.** Phase 1 ships the "@" menu, but calling in a second agent is Phase 2. **Default:** in a new chat, picking an agent starts the chat with that agent, using the existing agent-chat route. In an existing chat, the agents are listed but disabled, with the reason "Calling in another agent comes with multi-agent chat".
9. **Brand marks.** The 8 connector images already in `public/icons/integrations/` have no recorded source. Anthropic's and OpenAI's brand guidelines limit how their marks may be used. **Default:** replace each image with the brand's own press-kit asset, record it in THIRD-PARTY-NOTICES.md, and use the monogram wherever a brand's terms do not allow use in this app. Do you want any brand left as a monogram from the start?
10. **Where Inbox alerts go.** Inbox also lists the trigger engine's delivery attempts, not only what is waiting. **Default:** waiting and missed alerts appear in Home → Waiting on you, and the full alert history moves to Settings → Activity log. Agree?
