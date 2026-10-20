# Design notes: Workspace Studio (Graphite)

What the mockups in [design/](design/) contain, screen by screen, and where they disagree with our data or rules. **Our rules win**; each disagreement states the resolution. Values are the mockups' dark values. Light values come from the token table below, not from Home-B.

## Tokens

### Mapping onto the existing tokens

There is one set of semantic tokens, and the mockup roles map onto them. `frontend/src/styles/globals.css` already defines the shadcn tokens, and the mockup roles map onto them as follows. Note that shadcn's `--accent` is a hover surface, not the brand accent.

| Mockup role | Dark | Light | Token (existing → new) |
|---|---|---|---|
| bg | #121316 | #F7F7F8 | `--background` |
| sidebar, panel sheet | #17181C | #EFF0F2 | `--sidebar` |
| surface (cards, chat bar, popovers) | #1C1E23 | #FFFFFF | `--card`, `--popover` |
| raised (chips, user bubble, selected row, segmented buttons) | #24272D | #F1F2F4 | `--secondary`, `--muted`, `--accent` (hover) |
| border | #2E3138 | #DDDFE3 | `--border` |
| strong border (inputs, chat bar #3A3E46; outline buttons, dashed #4A4E57) | #3A3E46 / #4A4E57 | #C9CCD3 | `--input`, **new** `--border-strong` |
| text | #ECEDEF | #17181B | `--foreground` |
| text-2 (nav items, body in cards) | #C9CCD2 | #2F333A | **new** `--foreground-2` |
| muted (meta, labels, timestamps) | #9EA3AD | #5A606B | `--muted-foreground` |
| accent (primary button, links, active tab underline, on-switch) | #8FA8FF | #3355D6 | `--primary`, `--ring`, `--highlight` |
| on-accent | #121316 | #FFFFFF | `--primary-foreground` |
| good | #6FD3A0 | #1E7A4B | `--success` |
| warn | #F2B65A | #8A5300 | `--warning` |
| bad | #FF8A80 | #B3261E | `--destructive` |

### Colours the mockups use that are not in the table

Each of these needs a token, or is dropped:
- **Selected tab and selected "+" fill** #2F3A5C: new `--primary-subtle`, about 18% of the accent mixed into the surface. Its text must be `--foreground`, because muted text on it is 4.41:1 and fails AA.
- **Link hover** #B7C6FF: `color-mix` of the accent, not a literal.
- **Panel scrim** #0C0D0F: new `--overlay`.
- **Status pill borders** good #2F5A49 and warn #5A4628: `color-mix(status 35%, surface)`.
- **Agent avatar fills** #24272D (lead), #2F3A5C, #3D2F4F, #23423A: new `--avatar-1` to `--avatar-4`, each with a light value. The "@Release manager" mention colour #C9A8FF becomes `--avatar-3`'s foreground.
- **Logo placeholder fills** #3B6FD8, #4A154B, #D9C3A5, #ECEDEF: dropped. The real logos replace them.

### Contrast

Computed for every text token on bg, sidebar, surface and raised:
- **Dark**: the lowest pair is 5.91:1 (muted on raised). On-accent is 8.15:1.
- **Light**: the lowest pair is 4.67:1 (good on sidebar). On-accent is 6.16:1.

Every pair passes AA. Two points need care:
- **Light good on sidebar** passes, but only narrowly. Do not lighten the good colour.
- **Non-text contrast**: borders on bg are 1.43:1 and the off-switch border is 2.0:1. A component must therefore be identifiable by something other than its border:
  - an off switch, by its knob (muted, 5.9:1);
  - a field, by its fill and its label.

### Type and shape

- **Type**: Inter 400, 500 and 600, at 14px with line-height 1.5. JetBrains Mono for ids, paths and code.
- **Sizes**:
  - h1: 28px on Home, 24px on pages;
  - panel title: 15px;
  - entity title in a panel: 18px;
  - section h2: 13px, weight 600, muted;
  - meta: 12px;
  - chips: 13px;
  - composer text: 15px.
- **Radii**: the mockups use 4 to 18. They collapse to:
  - **8**: chips, nav items, small buttons;
  - **10**: buttons, inputs, list rows;
  - **14**: cards, the chat bar, panels. The mockups use 16 for the chat bar and 18 for sheets; both become 14.

  Pills, avatars and switches are fully round.
- **Spacing seen in the mockups**:
  - nav item padding 9px 10px;
  - card padding 18px 20px;
  - panel header padding 14px 20px;
  - panel body padding 24px 28px;
  - grid gaps 20 to 24px.

## Screens

### Shell (on every screen)

**Sidebar**: 248px wide (220px minimum), `--sidebar`, with a right border and padding 20px 12px.
- **Brand row**: a 22px mark (ring plus dot in the accent) and "OmniHarness" at 15px/600.
- **New chat**: a pen icon. Its badge is the warn fill with on-warn text, 12px/600, radius 10 and padding 0 7px.
- **Chats**: a speech-bubble icon.
- **MCP Suite**: a warn-coloured count, which Main renders as "1 unreachable".
- A 1px divider. "Recent" in 12px muted, then up to 5 chats with padding 7px 10px. The active chat has the raised fill.
- **Footer**: a top border, a 28px round avatar ("R" on #2F3A5C), the name, and an outline "More" button (aria-label "More: settings, memory, safety").

**Capsule**: `role="toolbar"`, aria-label "Tools". Surface fill, a border, radius 14 and padding 4. Its items are ghost buttons with an icon and a label, 13px with padding 8px 12px:
- Agents
- Skills
- Automations
- Tasks

After a 1px by 20px separator comes the ⌘K button: a raised fill, a search icon and "⌘K" (aria-label "Search everything").

Main centres the capsule. Chat puts it at the right of the header, and Settings and MCP omit it. **Resolution: top-centre on every page** (brief).

**Panels**: these are the Agent-Studio, Skill-Studio, Tasks and Automations mockups.
- The scrim is #0C0D0F, with padding 24.
- The dialog is a sheet, up to 1180px wide (1240px for Tasks), with the sidebar fill, a border and radius 18 (→ 14).
- **Header**: an 18px icon, the h1 at 15px/600, and a × button (aria-label "Close").
- **Body**: a list rail 230 to 280px wide with a right border. Its first item is a dashed "+ New …" button; after that come the items. The selected item has the raised fill and `aria-current`.
- **Detail**: padding 20px 28px. The title is 18px/600 with a 13px muted subtitle. The tablist uses a 2px accent underline for the selected tab (muted otherwise), with padding 8px 12px. The tabpanel is up to 760px wide.
- **Footer**: the actions are at the right, above a top border.

### Home (Main.dc.html; built in 005 Slice 3, with the interim version in Phase 1)

**Header**
- "Good evening, Rishabh" (28px/600).
- "Monday, October 19 · 2 things need you" (muted).

**Waiting on you**: a surface card with radius 14. Its h2 is 13px/600 in warn. Each row has gap 16 and padding 14px 20px, with a top border.
- **Session row**:
  - a 28px provider logo (aria-label "OpenAI logo (Codex session)");
  - "Codex · omniHarness@005-project-ledger" in 12px muted;
  - "Asked: “Should I pin the fixture version or rewrite the fixture?”";
  - "Observed · 6 min ago";
  - an outline "Open session" button.
- **Approval row**:
  - a lock icon;
  - "Approval · Google Calendar";
  - "Delete event “E2E test, delete me” (Tue 3:00 PM)";
  - "Asked in “Calendar cleanup” · expires in 3h 41m";
  - Decline (outline) and Confirm (solid).

**Projects** (left column of a grid with gap 20): name (500) and "3 of 7 tasks", "Feature 005 · Slice 1 in progress", then a progress bar (6px, track `--border`, fill accent, radius 3). The other rows read:
- "1 of 4 tasks", "Due Fri, Oct 23";
- "No task list yet", "Next: sync with Mike Flores, Tue 11:00 AM".

**Coding sessions**:
- rows with a 22px logo, the repository@branch, and a state: "Working" (good), "Waiting on you" (warn) or "Finished 22m ago" (muted);
- a footer reading "Watcher live · updated 12s ago".

**Upcoming**: time in muted, 92px wide, then the title.

**What moved today**: three lines.

**Chat bar**: docked at the bottom, up to 840px wide.

### Chat (Chat.dc.html)

**Header**: the title (500), an avatar stack (24px, -6px overlap, 2px bg ring; aria-label "Agents in this chat: Lead agent, Researcher, Release manager"), "3 agents", and the capsule.

**Thread**: up to 820px wide, with a gap of 22.
- **User bubble**: raised fill, radius 14, padding 12px 16px, up to 80% wide. It starts with the mention: "@Researcher" in the accent, or "@Release manager" in #C9A8FF.
- **Agent reply**: a 30px avatar, the name (600), and 12px muted meta (for example "Web search · GitHub" or "OmniHarness project"), then the body. Inline code sits on the raised fill with radius 4.
- **Approval card**: `section`, aria-label "Approval needed", with a warn border, radius 12, padding 14px 16px and the surface fill.
  - "Needs your approval · Slack" in warn, 13px/600;
  - "Expires in 3h 58m";
  - "I will post the Slice 1 plan to **#omniharness**.";
  - Decline and Confirm.

**@ menu**: `listbox`, "Agents to call in", up to 420px wide, surface fill, strong border, radius 14 and padding 6. It opens with "Call in an agent" in 12px muted. Each option has a 26px avatar, the name and its meta ("Project status · GitHub, Calendar" or "In this chat"), and the selected option has the raised fill and an "Enter" hint. The last option, "+ Create an agent", has a top border.

**Chat bar**: surface fill, strong border, radius 16 (→ 14) and padding 12px 14px, with a gap of 10.
- **Chips**: raised fill, radius 8, padding 5px 8px, 13px.
  - The project chip has a × button (aria-label "Remove project").
  - The agents chip reads "Lead · Researcher · Release manager".
  - The integrations chip is a logo stack (18px, radius 5).
  - The "+" button is dashed (aria-label "Add context"; in Main, "Add context: project, agent, integration, skill or file").
- **Text**: 15px, with the placeholder "Ask anything · @ to bring in an agent · / for commands".
- **Bottom row**:
  - Attach is a ghost icon button (aria-label "Attach file").
  - A spacer follows.
  - The Mode, Effort and Model buttons have the raised fill, radius 8, padding 6px 10px and 12px text: "Pro ▾", "Effort: High ▾", "Claude Sonnet ▾". Their aria-labels are "Mode: Pro", "Reasoning effort: High" and "Model: Claude Sonnet".
  - Send is 36px, radius 10, solid accent, with an arrow icon.

### Chat picker (Chat-Picker.dc.html)

**Container**: a `dialog`, "Add context", with the surface fill, a strong border and radius 14. Above it is a tablist, "Context type", with five tabs:
- Projects
- Agents
- Integrations
- Skills
- Files

The selected tab is filled #2F3A5C and has 500-weight text. Every tab is padded 7px 12px with radius 8.

**Search**: a field with the placeholder "Search integrations", on the raised fill with radius 10.

**Rows**: gap 12 and padding 8px 10px. Each has a 28px logo with radius 7, the name, a status word in 12px, and either a switch or a link.
- Google Calendar: "Live" (good). The switch is on (aria-label "Use Google Calendar in this chat").
- Gmail and Google Drive: "Live". The switch is off.
- GitHub: "Live". The switch is on.
- session-watcher: "Unreachable" (warn), with the link "Check".
- Slack: "Not connected" (muted), with the link "Connect".

**Switch**: 36 by 20, with a 16px knob. On, it is filled with the accent and has a bg-coloured knob. Off, it has the raised fill, a strong border and a muted knob.

The reply in the thread reads: "Gmail is connected but off in this chat; turn it on if you want me to check invites too."

### Agents panel (Agent-Studio.dc.html)

**Rail**: "+ New agent", then the agents with 26px avatars:
- Lead agent
- Researcher
- Evening wrap-up
- Release manager

**Detail header**: a 40px avatar, "Evening wrap-up", the subtitle "Tells you what moved and what's stuck, every weekday at 6:00 PM", and an "Active" pill (good text, good border, radius 8). Tabs: Overview, Instructions, Tools and skills, Autonomy, Schedule.

**Overview**: four stat cards (surface fill, radius 12, padding 14px 16px, with a 12px muted label):
- "Works on": OmniHarness, HackMIT 2026;
- "Uses": the GitHub and Calendar logos, "+ 2 skills";
- "Next run": "Tomorrow, 6:00 PM";
- "On its own it may": "Update tasks, add notes".

Below them is "Recent runs":
- "Today 6:00 PM · Delivered on Telegram · 9 lines", with the link "Open";
- "Fri 6:00 PM · Held for approval: archive 3 stale tasks", with the link "Review".

**Instructions**:
- A one-sentence field with an accent border, labelled "Describe the agent in one sentence", next to a solid "Draft" button.
- A textarea holding the instructions, with line-height 1.6.
- The note "Drafted from your sentence · edit freely".

**Tools and skills**:
- "Integrations": chips with a logo, the name and "Live", plus a dashed "+ Add".
- "Skills loaded every run": "Cite every claim" and "Project status format", plus "+ Add".

**Autonomy**:
- The text: "In chat it always asks you first. On a schedule nobody is there to ask, so choose what it may do on its own."
- A fieldset, "May do on its own (reversible)", with three choices:
  - Create and update tasks
  - Add notes and decisions
  - Archive stale tasks
- A box: "Always waits for you: sending messages, permanent deletes, calendar changes that notify others."

**Schedule and alerts**:
- "Weekdays at 6:00 PM · America/New_York", with an outline "Edit" button.
- Two checkboxes: "Send the result to Telegram" and "Show it on Home".

**Footer**: "Test run" (outline) and "Save" (solid).

### Skills panel (Skill-Studio.dc.html)

**Rail**: "+ New skill", then the skills:
- Cite every claim
- Project status format
- Deep research
- Web app builder

**Detail header**: "Project status format", with the subtitle "Used by Evening wrap-up and Release manager". Tabs: Details, Instructions, Files, Test.

**Details**:
- The "Name" field, up to 480px wide.
- "When should it be used?", with an outline "Draft" button and a textarea. Its help text: "This sentence decides when the skill loads. Name the situations, not the steps."

**Instructions**:
- A one-sentence field ("Describe it in one sentence and let it draft the instructions") with an outline "Draft" button.
- A formatting toolbar (B, I, H, List, </>), above a rich preview on the bg fill, 220px tall at least.

**Files**:
- Rows in mono: "example-report.md · 2 KB" and "score_risk.py · 4 KB".
- A dashed drop zone: "Drop scripts, references or templates here, or choose files".

**Test**:
- "Try messages and see whether this skill gets picked."
- Three rows, each a message and a result:
  - “Where are we on HackMIT judging?”: Loads (good)
  - “Wrap up my day”: Loads (good)
  - “Write a tweet about our launch”: Doesn't load (muted)
- A "Type a test message" field.

**Footer**: "Cancel" (outline) and "Save skill" (solid).

### Tasks panel (Tasks.dc.html)

**Rail**: "+ New project", then "All open tasks 14", a divider, and the projects with their open counts:
- OmniHarness 4
- HackMIT 2026 judging 3
- DarcyIQ walkthrough 2
- Personal 5

**Detail header**: "OmniHarness" (20px/600), with "Goal: Feature 005 Project Ledger shipped · 3 of 7 tasks done" beneath. Next to it is a nav, "Project views": Tasks (selected, raised fill), Evidence, Decisions, Chats.

Below the header:
- a progress bar at 43%;
- a quick-add field ("Add a task, or describe a goal and let the agent break it down"), with an outline "Break down" button.

**Groups**: each heading is an h3 in 12px/600 muted. Each row has an 18px checkbox, the title, a 12px evidence line, an owner chip (logo plus name, outline, radius 7) and a state or date.

- **In progress**:
  - "Codex adapter for the session watcher". Evidence: "Observed: 4 commits today on 005-project-ledger · Reported by Codex: 5 of 7 steps". Owner: OAI Codex. State: "Waiting on you" (warn).
  - "Native todo lists, applied only after a confirmed result". Evidence: "Observed: Claude Code session working · last activity 1m ago". Owner: Anthropic Claude Code. State: "Working" (good).
- **To do**:
  - "Review slices 1 and 2". Evidence: "No activity yet". Owner: You. Date: "Wed, Oct 21".
  - "Live Tier 3 check on a throwaway calendar event". Evidence: "Added from chat “Calendar cleanup”". Owner: You. Date: "No date".
- **Done this week**: "Phase 2.6 polish". Evidence: "Observed: PR #41 merged". Owner: Claude Code. The row is muted.

### Automations panel (Automations.dc.html)

**Rail**: "+ New automation", then the automations. Each row has its name, a 12px schedule, and an 8px status dot (good when on, outlined when off):
- Morning brief: "Weekdays 8:45 AM"
- Blocked session alert: "When a session waits on you"
- Evening wrap-up: "Agent · weekdays 6:00 PM"
- Weekly review: "Fridays 4:00 PM" (off)

At the foot of the rail is a tip: "Tip: in any chat, say “every weekday at 9, brief me” to create one."

**Detail header**:
- "Morning brief", with the subtitle "Weekdays at 8:45 AM · America/New_York · to Telegram";
- "On", next to a 40 by 22 switch (aria-label "Morning brief is on").

Tabs: History, Edit.

**History**:
- Three stat cards:
  - Next run: Tomorrow 8:45 AM
  - Last checked: 2 min ago
  - Quiet hours: 10 PM to 7 AM
- Rows, each with a time 130px wide, an outcome and a link:
  - "Delivered on Telegram" (good)
  - "Held, then delivered at 9:02 AM. You were mid-conversation." (accent)
  - "Delivered with 1 other (Blocked session alert), one message" (accent)
  - "Failed: the agent run errored (model timeout). Not retried." (bad)

  Each row links to "Open thread", except the failed one, which links to "Details".

### MCP Suite: Connected (Connections.dc.html)

**Header**: "MCP Suite" (24px/600), with "Where your agents' tools come from, and whether each one works right now." beneath and a solid "Browse apps" button. Tabs: Connected, Build. They are links that use the tab role.

**Counts**: three pills: "5 live" (good), "1 unreachable" (warn border) and "3 not connected".

**Needs attention**: a warn-bordered section.
- "session-watcher can't be reached"
- "Agents can't see your coding sessions until it's back." The reason follows in mono: "connection refused · host.docker.internal:18101".
- "View log" (outline) and "Retry" (solid warn).

**Apps**:
- Filter pills (`aria-pressed`): All (selected, text-coloured fill), Productivity, Communication, Dev tools.
- A search field.
- **Cards**: surface fill, radius 14, padding 16px 18px. Each has a 36px logo, a name and purpose, a status, a top-bordered "On in new chats" switch, and a "⋯" options button. They read:
  - Gmail: "Read, search and draft email". Live; switch off.
  - Google Calendar: "Events and availability". Live; switch on.
  - Google Drive: "Files and docs". Live; switch off.
  - GitHub: "Repos, issues and PRs". Live; switch on.
- **Not-connected cards**: dashed, on the sidebar fill, each with an outline "Connect":
  - Slack: "Channels and messages"
  - Notion: "Pages and databases"

**MCP servers**: rows of name (mono), transport, tool count and status:
- session-watcher: "Local · SSE", "— tools", Unreachable
- composio: "Remote · HTTP", "42 tools", Live
- hackmit-devpost "· built by an agent": "Sandbox", "3 tools", Off

### MCP Suite: Build (MCP-Suite.dc.html)

**Build card**: "Need a tool that doesn't exist yet?" (17px/600).
- A describe field with an accent border ("Describe it, e.g. “check my Devpost submissions and their judging status”"), and a solid "Build it" button.
- Three numbered steps:
  1. You describe it: "One sentence is enough".
  2. An agent builds and tests it: "In a sandbox, away from your data".
  3. You approve its first run: "Keys stay hidden from the model".

**Your MCP servers**: a list on the left and a detail pane on the right.
- **List**:
  - hackmit-devpost: "Built today · 3 tools", "Needs approval" (warn)
  - gym-log: "Built Oct 12 · 2 tools", Live
  - status-page-watch: "Build failed · Oct 9", Failed
- **Detail**: "hackmit-devpost", with a "Waiting for your approval" pill and "Check Devpost submissions and their judging status." Then the steps:
  - ✓ "Scaffolded server, 3 tools: list_submissions, get_submission, judging_status"
  - ✓ "Tests passed in sandbox: 5 of 5"
  - ✓ "Uses secret DEVPOST_TOKEN: stored, never shown to the model"
  - ● "First real run needs your approval"
- **Actions**: "View code" and "Discard" (outline), and "Approve and turn on" (solid).

### Settings: Memory (Settings.dc.html)

**Layout**: the More menu is expanded (`aria-expanded`). A second rail, 240px wide, holds "Settings" (18px/600) and seven sections:
- Account
- Memory (current)
- Safety
- Notifications
- Activity log
- Appearance
- About

**Memory**:
- "Memory" (24px), with "What OmniHarness has learned about you. Edit anything that's wrong." beneath.
- A solid "Add fact" button and a "⋯" button (aria-label "More memory actions: import, export, clean up, clear").
- Tabs: "Summary", and "Facts · 38".

**Summary cards**: radius 14, padding 16px 18px. Each has an h2 at 15px/600, an "Edit" link in the accent, body text in text-2, and an "Updated …" line.
- **Work**: "Builds OmniHarness, a personal AI workspace…"
- **Personal**: "In America/New_York. Likes scheduling stated as explicit time ranges." Its line reads "Updated 4 months ago · may be out of date" (the last part in warn).
- **Top of mind**: has a "Show more" link, and its line reads "Updated today".

### Home-B.dc.html (Direction B)

Not chosen. It uses IBM Plex Sans 13px, radius 6 and 10, a table for projects, text badges ("Codex" and "Approval") instead of logos, and a separate light palette (#F5F6F8, #2F5BEA). **Ignored**, except as confirmation that the same blocks work in a light layout.

## Status vocabulary (picker, chips, MCP Suite, agent Tools)

The gateway's states (`app/gateway/tool_sources.py`) map onto the words as follows. The per-chat switch is separate from the status, and shows only whether the source is selected in this chat.

| Gateway state | Word | Colour | Switch in the picker |
|---|---|---|---|
| local `live` | **Live** (with N tools) | good | yes |
| local `disabled` | **Off** | muted | no; links to MCP Suite |
| local `unreachable` | **Unreachable**, with the real `error` | warn | no; links to MCP Suite ("Check") |
| local `not-configured` | **Not connected** | muted | no; links to MCP Suite ("Set up") |
| local `not-loaded` | **Not checked yet** (can't-tell) | muted | yes, labelled as unverified |
| connector `authorised`, `-selected`, `-not-selected` | **Connected** (Open Question 1; the mockups say "Live") | good | yes |
| connector `not-authorised` | **Not connected** | muted | no; links to MCP Suite ("Connect") |
| `connectors_available: false` | one line: "Apps need a Composio key"; not eight "Not connected" rows | muted | — |

## Disagreements: mockup vs our data or rules

| # | Mockup | Our data or rule | Resolution |
|---|---|---|---|
| 1 | Two solid buttons on one screen: Chat (Confirm and Send), Home (Confirm and Send), Agents › Instructions (Draft and Save), MCP Build (Build it and Approve and turn on), Connected (Browse apps and solid-warn Retry) | One solid primary per screen | **Chat and Home**: Send stays solid, and Confirm becomes an emphasised outline (accent border and text). **Agents**: Save is solid and Draft is outline. **Build**: whichever step is current is solid (Approve while a build waits, otherwise Build it). **Connected**: Browse apps is solid, and Retry is outline with the warn colour. |
| 2 | An authorised connector reads "Live" | We only know that Composio reports the connection ACTIVE, which is reported and not observed | "Connected" (Open Question 1). "Live" only for an observed load. |
| 3 | Picker statuses use four words | The gateway has nine states, including `not-loaded` and `connectors_available` | The status vocabulary table above. `not-loaded` is can't-tell, never Live. |
| 4 | The picker shows no tool count | The current picker shows "N / cap" and blocks going over the cap | Keep the count and cap in the Integrations tab (FR-110). |
| 5 | Every chip is removable, including Skills | No per-thread skill selection exists. Skills are global, plus a whitelist per agent. | Read-only Skills chip in Phase 1 (Open Question 7). |
| 6 | "@" calls a second agent | Phase 2 machinery | Phase 1 behaviour as in Open Question 8. |
| 7 | Greeting "Rishabh" and the footer name | Users store only an email | Optional display name (Open Question 2). Until it is set, no name. |
| 8 | Automations History paraphrases the reason ("You were mid-conversation.") | `FiringView.reason` is verbatim and never summarised (004 FR-019) | The outcome word in colour, then the recorded reason verbatim. The "Delivered with 1 other" line uses `delivered_with`. "Not retried" only when the record says so. |
| 9 | "Last checked 2 min ago" and "Next run" | `last_evaluated` may be `not-recorded` or `never` | "Can't tell when it last checked" or "Never checked yet". Next run is computed from the schedule, with "can't tell" for event triggers. |
| 10 | Agent schedules sit in the Automations list ("Agent · weekdays 6:00 PM") | Rules have no agent field, and agents have no schedule | Phase 4 adds `agent` to the rule, through the existing write path. Until then, no agent rows. |
| 11 | Agents have a display name ("Evening wrap-up"), avatar colour, "Active" status, "Works on" projects and "Next run" | `AgentResponse` has a slug name (`^[A-Za-z0-9-]+$`, lowercase), description, model, tool_groups, skills and soul | Phase 3 adds display name, avatar, projects and schedule. "Active" only when an enabled schedule exists. Until then, a title-cased slug. |
| 12 | Autonomy: "In chat it always asks you first" | Tier 1 runs silently, and Tier 2 runs and then discloses (Article II) | "In chat, anything irreversible waits for you. On a schedule…" |
| 13 | Autonomy: "Always waits for you: sending messages, permanent deletes, calendar changes that notify others" is hand-written | Waiting is decided by Tier 3 classification per tool | The list is generated from the agent's tools' Tier 3 classification. |
| 14 | Autonomy has three choices | The brief includes "draft, not send" | Add "Draft messages (never send)". `ledger_apply` is Tier 3 (Open Question 5). |
| 15 | Skill Test shows a definite "Loads" or "Doesn't load" | Skills are chosen by the model reading their descriptions (`lead_agent/prompt.py` `<skill_system>`), not by a function | Report what was observed per try (Open Question 6). |
| 16 | Task groups: In progress, To do, Done this week | `TaskStatus` is todo, doing, blocked, done or dropped | `blocked` goes in In progress with the word "Blocked". `dropped` is hidden, but counted under "Dropped (n)". |
| 17 | A task row shows "Waiting on you" | That is the linked session's state, not the task's | Label it as the session's ("Codex session: waiting on you · observed"). |
| 18 | "3 of 7 tasks done (observed)" in a chat reply | Task status is recorded in the ledger, not observed evidence | Progress counts carry no evidence label. "Observed" and "reported" apply only to evidence lines. |
| 19 | "Reported by Codex" | 005 uses "claimed" | "Reported" in the UI (Open Question 3). |
| 20 | "Observed: 4 commits today", Home's "Upcoming", "What moved today" and "Next: sync … Tue" | Git and calendar evidence arrive in 005 Slice 4 | Until then, each says it can't tell yet and why ("Calendar not linked yet"). Never empty. |
| 21 | Gmail's purpose: "Read, search and draft email" | The constitution (Article V) says drafts only, but the code's catalog says "send emails" (`routers/composio.py`) | The mockup is right. The catalog copy is fixed in Phase 5, and noted as a code-vs-rule bug. |
| 22 | Connected shows "3 not connected" but only two cards | The counts come from data | Counts are computed, never typed in. |
| 23 | MCP Build shows no egress | `McpServerResponse.egress_hosts` exists | Show "Talks to: …" in the build steps. |
| 24 | The Settings rail lacks Tools and Skills, which exist today | The existing sections | Tools moves to MCP Suite and Skills to the Skills panel. The old URLs redirect (FR-502). |
| 25 | Capsule placement varies: centred, header-right, or absent | Brief: top-centre on every page | Top-centre everywhere. |
| 26 | "/" means two things: commands in the chat bar, and "work from anywhere" | One key must not do both | "/" at the start of the chat bar opens commands. Anywhere outside a text field, it opens ⌘K. |
| 27 | The approval card shows the plan with Decline and Confirm only | Existing cards have targets, a typed count above threshold, the delegation chain, Edit (005 T017) and Withheld | Every existing field is kept. The mockup is only the visual shell. |
| 28 | The New chat badge shows a number | `useInboxCount` returns `null` when it can't tell | "?" with "Cannot tell what is waiting", as today. |
| 29 | MCP Suite badge "1 unreachable" in Main, "1" elsewhere | `failing` counts only unreachable sources | The number, with the accessible name "1 tool source failing". |
| 30 | Inline colours outside the token table (avatars, selected tab, hover, scrim, pill borders) | Only tokens may carry colour | New tokens as listed above. |
| 31 | Radii from 4 to 18 | 8, 10 and 14 | Collapse, as listed above. |
| 32 | Logo squares, with brand fills hardcoded | Official assets only | The registry and monogram fallback. These fills are not tokens; they are removed. |
| 33 | No Inbox; Inbox's alert history has no place in the mockups | Inbox shows `/api/inbox/alerts` today | Waiting and missed alerts go on Home, and the history goes to the Activity log (Open Question 10). |
