# Implementation Plan: Workspace Studio

**Branch**: `006-workspace-studio` (one PR per phase) | **Date**: 2026-10-19 | **Spec**: [spec.md](spec.md) | **Design**: [design-notes.md](design-notes.md)

## Summary

Phase 1 changes three things:
- **The theme**: tokens and a server-side preference.
- **The shell**: sidebar, capsule, ⌘K and the Inbox removal.
- **The composer**: the chat bar and its picker, over existing APIs.

It adds one small backend surface, the user preferences API. Every other Phase 1 change is frontend.

Phases 2 to 5 add backend capability where the mockups need data that does not exist yet (design-notes.md, Disagreements): thread participants, agent fields, standing grants, draft endpoints, a rule's agent, and a default tool selection.

## Technical Context

- **Stack**: Python 3.12 / FastAPI / SQLAlchemy plus Alembic (gateway). TypeScript 5 / React 19 / Next.js 16 / Tailwind 4 / shadcn (Radix) / TanStack Query / next-themes (frontend).
- **New dependencies**: none. Inter and JetBrains Mono load through `next/font` (self-hosted at build, no network at runtime). Radix `Dialog`, `Tabs` and `Command` (cmdk) are already in `components/ui`.
- **Storage**: a new `user_preferences` table (migration `0015`): `user_id` (PK and FK), `theme`, `display_name` (Open Question 2), `updated_at`. Phase 5 adds `default_tool_sources` (JSON) to the same table.
- **Testing**:
  - pytest, including `tests/gates/test_wiring.py`;
  - a composition-root harness as in `backend/tests/ledger/conftest.py`;
  - vitest, including `tests/unit/colour-tokens.test.ts` and `theme.test.ts`;
  - Playwright rendering specs: `contrast.spec.ts` (both themes), `bundle-budget.spec.ts`, `sidebar.spec.ts`, `theme.spec.ts`, and the new specs below.
- **Performance**:
  - page usable in under 1 s and panel open in under 150 ms, both on `pnpm build && next start`, headless;
  - panels load through `next/dynamic`, prefetched on hover or focus of their capsule item;
  - ⌘K search uses gateway REST, not the LangGraph SDK (whose `@langchain/core` is a bundle-budget marker).

## Constitution Check

| Article | Compliance |
|---|---|
| I. Gateway only | Every new data path goes through `/api/*` routers. The frontend never reaches the core directly. |
| II. Three tiers | Phase 1 adds no tools. Phase 2: called-in agents run under the same `PolicyMiddleware`. Phase 3: standing grants live inside the policy layer, never around it, and are limited to action classes marked reversible (Open Question 5). |
| III. Provenance | @-mentions count only when typed in user turns. Content inside a tool result cannot call in an agent. |
| IV. Human in the loop | No session approvals are relayed. "Open session" opens the session view. |
| V. Non-goals | Drafts, never sends. Gmail's catalog copy is corrected to "draft" (design-notes #21). |
| VI. Lite | No new process and no heavy front-end library. Panels are lazy-loaded. |
| VII. Politeness | Automations history only shows what the existing pipeline recorded. Phase 1 changes no alerting. |
| VIII. Privacy | Secrets are never displayed in Build. Egress hosts are shown. Logos are local assets, with no third-party fetches at runtime. |
| IX. Slices | Each phase is one releasable PR. Phase 1 alone delivers themes, the shell and the visible tool selection. |
| X. Honest limits | The status vocabulary and the can't-tell states (design-notes); interim Home; disabled "@" with its reason. |
| XI. Production shape | One `create_app()`+lifespan test per phase. The rendering specs run on the production build. |
| XII. Probes | Every new guard is sabotaged: the token test, the contrast route list, the redirect, the preference read, the status mapping, and the grants (Phase 3). |
| XIII. Initiation ≠ confirmation | Phase 2 and Phase 3 each test these separately: a mention arriving in tool output is refused, and a grant never answers a pending confirmation. |
| XIV. Tracked defaults | The token values, the logo assets, THIRD-PARTY-NOTICES and the policy action-class rules are all tracked. |

**Result: PASS.**

## Phase 1: Foundation

### 1a. Tokens and appearance

- **`frontend/src/styles/globals.css`**: replace the `:root` and `.dark` values with the Graphite table, mapped as in design-notes.md §Tokens.
  - Add `--foreground-2`, `--border-strong`, `--primary-subtle`, `--overlay` and `--avatar-1..4` (each with its `-foreground`), and expose them in `@theme inline`.
  - Set `--radius: 10px` and re-derive `sm`/`md`/`lg` to 8/10/14.
  - Point `--font-sans` and `--font-mono` at the `next/font` variables.
- **`frontend/src/app/layout.tsx`**: load Inter (400, 500, 600) and JetBrains Mono (400) through `next/font/google`, as CSS variables. Keep `ThemeProvider` with `attribute="class"` and `defaultTheme="system"`, and no `forcedTheme` (see the comment in `components/theme-provider.tsx`).
- **Migrate existing screens**: sweep `components/workspace/**` and `app/workspace/**` for shadcn tokens used against the role they now carry. In particular, `--accent` stays the hover surface, and the brand accent is `--primary`. Fix anything the contrast spec flags in either theme.
- **Backend**:
  - `backend/packages/harness/omniharness/persistence/user_preferences/{model.py,sql.py}`;
  - migration `0015_user_preferences.py`;
  - router `backend/app/gateway/routers/preferences.py`, with `GET` and `PUT /api/me/preferences` (`{theme, display_name}`), the user taken from `request.state.auth`;
  - registered in `create_app()`.
- **Frontend**:
  - `frontend/src/core/preferences/{api.ts,hooks.ts}`.
  - A `ThemeSync` component in `workspace-content.tsx`: on sign-in it applies the server value through `setTheme`, and on change it writes back. Local storage (next-themes) stays, so the first paint is right.
  - `components/workspace/settings/appearance-settings-page.tsx` writes through the hook, and shows "Not saved; will retry" when the PUT fails.

### 1b. Shell, capsule and ⌘K

- **Sidebar**: `components/workspace/workspace-nav-chat-list.tsx` becomes New chat (`/workspace`, badge from `useInboxCount`, renamed `useWaitingCount`, with its `null` meaning can't-tell kept), Chats, and MCP Suite (`/workspace/connections`, relabelled; badge `failing`). The Projects, Automations, Connections, Agents and Inbox items are removed. Below it come `recent-chat-list.tsx` and the footer `workspace-nav-menu.tsx`: an avatar and a More menu with Settings, Memory, Safety, Activity log, Appearance and About (the existing website, GitHub and contact links move under About).
- **Home (interim)**: `app/workspace/page.tsx` stops redirecting to `/workspace/chats/new`, and renders `components/workspace/home/interim-home.tsx`:
  - the greeting and date;
  - **Waiting on you**, from `usePendingConfirmations` plus `useInboxAlerts` (waiting and missed), reusing `inbox/alert-row.tsx` and the confirmation card;
  - the chat bar, which starts a new thread.

  The static-demo redirect branch is kept.
- **Inbox**: `app/workspace/inbox/page.tsx` → `redirect("/workspace")`. `tests/rendering/inbox.spec.ts` is rewritten as a redirect and Home spec. `/api/inbox/alerts` stays; it is Home's source.
- **Capsule**: `components/workspace/capsule/capsule.tsx`, mounted once in `workspace-content.tsx` and fixed at the top centre. Its state lives in a `?panel=agents|skills|automations|tasks[&id=…]` search parameter, managed by `capsule/use-panel-param.ts` (`router.push` with `scroll: false`).
  - Closing calls `router.back()` when the panel was opened in-app, and otherwise removes the parameter.
  - `capsule/panel-sheet.tsx` wraps `components/ui/dialog`, which gives the focus trap, Esc and focus return.
  - Each panel body is `next/dynamic`. In Phase 1 they host the existing pages: `agents/agent-gallery.tsx`, skills from `settings/skill-settings-page.tsx`, the automations list (`automations/automation-row.tsx`), and the projects list (`app/workspace/projects/page.tsx` content).
- **⌘K**: extend `components/workspace/command-palette.tsx`.
  - Its sources are threads (gateway `POST /api/threads/search`), projects and tasks (`core/ledger`), agents (`core/agents`), skills (`core/skills`) and automations (`core/automations`). Queries are debounced and run only while the palette is open.
  - Actions: New chat, New agent (opens the Agents panel in new mode), Connect *app* (MCP Suite connect flow), Turn on dark or light theme, and Go to *every existing route*, so that FR-105 holds.
  - The key handler lives in `workspace-content.tsx`. It opens on ⌘K or Ctrl-K, and on "/" when `document.activeElement` is not editable.

### 1c. Chat bar, picker and logos

- **`components/workspace/chat-bar/`**: `chat-bar.tsx` replaces the layout of `input-box.tsx` but keeps its `PromptInput` core and every behaviour listed in FR-110. Moved, not rewritten: follow-ups, suggestions, stop, attachments, mode and effort logic (`getResolvedMode`), the model selector, and `ModeHoverGuide`.
  - `context-chips.tsx`: Project (the thread's ledger links), Agents (the lead agent in Phase 1), Integrations (a logo stack from the thread selection), Skills (read-only), Files (uploads).
  - `context-picker.tsx`: a dialog with `Tabs` (an arrow-key tablist) for Projects, Agents, Integrations, Skills and Files. The Integrations tab reuses the logic of `tools/tools-picker.tsx`: catalog, selection, `PUT /api/threads/{id}/tools` and count/cap. It adds `/api/tool-sources?thread_id=` for status.
  - `mention-menu.tsx` ("@", a listbox) and `command-menu.tsx` ("/").
- **`frontend/src/core/tool-sources/status.ts`**: a pure function from `ToolSource` to `{word, tone, selectable, link}`, per the design-notes table. Unit-tested over every state, and sabotaged.
- **Logo registry**: `frontend/src/core/brand/registry.ts` holds `{id → {src, name, source, licence}}`. Its keys are the connector slugs and the providers `anthropic` and `openai`. `components/workspace/brand/logo.tsx` renders `<img alt=name>`, or a monogram (initials on `--avatar-*`) for unknown ids.
  - `tools/integration-icon.tsx` becomes a thin wrapper, so its current callers keep working.
  - Session and owner labels (`components/workspace/sessions/*`, the ledger owner chips) use the provider marks.
  - Assets live in `frontend/public/brand/`. Each one gets a THIRD-PARTY-NOTICES.md entry with its source URL, the guideline followed, and its licence or terms.
- **New chat and threads**: the chat bar replaces `InputBox` in `chats/chat-box.tsx` and on Home. A new chat has no thread id until its first send, so picker selections are held locally and PUT once the thread id exists. This is how the current welcome flow works; the plan checks it during implementation.

### Phase 1 tests

- **vitest**:
  - `colour-tokens.test.ts` already scans all of `src`. A test asserts that `capsule/`, `chat-bar/`, `home/` and `brand/` are inside its scan (sabotage: exclude one).
  - `status.test.ts`.
  - `logo-registry.test.ts`: every entry has a source and a licence, and every asset file exists and is tracked (Article XIV).
- **Playwright**:
  - `contrast.spec.ts`: ROUTES gains every remaining page (workflows, policy, triggers, tool-sources, confirmations, chats, a chat thread, settings notification, about, tools and skills) plus each `?panel=`, in both themes.
  - `shell.spec.ts`: the sidebar items and badges (including "?"), the capsule's keyboard path, focus return, URL round-trip, and panel open time under 150 ms.
  - `chat-bar.spec.ts`: chips, picker tabs and arrow keys, the switch-to-PUT round-trip, the effort control hidden for an unsupported model, and every FR-110 behaviour.
  - `screenshots.spec.ts`: every page, plus the shell, the capsule (closed and open) and the chat bar, in light and dark, written to `frontend/test-results/screenshots/`.
- **pytest**: `tests/preferences/test_preferences_api.py`, through `create_app()` and its lifespan. A PUT followed by a GET from a fresh client (the "other browser") returns the same value, and another user's preference is not visible. The wiring gate covers the new module.

## Phase 2: Multi-agent chat

### 2.0 FIRST: confirming delegated and subagent actions (design spike, then build)

Two defects block multi-agent chat (AUDIT-2026-10 addendum, 2026-10-20):
- a delegation suggested by a page cannot be confirmed from the card;
- a subagent's own Tier 3 tool cannot be confirmed from the lead's chat, because nothing suspends the subagent.

**Decision (T200, 2026-10-20).** Proceeding on the recommendation below because the user asked for the work to finish without stopping. **The user can still overturn it**: everything here is reversible, and option (a) stays open as the path if the subagent should keep reasoning after the confirmed step.

Two facts were measured before deciding (probe in the chat agent's scratchpad):
- `langgraph.config.get_stream_writer()` raises `RuntimeError` outside a running graph. The `task` tool calls it first, so confirming a delegation from the card fails even when the route has the tool.
- A subagent's checkpoint key is the LEAD's `thread_id`, and the subagent checkpointer is the in-memory process singleton (no `checkpointer:` block ships in `config.example.yaml`). A second delegation in the same chat therefore starts with the first delegation's messages, and nothing a subagent checkpoints survives a restart or is visible to another worker.

**Options.**

| | (a) `interrupt` + checkpoint, resume with `Command(resume=…)` | (b) stop at the plan; on confirm run the ONE call against the proposing agent's recorded tool surface |
|---|---|---|
| Survives a gateway restart / another worker | Only with a durable, shared subagent checkpointer. Today it is in-memory per process, so a restart or a confirm on another worker finds nothing to resume. | Yes. The pending action (already a file per action, claimed with `os.link`) carries everything needed: the call, its arguments, and a description of the tool surface. No live state is needed. |
| Exactly once | The claim plus a resumed node. A resume re-runs the interrupted tool node; a crash between the tool and the next checkpoint re-runs the tool. | The claim (`take_claim`, one call site, gate-tested) and nothing else. Same window as every Tier 3 action today. |
| What the lead sees meanwhile | The `task` tool must return while its subagent is suspended (it polls an in-memory task table), so the lead needs a new "waiting" status, and the subagent's eventual answer needs a way back into the lead's thread. | Nothing new: the subagent's run ends with the stated plan, `task` returns it, and the lead says "Researcher is waiting for you". The card is the pending action, shown inline. |
| Cost | Rebuild and re-run the subagent graph on every confirm, plus a model call to continue. | One tool call. No model call. |
| After the confirmed step | The subagent continues reasoning. | The subagent does not continue on its own. The result is reported in the thread, and the lead (or the user) takes the next step. |

**Chosen: (b).** It works on today's infrastructure, its exactly-once guarantee is the claim we already trust, and it needs no durable subagent checkpointer. Its one cost (the subagent does not keep reasoning after the confirmed step) is stated in the reply rather than hidden. Option (a) becomes worth it once subagent checkpoints are durable and shared; the surface record below is what (a) would need too, so nothing is thrown away.

**How it works.**
1. **The tool surface is recorded with the proposal.** Every agent run carries a `tool_surface` in its runtime context, describing how its tool list was assembled:
   - lead: `{kind: "lead", model_name, agent_name, subagent_enabled, selected_sources, user_id}`;
   - subagent or @-called agent: `{kind: "subagent", agent, subagent_type, model_name, tool_groups, skills, selected_sources, user_id}`.

   `PolicyMiddleware` copies it onto the `PendingAction` (new `surface` field, persisted).
2. **One rebuild function, used by both confirm paths.** `tools_for_surface(surface, app_config)` reassembles the list with the SAME functions that built it the first time (the lead's assembly is extracted from `_make_lead_agent`; the subagent's from the `task` tool and the executor's filters). Chat (`PolicyMiddleware._runner`) and the card (`routers/confirmations._runner`) both call it. The chat path no longer takes the LEAD's live `request.tools` for an action a subagent proposed, and the card path no longer rebuilds the thread's tools without `task`. An action recorded before this change has no surface and keeps the old behaviour.
3. **It runs as the proposing agent.** The confirmed call is invoked with the proposer's runtime context (thread, user, `invited_agent`, `delegation_chain`, inherited origin), so it runs "in that subagent" and its result names it. Async-only tools (MCP, `task`) are awaited off the event loop. The card route runs the flow in a worker thread, so a delegation confirmed from the card does not block the gateway while the subagent works.
4. **`task` from the card.** The `task` tool tolerates having no stream writer (it reports progress only when a graph is running), and its runtime is built from the recorded surface (model, tool groups, skills). The delegated subagent starts from the ACTION's origin (`invited_agent_context`), never from the click: confirming "delegate this" approves the delegation, not whatever the delegate later asks for.
5. **Subagent checkpoints are keyed per delegation** (`<thread_id>/subagent/<task_id>`), so a delegation never inherits another one's messages.
6. **@-called agents use the same mechanism.** Calling an agent in runs it through the subagent executor with `invited_agent_context` from the user turn that mentioned it (origin `user`, chain `lead_agent → <agent>`), and with a `subagent` surface. Its Tier 3 calls are recorded, shown and confirmed exactly like a delegated subagent's.

**Test plan** (each through `create_app()` + lifespan + the real `SubagentExecutor`, only the chat models faked; each with a sabotage that must fail it):
- A page-suggested `task` is card-only; confirming it by button runs the subagent ONCE; a second confirm is `already_resolved` and runs nothing. Sabotage: the card path rebuilds tools without the surface (the old code), and the outcome is `failed` with `LookupError`.
- A subagent's own Tier 3 tool, which the lead does NOT have, confirmed by typing "yes" in the lead's chat, runs ONCE, with the subagent's tool and the subagent's runtime context (`invited_agent`). Sabotage: the chat path uses the lead's `request.tools`, and the test fails on `LookupError`.
- The same action confirmed from the card runs once. Sabotage: drop the claim check, and the double-confirm test runs it twice.
- Two delegations in one thread: the second subagent does not see the first one's messages. Sabotage: key the checkpoint by the thread id again.
- An @-called agent's Tier 3 call shows `delegation_chain = [lead_agent, <agent>]` and is confirmable from the card.

**Acceptance**, each check with a sabotage that must fail it:
1. A page-suggested delegation, confirmed by the button, runs ONCE.
2. A subagent's own Tier 3 action, confirmed from the lead's chat, runs ONCE in that subagent with its own tools.
3. A test through the production composition root, `create_app()` + lifespan + the real `SubagentExecutor`.

- **Participants**: `thread_meta` gains `participants` (a list of agent names, with `lead`) and a router `routers/thread_participants.py`. The mention parser runs in `thread_runs.py` on user turns only (Article III).
- **Running a called-in agent**: reuse the subagent executor (`omniharness/subagents/executor.py`, `tools/builtins/task_tool.py`), with that agent's config (`config/agents_config.py`). Its tools are the intersection of the thread's selection and the agent's `tool_groups` and `skills` (see `_merge_skill_allowlists`). `PolicyMiddleware` applies unchanged.
- Messages carry `agent_name`, which `components/workspace/messages/*` renders with the avatar.
- **Tests**: through `create_app()`, two agents each use only their own tools; removing an agent stops its replies; "@unknown" does nothing; a mention arriving in tool output is ignored.

## Phase 3: Agent and Skill Studio

- **Agent fields**: `display_name`, `avatar`, `projects`, `schedule` and `autonomy`, in `agents_config.py` and `routers/agents.py`, with "chat to create" (`setup_agent_tool.py`) kept.
- **Drafts**: `routers/drafts.py`, `POST /api/drafts/{field_type}` for `agent_instructions`, `agent_description`, `skill_when` and `skill_body`. Each returns text and never writes, which a gate test asserts.
- **Standing grants**:
  - `backend/app/policy/grants.py`, checked in `middleware.py` before the Tier 3 path, with an action class read from `default_rules.yaml` (`reversible: true`, tracked);
  - the audit goes to `audit.py`;
  - the API is `routers/policy.py`.
  - Three sabotages: a grant applies in a chat run; a grant covers an irreversible class; a revoked grant still applies on the next call.
- **Skill Test**: `routers/skills.py`, `POST /api/skills/{name}/test`. It builds the prompt section with the same function `lead_agent/prompt.py` uses, runs the configured model, and reports the observed picks per try (Open Question 6). It is validated against real-run traces.
- **Frontend**: the `capsule/panels/{agents,skills}/`, tabbed per the mockups.

## Phase 4: Tasks and Automations panels

- **Tasks**: `capsule/panels/tasks/`, over `core/ledger` only.
  - "Personal" is an ordinary project, created on first use.
  - Break down calls `ledger_apply` through the confirmation card.
  - Owner chips use the logo registry. Evidence lines say "observed" or "reported" (pending 005 Slice 4).
- **Automations**: `capsule/panels/automations/`, over `routers/automations.py` and `routers/triggers.py` (`/rules` and `/firings`).
  - History uses the outcome, the verbatim `reason` and `delivered_with`.
  - The rule gains an optional `agent`, through `automations_store.py` and the engine parser.
  - It exposes `openAutomationDraft(rule)`, the create-from-chat hook for 005 Slice 5.

## Phase 5: App pages

- **MCP Suite** (`app/workspace/connections`, `components/workspace/mcp/*`):
  - **Connected**: the counts from `/api/tool-sources`, "View log" (load error and history), Retry (re-runs the load), cards from `/api/tools/catalog`, and servers from `extensions_config` (transport, tool count, agent-built origin).
  - **"On in new chats"**: `PUT /api/me/preferences {default_tool_sources}`. It is applied in `thread_tool_selection` when a thread gets its first selection (the composition-root test).
  - **Build**: over `routers/mcp_studio.py` (build, test, approve, egress).
  - **Copy**: the Gmail catalog text is fixed to say "draft".
- **Settings** (`components/workspace/settings/*`): the Memory, Safety, Activity log (including Inbox's alert history), Notifications, Account (with display name), Appearance and About sections share one layout. The Tools and Skills sections redirect.

## Project Structure

```text
specs/006-workspace-studio/
├── spec.md  plan.md  tasks.md  design-notes.md
├── checklists/requirements.md
└── design/*.dc.html, README.md
```

## Complexity Tracking

There are no constitution violations.

One deliberate cost: the Phase 1 panels host the existing pages inside sheets, so the capsule, its URL contract and focus handling ship before the redesigns. Phases 3 and 4 then replace the panel bodies without touching the shell.
