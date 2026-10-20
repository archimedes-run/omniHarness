---
description: "Task list for Feature 006, Workspace Studio"
---

# Tasks: Workspace Studio

**Input**: [spec.md](spec.md), [plan.md](plan.md), [design-notes.md](design-notes.md), and the mockups in [design/](design/).

**Tests**: required. Every phase has one integration test through `create_app()` and its lifespan. Every new guard is sabotaged once. Every new screen has a rendering spec in both themes.

**Done means**: production code calls it, it is tested, and its sabotage was seen to fail (with the sabotage text confirmed in the file and the summary line read).

## Order with Feature 005

The work runs **A → B → C → D**:
- **A**: Phase 1 below.
- **B**: 005 Slice 3, Home per Main.dc.html (005 T023–T027, re-targeted from "Today" to Home).
- **C**: Phases 2 to 5 below.
- **D**: 005 Slices 4 to 6, with US6 in Slice 5.

After Phase 1: **STOP** for review.

## Format: `[ID] [P?] [Area] Description`

- **[P]**: can run in parallel with the other [P] tasks of its block.

## Phase 1: Foundation

### 1a. Tokens and appearance

- [ ] T001 [P] [tokens] `frontend/src/styles/globals.css`: set the Graphite light and dark values on the existing tokens, mapped per design-notes §Tokens.
  - Add `--foreground-2`, `--border-strong`, `--primary-subtle`, `--overlay` and `--avatar-1..4` (each with `-foreground`), and expose them in `@theme inline`.
  - Set radii to 8, 10 and 14.
- [ ] T002 [P] [tokens] Fonts: Inter (400, 500, 600) and JetBrains Mono through `next/font/google` in `frontend/src/app/layout.tsx`, as `--font-sans` and `--font-mono`. Ids, paths and code use `font-mono`.
- [ ] T003 [tokens] Extend `tests/rendering/contrast.spec.ts` ROUTES to every existing page: workflows (list, detail, run), policy, triggers, tool-sources, confirmations, chats list, a chat thread, and settings notification, about, tools and skills. Run in both themes and fix every failure.
  - Sabotage: set `--muted-foreground` to the bg value in `.dark` only. The dark run must fail.
- [ ] T004 [tokens] Migrate the existing screens: sweep `components/workspace/**` and `app/workspace/**` for tokens used in the wrong role. `--accent` is the hover surface, and the brand accent is `--primary`. Every page must look right in both themes, checked in the T012 screenshots.
- [ ] T005 [P] [tokens] `tests/unit/colour-tokens.test.ts`: assert that the scan root includes `capsule/`, `chat-bar/`, `home/` and `brand/`.
  - Sabotage: add `#8FA8FF` to a new file in `chat-bar/`. The test must fail.
- [ ] T006 [appearance] Backend preferences:
  - `persistence/user_preferences/{model.py,sql.py}`;
  - migration `0015_user_preferences.py` (`user_id`, `theme`, `display_name`, `updated_at`);
  - `routers/preferences.py`, with `GET` and `PUT /api/me/preferences`, registered in `create_app()`.
- [ ] T007 [appearance] Integration test `backend/tests/preferences/test_preferences_api.py` through `create_app()` and its lifespan. The docstring names the difference it defends against (hand-built router vs the real app).
  - A PUT followed by a fresh-client GET returns the same value.
  - User B cannot see A's preference.
  - Unauthenticated requests get 401.
  - Sabotage: GET ignores the stored row. The test must fail.
- [ ] T008 [appearance] Frontend `core/preferences/{api.ts,hooks.ts}`, plus a `ThemeSync` component in `workspace-content.tsx`: on sign-in it applies the server theme, and on change it writes back.
  - `settings/appearance-settings-page.tsx` saves through the hook, and says "Not saved" when the PUT fails.
  - Extend `tests/rendering/theme.spec.ts`: the server value wins over the local one on sign-in, and a failed PUT is shown.
- [ ] T009 [P] [appearance] i18n: add the new strings to en-US and zh-CN.

### 1b. Shell, capsule, ⌘K and the Inbox removal

- [ ] T010 [shell] Sidebar in `workspace-nav-chat-list.tsx`:
  - New chat → `/workspace`, with the waiting badge (rename `useInboxCount` → `useWaitingCount` and keep `null` → "?");
  - Chats;
  - MCP Suite → `/workspace/connections`, with the `failing` badge and the accessible name "N tool source(s) failing";
  - a divider, then Recent chats.
  
  Remove the Inbox, Projects, Automations, Connections and Agents items. Update `tests/rendering/sidebar.spec.ts`.
- [ ] T011 [shell] Footer in `workspace-nav-menu.tsx`: the avatar (display name, or the email initial) and a More menu with Settings, Memory, Safety, Activity log, Appearance and About. The external links move under About.
- [ ] T012 [shell] Interim Home: `app/workspace/page.tsx` renders `components/workspace/home/interim-home.tsx` (keeping the static-demo branch), with:
  - the greeting and date (the name only when one is set);
  - **Waiting on you**: pending confirmations plus waiting and missed alerts. Its count equals the badge. It says "nothing waiting" when empty, and "can't tell" when either source fails;
  - the chat bar.
- [ ] T013 [shell] Remove Inbox: `app/workspace/inbox/page.tsx` → `redirect("/workspace")`. Rewrite `tests/rendering/inbox.spec.ts` as a redirect and Home spec.
  - Sabotage: return the old page. The spec must fail.
- [ ] T014 [shell] FR-105, reachability: a test that lists every `app/workspace/**/page.tsx` route and asserts each is reachable from the capsule, ⌘K or More (the list comes from the filesystem, not typed by hand).
  - Sabotage: drop the workflows entry from ⌘K. The test must fail.
- [ ] T015 [capsule] `components/workspace/capsule/{capsule.tsx,panel-sheet.tsx,use-panel-param.ts}`:
  - a fixed pill at the top centre, mounted in `workspace-content.tsx`;
  - `?panel=` in the URL;
  - a Radix Dialog (focus trap, Esc, focus return);
  - closing restores the page and its scroll position;
  - at narrow widths, the pill collapses to icons and every target is at least 44 px.
- [ ] T016 [capsule] Panel bodies through `next/dynamic`, prefetched on hover or focus. In Phase 1 they host the existing pages:
  - agent gallery
  - skills
  - automations list
  - projects list
  
  Each panel has a "gone" state for an id that is missing.
- [ ] T017 [capsule] `tests/rendering/shell.spec.ts`:
  - each panel opens by mouse and by keyboard;
  - the URL round-trips from a fresh load;
  - focus returns on close;
  - the scroll position is restored;
  - a panel opens in under 150 ms (median of 5, on the production build);
  - narrow-width targets are at least 44 px.
  
  Add each `?panel=` to the contrast ROUTES.
  - Sabotage: remove focus return. The spec must fail.
- [ ] T018 [⌘K] `command-palette.tsx`:
  - search over chats (`POST /api/threads/search`), projects and tasks (ledger), agents, skills and automations, queried only while the palette is open;
  - actions: New chat, New agent, Connect *app*, Turn on dark or light theme, and Go to every route;
  - opens on ⌘K or Ctrl-K, and on "/" outside editable elements.
  - Rendering spec, including that "/" typed in the chat bar does NOT open the palette.
- [ ] T019 [⌘K] Bundle: add `/workspace` (Home) and one `?panel=` URL to `bundle-budget.spec.ts`'s NON_CHAT list. The palette must not pull in `@langchain/core`.
  - Sabotage: import the LangGraph client in the palette. The spec must fail.

### 1c. Chat bar, picker and logos

- [ ] T020 [P] [logos] `core/brand/registry.ts` and `components/workspace/brand/logo.tsx`:
  - official assets in `public/brand/` (the providers `anthropic` and `openai`, plus the 8 connectors);
  - a monogram fallback;
  - an `alt`/`aria-label` on every logo.
  
  `tools/integration-icon.tsx` wraps it. Each asset is recorded in THIRD-PARTY-NOTICES.md (source URL, guideline, licence or terms; see Open Question 9).
- [ ] T021 [P] [logos] `tests/unit/logo-registry.test.ts`: every entry has a source, a licence and a tracked file, and an unknown id renders the monogram with a name.
  - Sabotage: delete one asset's notice line. The test must fail.
- [ ] T022 [logos] Provider marks replace the text labels wherever a session or its owner appears: `components/workspace/sessions/*`, ledger owner chips, and Home's Waiting on you. Extend `sessions.spec.ts`.
- [ ] T023 [P] [chat bar] `core/tool-sources/status.ts`: a pure mapping from state to word, tone, selectable and link, per the design-notes table. `status.test.ts` covers all nine cases.
  - Sabotage: map `not-loaded` → Live. The test must fail.
- [ ] T024 [chat bar] `components/workspace/chat-bar/chat-bar.tsx`: the new layout over `input-box.tsx`'s `PromptInput` core.
  - Bottom row: Attach, Mode (Flash, Reasoning, Pro, Ultra; `getResolvedMode` kept), Effort (only when `supports_reasoning_effort`), Model, and Send (the screen's one solid button).
  - Kept: stop, attachments, follow-ups and the append-or-replace prompt, welcome suggestions, and the mode guide.
- [ ] T025 [chat bar] `context-chips.tsx`:
  - Project (thread links), Agents (lead), Integrations (a logo stack), Skills (read-only, Open Question 7), Files;
  - each removable chip has a labelled ×.
- [ ] T026 [chat bar] `context-picker.tsx`: a dialog with a `Tabs` tablist (arrow keys) for Projects, Agents, Integrations, Skills and Files.
  - **Integrations**: the logo, the status word from T023, and a per-chat switch that PUTs `/api/threads/{id}/tools`. It shows count/cap and blocks going over the cap.
  - Unreachable and not-connected rows link to MCP Suite, and an unreachable row shows its error.
  - In a new chat, the selection is held until the thread exists.
- [ ] T027 [chat bar] `mention-menu.tsx` ("@", a listbox with arrows, Enter and Esc) and `command-menu.tsx` ("/" at the start of the message). Phase 1 behaviour follows Open Question 8: in an existing chat, other agents are disabled, with the reason shown.
- [ ] T028 [chat bar] Swap `InputBox` → `ChatBar` in `chats/chat-box.tsx` and on Home. Delete the dead code from `input-box.tsx` once nothing imports it, and check the wiring gate.
- [ ] T029 [chat bar] `tests/rendering/chat-bar.spec.ts`:
  - chips are removed;
  - the tablist works with arrow keys;
  - the switch PUT round-trips;
  - Effort is hidden for an unsupported model;
  - "@" and "/" are keyboard navigable;
  - every FR-110 behaviour still works;
  - contrast holds in both themes.
  - Sabotage: drop the stop button. The spec must fail.
- [ ] T030 [chat bar] Integration test (SC-006) through `create_app()`: a selection PUT for a thread changes the tool set the agent assembles for its next run (`get_available_tools` with that thread's sources).
  - Sabotage: the PUT writes to another thread id. The test must fail.

### 1d. Close Phase 1

- [ ] T031 `tests/rendering/screenshots.spec.ts`: every existing page, plus the shell, the capsule (closed and each panel open) and the chat bar (with the picker and the @ menu open), in light AND dark.
- [ ] T032 Measured speed on `pnpm build && next start`, headless: each page usable in under 1 s, and panel open in under 150 ms. Record the numbers in the PR.
- [ ] T033 Gates: backend lint plus the full suite (wiring gate included), and frontend `tsc`, lint, prettier, vitest and Playwright, all green. Then STOP.

## Phase 2: Multi-agent chat (outline)

- T201 Thread participants (`thread_meta`, `routers/thread_participants.py`), with the lead as default.
- T202 A mention parser on user turns only. A mention arriving in tool output is ignored (Article III test).
- T203 Run a called-in agent through the subagent executor, with its config, tools taken as the intersection, and `PolicyMiddleware`.
- T204 Labelled replies (name and avatar), plus participants in the header and chip, removable.
- T205 Tests through `create_app()`: two agents use only their own tools; removing one stops its replies; "@unknown" is harmless; Tier 3 goes through the same card.

## Phase 3: Agent and Skill Studio (outline)

- T301 Agent fields: display name, avatar, projects, schedule and autonomy. API and migration.
- T302 `routers/drafts.py`: one endpoint per field type. A gate test checks that it never writes.
- T303 Agents panel tabs per the mockup, with the design-notes resolutions #11 to #14 applied.
- T304 Standing grants in `app/policy/grants.py`, with an action-class attribute in the tracked rules. Each use is audited, and grants are revocable and visible on Overview. Three sabotages (spec US5).
- T305 Skills panel: Details, Instructions, Files and Test. The Test endpoint uses the runtime prompt path and is validated against real runs.

## Phase 4: Tasks and Automations panels (outline)

- T401 Tasks panel over the ledger: the Personal project, All open tasks, goal and progress, Break down (confirmed), groups, owner logos, and evidence words.
- T402 Automations panel: on/off, History (outcome, verbatim reason, `delivered_with`), and Edit.
- T403 The rule gains an `agent` field (store, parser, form), and agent schedules are listed.
- T404 A create-from-chat hook for 005 Slice 5.

## Phase 5: App pages (outline)

- T501 MCP Suite › Connected: the counts, the failing source with View log and Retry, the cards with "On in new chats", filters and search, and the servers list.
- T502 A default tool selection per user, applied at thread creation (composition-root test). This fixes "connected but not selected".
- T503 MCP Suite › Build, over `mcp_studio`: steps, tests, secrets (names only), egress, and Approve, Discard and View code.
- T504 Settings: one layout for every section. Tools and Skills redirect, and Activity log gains Inbox's alert history.
- T505 Gmail catalog copy changes to "draft" (Article V).

## Dependencies

- Within Phase 1: T001 blocks T003 and T004. T006 blocks T007 and T008. T015 blocks T016 and T017. T023 blocks T026. T020 blocks T022 and T025. T024 blocks T025 to T029.
- Phase 3 T304 depends on Open Question 5.
- Phase 4 T401 depends on 005 Slice 2, which is merged. Its evidence lines become complete after 005 Slice 4.
