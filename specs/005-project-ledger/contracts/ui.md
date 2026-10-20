# Contract: UI (minimal, theme tokens only)

**Design rules** (FR-048, FR-049, and the Memory page's rules carried over):
- Each screen has one solid primary action; everything else is outline or ghost.
- Body text is at normal size. Metadata is small and muted ("Updated 2 days ago").
- No code-styled pills, no decorative icons, and no borders that carry nothing.
- Labels are words: **observed**, **claimed**, **inferred**. Each is a small muted chip, and the chip's text carries the meaning, so it never depends on colour.
- Light and dark use the existing tokens only. The AA-contrast spec covers every new route and state.

## Sidebar
```
OmniHarness
  ＋ New chat
  ◻ Chats
  ◎ Today            3      ← badge = waiting on you (was Inbox's)
  ▤ Projects
  ⚡ Automations
  ⏚ Connections      1      ← failing sources (unchanged)
  ◇ Agents
  …
  ⋯ More •
```

## Today (`/workspace/today`)
```
Today                                   Tuesday 21 October
─────────────────────────────────────────────────────────
Waiting on you · 3
  Approve: decline 2 meetings            Beta · 12 min ago   [Review]
  Claude Code is asking permission       omniHarness · observed
  Workflow "nightly build" failed        2 h ago

Due
  Overdue  Write announcement post       Beta · due Mon
  Today    Waitlist form                 Beta
  Today    10:00 Design review (calendar) Beta

Moved since yesterday
  3 commits in beta-site                 observed · 9:14
  Codex finished its plan (4/4)          claimed · 8:40
  "Landing page" marked done, still changing   inferred
─────────────────────────────────────────────────────────
Calendar isn't connected — connect it in Connections.     (muted, once)
```
- **Empty section**: one muted line ("Nothing due today.").
- **Can't-tell**: one line naming the source and reason ("Can't read coding sessions right now: the watcher isn't answering."). It is never left empty.
- **Loading**: skeleton rows.
- **Primary action**: none. Today is for reading, and every action sits on its item.

## Projects (`/workspace/projects`)
A list of rows: name, one-line why (muted), open and overdue counts, last moved. The primary action is **New project**.

## Project view (`/workspace/projects/[id]`)
```
Beta launch                                         [Add task]  ⋯
Ship the public beta by Dec 1.          active · updated 2 h ago

Goals
  Public beta live          ▓▓▓▓▓▓░░░░ 3/5      Dec 1

Tasks            To do · Doing · Blocked · Done
  T-3  Landing page        doing   you    due Fri   ⚑ done, still changing
  T-4  Waitlist form       to do   Codex  today
Evidence         All · Observed · Claimed      Source ▾
  9:14  commit a1b2c3 "T-3 hero copy"     observed · git
  8:40  Codex marked "Waitlist" done       claimed · codex
Links            2 chats · 1 session · beta-site (repo)
Decisions        Use Resend for the waitlist — cheaper, simple API
```
- **Tasks**: edit and status change happen inline. Status is a select, and changing it is the user's action (FR-013).
- **Flags** (⚑): open their evidence, and have a Dismiss action.
- **Evidence**: rows marked Withheld show the source and time, plus the Withheld sentence.

## Chat cards
- **Project / task proposal**: a title, the exact list of changes, and the actions **Confirm** (solid), **Edit** (outline) and **Decline** (ghost). Edit opens the same fields inline.
- **Automation proposal**: shows "Every weekday at 9:00 (Europe/…)", the rule in small muted mono beneath it, what it will say, and where it goes. It uses the same three actions.
- **Promote todos**: shown on a thread's todo list, as a ghost button that opens a checklist and a project picker.

## Settings → Coding agents (US7)
A switch labelled "Report Claude Code prompts precisely". When turned on, the page shows the exact diff and the one command to run (research R7), then shows the status reported by the receiver (installed / not installed / not seen yet).
