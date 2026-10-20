# Feature 006 design parity audit (baseline)

**Date:** 2026-10-20
**Branch:** `006-parity-audit` (from `main`)
**Scope:** every board in `design/` against the app as it runs on `main` today.

## Method

1. **Boards.** I read the markup of every `design/*.dc.html` board. The inline styles give the exact
   values, so every px, radius and colour below comes from the markup. I also checked the rendered
   board screenshots: dark, at each board's canvas size (1440 wide). Chat-Bar-v2 has no screenshot,
   so its values come from the markup alone.
2. **Live app.** I looked at screenshots of today's app in both themes for these pages: Home, New
   chat, a thread, the "+" picker, the four capsule panels, Connections and Settings > Memory. I
   also looked at four pages with no board: Coding sessions, Chats list, Activity log and
   Settings > Safety.
   - **Width note:** the live screenshots were taken in Chrome at about **1600 CSS px** wide,
     because the window could not be resized to 1440. Widths and centring in them are therefore
     about 160 px wider than on the boards. I took sizes from the code, not from the screenshots.
3. **Code.** I checked `frontend/src` for what screenshots cannot show: states, sizes, tokens and
   copy.
4. **Hex to token mapping.** A board hex value maps to a token through the table in
   `AGENT-BRIEF.md`:
   - `#121316` = `bg-background`
   - `#17181C` = `bg-sidebar`
   - `#1C1E23` = `bg-card`
   - `#24272D` = `bg-surface-raised`
   - `#2E3138` = `border-border`
   - `#3A3E46` / `#4A4E57` = `border-border-strong`
   - `#9EA3AD` = `text-muted-foreground`
   - `#C9CCD2` = `text-foreground-2`
   - `#8FA8FF` = `primary`
   - `#2F3A5C` = `primary-subtle`
   - `#F2B65A` = `warning`
   - `#6FD3A0` = success / good
   - `#FF8A80` = destructive / bad

   The token radius scale is `--radius` 10 px: `rounded-lg` 10, `rounded-xl` 14, `rounded-2xl` 18.

### Precedence (which board wins)

1. **Later user decisions** win over every board:
   - The chat bar is **816 px** wide (`max-w-[816px]`).
   - The chat bar is **always at the bottom** of the page, on a new chat too.
   - **Skills are not chips on the bar.** Skills are set in the picker's Skills tab.
2. **`Chat-Bar-v2.dc.html`** overrides the top bar, the capsule and the chat bar on every other
   board. The older floating "Tools" toolbar on Main, Chat and Chat-Picker is superseded, and so are
   their chat bars (8 px-radius chips, 12 px mode pills, 36 px send button).
3. **Every other board** is the reference for its own screen.

**`Home-B.dc.html`** ("Home, Direction B") is in the folder but not in the README's table. Its
content is the same as Main: Waiting on you, Projects (as a table: Project · Next · Progress ·
Due), What moved today (with times), Coding sessions, Upcoming, and a chat bar. Nothing in it is
new. **I treat it as superseded by Main.** The one idea worth keeping is its "Next" column (each
project's next task). Main already shows that as a subline: "Next: sync with Mike Flores, Tue
11:00 AM".

### This is the baseline

Five phases are being built **in parallel right now**:

| Phase | Area |
|---|---|
| A | Home (005 Slice 3) |
| B | Multi-agent chat + picker |
| C | Agent and Skill studios |
| D | Tasks and Automations |
| E | App pages (Connections, MCP Suite, Settings and pages with no board) |

This document is the state **before** those phases land. Each gap names the phase that should
close it. Re-run this audit after the phases merge.

**Size:**
- **S** is under half a day and needs no backend change.
- **M** is about a day, or needs a small read-only backend addition.
- **L** is several days, a new layout, or a new backend capability.

### Summary: gaps per board

| Board | Phase | S | M | L | Total |
|---|---|---|---|---|---|
| Main (Home) | A | 8 | 8 | 0 | 16 |
| Chat-Bar-v2 | shipped | 3 | 0 | 0 | 3 |
| Chat | B | 4 | 3 | 2 | 9 |
| Chat-Picker | B | 2 | 2 | 0 | 4 |
| Panel frame (shared) | C | 4 | 0 | 0 | 4 |
| Agent-Studio | C | 2 | 5 | 4 | 11 |
| Skill-Studio | C | 3 | 4 | 3 | 10 |
| Tasks | D | 2 | 2 | 2 | 6 |
| Automations | D | 0 | 6 | 2 | 8 |
| Connections | E | 3 | 4 | 1 | 8 |
| MCP-Suite (Build) | E | 2 | 2 | 1 | 5 |
| Settings (Memory) | E | 7 | 0 | 0 | 7 |
| **Boards total** | | **40** | **36** | **15** | **91** |
| Live pages with no board | C / D / E | 6 | 4 | 0 | 10 |

---

## Shared: the capsule panel frame (Agents, Skills, Tasks and Automations boards)

The four capsule boards share one dialog frame. Live, that frame is `shell/panel-sheet.tsx`, a
shared shell file. **Phase C** should close these gaps first. They are additive class changes, and
Phase D inherits them.

| Element | Board | Live today | Gap | Phase | Size |
|---|---|---|---|---|---|
| Sheet radius | `border-radius: 18px` | `sm:rounded-xl` = 14 px | Use `rounded-2xl` (18 px) | C | S |
| Sheet surface | `#17181C` (sidebar) on a `#0C0D0F` backdrop | `bg-background` (`#121316`) | Use `bg-sidebar`. The inner cards stay `bg-card` (`#1C1E23`). | C | S |
| Sheet width | `max-width: 1180px` (Agents, Skills, Automations); 1240 px (Tasks) | `max-w-[1240px]` for all | Set the width per panel: 1180 px for three panels, 1240 px for Tasks | C (D for Tasks) | S |
| Sheet header | `padding: 14px 20px`; 18 px icon in `#C9CCD2`; title 15 px/600; × in `#9EA3AD` at 18 px | `py-2 px-5`; 16 px icon; 15 px title; 36 px close | Header padding `py-3.5`; icon `size-[18px] text-foreground-2`. Keep the 44 px close target at narrow widths. | C | S |

Two things in the panel screenshots belong to **Phase E** (Chats list), not to the frame:
- Behind the scrim, the page underneath still shows the legacy header's GitHub icon (top right).
- The chat-list rows also show through, at the bottom edge.

---

## Main.dc.html (Home) → 005 Slice 3, Phase A

Today's Home (`app/workspace/home/page.tsx`) is the **Phase 1 interim** page:
- "Home" (20 px) with a one-line description;
- Waiting on you, split into "Approvals" and "Coding sessions" subsections;
- "While you were away" (alerts, dismissable in the browser).

It has no greeting, no cards, no chat bar, and it is reached only from the New chat badge.

| Element | Board | Live today | Gap | Phase | Size |
|---|---|---|---|---|---|
| Page header | H1 "Good evening, Rishabh" at 28 px/600, `letter-spacing -0.01em`. Subline "Monday, October 19 · 2 things need you" at 14 px muted, 6 px top margin. | H1 "Home" at `text-xl` (20 px) plus "What is waiting on you, from every conversation, coding session and Telegram." | Greeting by time of day, then the date and a count of waiting items. The count comes from `useInboxCount`. When the count can't be read, say "Can't tell what is waiting". | A | S |
| Content column | `max-width: 1040px`; padding 36 / 32 / 24 px; 24 px gap | `max-w-3xl` (768 px), `p-6`, `space-y-8` | Use `max-w-[1040px]` and the board's padding and gaps | A | S |
| "Waiting on you" container | **One** card: `bg-card`, 1 px border, 14 px radius, `padding: 6px 0`. Header "Waiting on you" at 13 px/600 in **warning** colour, padding 12 / 20 / 8. Each item is a row with a 1 px top border, padding 14 / 20, 16 px gap. | An H2 at 16 px, then H3 "Approvals" and H3 "Coding sessions", each a separate block. Approvals render as shadcn Cards. | Merge everything into one card of rows. Remove the subsection headings. The empty state ("Nothing is waiting on you") goes inside the card. | A | M |
| Waiting row (session) | 28 px BrandLogo (radius 8). Meta "Codex · omniHarness@005-project-ledger" at 12 px muted. Body "Asked: "Should I pin the fixture version or rewrite the fixture?"". Then "Observed · 6 min ago" at 12 px muted. Outline button "Open session": 1 px `border-border-strong`, radius 10, padding 9 / 14. | A session card: "Rallion@main" with a pill "Looks like it's waiting on you", an excerpt, and "Observe only · 970c9ce · 1 file changed" | Use the row layout. Use the agent's logo, not a text pill. Say whether the "Asked" text was observed or inferred, in words. Add an "Open session" outline button. | A | M |
| Waiting row (approval) | 20 px shield icon in `#C9CCD2`. Meta "Approval · Google Calendar". Body "Delete event "E2E test, delete me" (Tue 3:00 PM)". Then "Asked in "Calendar cleanup" · expires in 3h 41m". Buttons: "Decline" outline and "Confirm" solid primary (600, radius 10, padding 9 / 14). | `PendingConfirmations`, a full Card per action | Add a compact row variant of `PendingActionCard` for Home. Confirm is the one solid button per row. | A | M |
| "While you were away" | Not on the board | A separate section: alerts that were waiting or not delivered, with a dismiss action | Fold these alerts into the Waiting rows: one row per waiting alert, using the same row layout. Delivered and missed items go to "What moved today". Then remove the section. | A | S |
| Projects card | Grid: `repeat(auto-fit, minmax(320px,1fr))`, 20 px gap. Each card: `bg-card`, 14 px radius, padding 18 / 20, H2 at 13 px/600 muted. Rows show the name (500) with "3 of 7 tasks" right-aligned at 12 px muted. Subline "Feature 005 · Slice 1 in progress", or "Due Fri, Oct 23", or "No task list yet". Progress bar: 6 px track in `border-border`, radius 3, fill in `primary`. | None | Build the card from the ledger: projects, goals and tasks. | A | M |
| Coding sessions card | Rows: 22 px logo (radius 6), `repo@branch` with ellipsis, then the state as a coloured word ("Working" good, "Waiting on you" warning, "Finished 22m ago" muted). Footer "Watcher live · updated 12s ago" at 12 px muted, top border, 10 px top padding. | Only waiting sessions, inside Waiting on you | Build the card from `useSessions()`. Watcher health goes in the footer. If the watcher can't be reached, say so in words. Never show an empty list in that case. | A | M |
| Upcoming card | Rows with a 92 px time column in muted ("Tue 11:00") and the title. | None | Build the card. The backend has no read endpoint for upcoming calendar events (see the data list below). Until it has one, show "Not set up" (no calendar connected) or "Can't tell yet". | A | M |
| What moved today card | Three plain lines: "PR #41 merged: …", "Feature 005 spec approved · Slice 1 started", "Morning brief delivered 8:45 AM on Telegram". | None | Combine trigger firings (delivered), ledger changes and session finishes. There is no single feed for this, so the client has to merge them. Mark each line as observed or reported. | A | M |
| Chat bar on Home | Bar at the bottom of the page, under the cards, with project, agent and integration chips | No chat bar on Home | Add the shipped chat bar at the bottom: `InputBox`, `max-w-[816px]`, centred. The Chat-Bar-v2 look applies, not Main's older bar. | A | M |
| Home vs New chat (decision) | Main marks **"New chat"** as the current sidebar item (`aria-current`, `#24272D`, 500) with the badge on it. The bar sits under the dashboard, so Home is where a new chat starts. | Home is `/workspace/home`, reached only through the badge. New chat is a separate empty page. | **Decide in Phase A.** Option 1: Home is the New-chat landing; the dashboard sits above the bottom bar and goes away once a message is sent. Option 2: keep Home separate and add a sidebar entry for it. The board shows option 1. | A | S |
| Sidebar: New chat badge | Warning pill: 12 px/600, `#121316` text, radius 10, padding 0 7 px, inside the row | Same styling. Shows "?" when the count can't be read. Hidden at 0. | **Matches.** | — | — |
| Sidebar: MCP Suite status | "1 unreachable" at 12 px in **warning** colour, right-aligned in the row | A bare number in `text-destructive` (red). The accessible name is "N failing sources". | Use `text-warning` and the words "1 unreachable" (the count is the failing count). Shared sidebar file: an additive edit. | E | S |
| Sidebar: section label | "Recent" at 12 px muted, padding 0 10 6 | "Recent chats" | Change the copy to "Recent" | A | S |
| Sidebar: footer | 28 px avatar circle in `primary-subtle` with 13 px/600 initial "R". Name "Rishabh". "More" outline button (radius 8, padding 6 / 10). Top border, 10 px padding. | Initials "RI" and name "rishabh.sharma1103" (the account id). "More" button. | Use the display name when there is one, and its first letter for the initial. Today's fallback shows a login id where the board shows a first name. | A | S |
| Sidebar: nav icons | New chat = pencil, Chats = speech bubble, MCP Suite = plug, all 16 px | `MessageSquarePlus`, `MessagesSquare`, `Plug` | Optional: use `PencilLine` and `MessageSquare` to match the board | A | S |

---

## Chat-Bar-v2.dc.html (top bar, capsule, chat bar) → shipped

I confirmed each element against `shell/capsule.tsx`, `input-box.tsx`, `chat-bar/context-chips.tsx`,
`chat-bar/bar-controls.tsx` and `chat-bar/welcome-suggestions.tsx`.

| Element | Board | Live today | Gap | Phase | Size |
|---|---|---|---|---|---|
| Top bar grid | `grid 1fr auto 1fr`, 64 px high, `padding 0 24px`, 16 px gap | `grid h-16 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] gap-4 md:px-6` | **Matches** | — | — |
| Title (left) | 13 px muted | `text-[13px] text-muted-foreground`, truncated | **Matches** | — | — |
| Capsule | 44 px high, radius 22, padding 4, gap 4, `#1C1E23`, 1 px border, shadow `0 6px 20px rgba(0,0,0,.35)` | `md:h-11 rounded-[22px] p-1 gap-1 bg-card border shadow-md` | **Matches** (shadow is the token equivalent) | — | — |
| Capsule buttons | 34 px high, radius 17, padding 0 16, 18 px icon + 14 px label; selected `#2F3A5C`, 500 weight | `md:h-[34px] rounded-[17px]`, `px-4` from 900 px wide, 18 px icon, `text-sm`; selected `bg-primary-subtle font-medium` | **Matches** | — | — |
| Capsule icons | Agents = two people; Skills = sparkle; Automations = bolt; Tasks = check in a rounded square | `BotIcon`, `SparklesIcon`, `ZapIcon`, `ListChecksIcon` | Agents → `UsersIcon`; Tasks → `SquareCheckIcon` (shared `shell/panels.ts`) | C | S |
| Search | 36 px high, radius 10, `#17181C`, 1 px border, 15 px icon, "Search", `⌘K` kbd (12 px, `#24272D`, radius 6) | `md:h-9 rounded-[10px] bg-sidebar border`, 15 px icon, "Search", kbd `bg-surface-raised border-border-strong rounded-md text-xs` | **Matches** (kbd border is `border-strong`, not `#3A3E46`: within the token set) | — | — |
| Chat bar shell | `#1C1E23`, 1 px `#3A3E46`, radius 20, padding 14 / 16 / 12, 12 px gap, shadow `0 10px 30px rgba(0,0,0,.3)` | `bg-card border-border-strong rounded-[20px] px-4 pt-3.5 pb-3 gap-3 shadow-lg` | **Matches** | — | — |
| Heading (new chat) | "What are we working on, Rishabh?" at 30 px/600, `-0.01em`, centred | Same type. Live copy reads "rishabh.sharma1103" because the display name falls back to the account id. | Data, not style: see Home's sidebar footer row | A | — |
| Chips | 34 px high, radius 17, `#24272D`, 1 px `#3A3E46`, 14 px; × button 26 px circle | `h-[34px] rounded-[17px] bg-surface-raised border-border-strong text-sm`; × `size-[26px] rounded-full` | **Matches** | — | — |
| Project chip | Folder icon at 18 px in `#F2B65A` | `FolderIcon text-warning size-[18px]` | **Matches** | — | — |
| Agent chip | 24 px initial circle in the agent's colour | `AgentAvatar` with a deterministic colour. Locked with a lock icon: "A chat keeps the agent it started with". | Matches the look. The lock is a live addition that stays until Phase B allows more than one agent per chat. | B | — |
| Integration chip | 22 px logo (radius 6); unreachable shows a dashed `#F2B65A` border and "Unreachable" at 12 px | BrandLogo 22; `border-warning border-dashed` plus the state in words | **Matches** | — | — |
| Add button | 34 px, dashed `#4A4E57`, "+ Add" 14 px, padding 0 14 0 10 | `h-[34px] rounded-[17px] border-dashed pl-2.5 pr-3.5`; selected while the picker is open | **Matches** | — | — |
| Textarea | 16 px; placeholder "Ask anything · @ to bring in an agent · / for commands" | Same placeholder | **Matches** | — | — |
| Attach | 38 px, radius 10 | `size-[38px] rounded-[10px]` | **Matches** | — | — |
| Mode / Effort / Model | 36 px high, radius 10, `#24272D`, 1 px `#2E3138`, muted label + value + ▾; the model has a 20 px logo | `PILL`: `h-9 rounded-[10px] bg-surface-raised border-border`, label `text-muted-foreground`, BrandLogo 20 | **Matches** | — | — |
| Send | 40 px, **radius 12**, `#8FA8FF`, 18 px arrow | `size-10 rounded-xl` = **14 px**; 16 px arrow | Use `rounded-[12px]` and a `size-[18px]` icon | B | S |
| Starters | 34 px pills, radius 17, 1 px `#2E3138`, `#C9CCD2` 14 px, padding 0 14; copy "Plan my week · What's blocked? · Review a coding session · New automation" | `h-[34px] rounded-[17px] border-border text-foreground-2 px-3.5`; same four labels | **Matches** (position: see exceptions) | — | — |
| Picker placement on a new chat | (Not on this board) | `placement={isWelcomeMode ? "bottom" : "top"}`. Now that the bar is always at the bottom, a picker that opens downward on a new chat may fall off screen. | Check this, and open upward everywhere | B | S |

**Agreed exceptions.** These differ from the board because the user decided so later. They are not
gaps:
1. The bar is **816 px**, not the board's 960 px column.
2. The bar is **at the bottom** on a new chat too. The board centres it vertically. So the heading
   sits in the empty space above (`min-h-[32vh]`), and the **starters sit above the bar** (the
   board puts them below).
3. **No skill chips** and no "+21 skills" overflow button. Skills live in the picker's Skills tab.
   Instead, the live bar shows "+N integrations" overflow, so that an unreachable integration chip
   is never hidden.
4. Always-on sources (filesystem, postgres, session-watcher) show a **lock** and cannot be removed.
   This is a live addition and consistent with the honesty rules.
5. Below 900 px of main area, the capsule shows **icons only**, each with a name and a tooltip.
   Touch targets are 44 px at phone width.

---

## Chat.dc.html (multi-agent chat) → Phase B

The board's own header toolbar and its chat bar are superseded by Chat-Bar-v2. So are its chips:
one "Lead · Researcher · Release manager" chip, and logo-stack chips. Chat-Bar-v2 has one chip
per agent instead.

| Element | Board | Live today | Gap | Phase | Size |
|---|---|---|---|---|---|
| Agents in the chat (header) | Next to the title: avatars 24 px, overlapping by −6 px, each with a 2 px `#121316` ring (L, Rs, RM), then "3 agents" at 12 px muted. Group label "Agents in this chat: Lead agent, Researcher, Release manager". | Top bar shows the title only | Put the avatar stack and the count after the title, in the top bar's left column (shared `capsule.tsx`; additive slot via `useShell`) | B | M |
| Export | (Not on the board) | "Export" ghost button at the top right of the thread | Keep it as a ghost button. Move it into the top bar's right column, before Search, or into a ⋯ menu, so the right column holds one control. | B | S |
| User message | Right-aligned, max 80 %, `#24272D`, radius 14, padding 12 / 16. A leading "@Researcher" in the agent's colour at 500 (Researcher `#8FA8FF`, Release manager `#C9A8FF`). | Human bubble is `w-fit`; mentions are plain text | Bubble tokens: `bg-surface-raised rounded-[14px] px-4 py-3 max-w-[80%]`. Colour @mentions with the agent's avatar colour (`avatarClasses`), contrast-checked in both themes. | B | M |
| Agent message header | 30 px avatar, then the name at 600 and a 12 px muted context line ("Web search · GitHub" for tools used; "OmniHarness project"). 12 px gap. Body directly below, with a 4 px margin. | One anonymous assistant stream: no avatar, no name | Each AI message carries its agent: `AgentAvatar` at 30 px, the name, and a context line (tools actually called, or the project). Needs agent attribution on messages from the backend. | B | L |
| Approval card in the thread | 1 px **warning** border, radius 12, padding 14 / 16, `bg-card`. Header "Needs your approval · Slack" at 13 px/600 warning, with "Expires in 3h 58m" at 12 px muted on the right. Body "I will post the Slice 1 plan to **#omniharness**." Buttons right-aligned: "Decline" outline, "Confirm" solid (radius 10, padding 8 / 14). | `PendingActionCard` (shadcn Card: title and description header, plain border) | Restyle to the board: warning border, a one-line header with the expiry, the actions at the right | B | M |
| @ dropdown | Max 420 px, `#1C1E23`, 1 px `#3A3E46`, radius 14, padding 6, shadow `0 12px 32px rgba(0,0,0,.45)`. Title "Call in an agent" at 12 px muted. Options: 26 px avatar, name, then a 12 px subline ("Project status · GitHub, Calendar" / "In this chat"). Active option is `#24272D` with an "Enter" hint. Last row, after a top border: "+ Create an agent". | `SuggestMenu`: `max-w-[420px] rounded-xl border-border-strong shadow-xl`, title "Call in an agent", "In this chat" hint | Add the "Enter" hint on the active row, a description subline for each agent, and a final "+ Create an agent" row (opens Agent Studio's New agent) | B | S |
| More than one agent per chat | Three agents in one thread, each one called in with @ | One agent per thread. Its chip is locked: "A chat keeps the agent it started with". | Thread membership: add an agent with @ or the picker, remove it with ×. The lead routes messages. Then the agent chips become removable and the lock goes. | B | L |
| Conversation column | `max-width: 820px`, padding 28 / 24 / 0, 22 px gap between messages | `max-w-(--container-width-md)`, `gap-8` (32 px), `pt-8` | Align with the 816 px bar: `max-w-[816px]`, `gap-[22px]` | B | S |
| Typed @mention | "@Ev" in `#8FA8FF` inside the textarea while it is being typed | Plain text | Highlight a mention in progress (overlay or token) | B | S |

---

## Chat-Picker.dc.html ("+" picker) → Phase B

The board's chat bar and header are superseded by Chat-Bar-v2. Two items are the user's own
requests for Phase B: **Connect in place** and the **file chip hover preview**.

| Element | Board | Live today | Gap | Phase | Size |
|---|---|---|---|---|---|
| Popover shell | Above the bar. `#1C1E23`, 1 px `#3A3E46`, radius 14, shadow `0 12px 32px rgba(0,0,0,.45)`, 10 px gap to the bar. | Same placement and look. Width = bar width. | **Matches** | — | — |
| Tabs | Projects · Agents · Integrations · Skills · Files. Padding 8, 4 px gap, bottom border. Each tab: padding 7 / 12, radius 8. Selected: `#2F3A5C` with 500 weight. Others: `#C9CCD2`, no background. | The same five tabs as shadcn `Tabs`. The selected tab shows an outlined box (screenshot), not a `primary-subtle` fill. | Selected tab: `data-[state=active]:bg-primary-subtle font-medium`, no border. Keep the focus ring for keyboard only. | B | S |
| Search | `#24272D`, radius 10, padding 8 / 10, 14 px icon, "Search integrations" | Present. Also shows the line "59 / 125 tools for this model". | **Matches** (the tool-budget line is a live addition: keep) | — | — |
| Integration row | 28 px logo (radius 7), name, status at 12 px ("Live" good), switch 36 × 20 (on `#8FA8FF`, knob `#121316`; off `#24272D` with a `#4A4E57` border, knob `#9EA3AD`) | BrandLogo 28. Status "Live · 14 tools", "Connected", or "Unreachable" with a mono error line. shadcn `Switch`. | Check the `Switch` size against 36 × 20 and the off-state colours. "Connected" (authorised, not yet seen working) vs "Live" (observed working) is an **agreed exception**: it keeps observed and reported apart. | B | S |
| Unreachable row | "Unreachable" in warning, then a "Check" link to MCP Suite | Same, plus a mono error line | **Matches** | — | — |
| Not-connected row | "Not connected" in muted, then a "Connect" link to Connections (leaves the chat) | "Connect" link to `/workspace/connections` | **Connect in place**: open the provider's OAuth (Composio) in a popup. On return, the row becomes "Connected" and its switch turns on, without leaving the chat. If the popup is blocked, say so and offer the link. | B (picker) | M |
| Always-on rows | (Not on the board) | Lock icon with "Always on" | Agreed addition (matches the locked chips) | — | — |
| File chip hover preview | (User request; not on the board) | File chips show a 20 px thumbnail for images, and nothing on hover | On hover or focus of a file chip, show a preview popover with tokens: card, radius 14, padding 12, `max-w-[320px]`. Images: up to 240 px tall. Text: the first ~12 lines in mono 12 px. Otherwise: name, type and size. Esc closes it; it has an accessible name. | B (picker) | M |

---

## Agent-Studio.dc.html (Agents panel) → Phase C

Live: `AgentsPanel` renders `AgentGallery`. That is the header "Agents" / "Create and manage
custom agents with specialized prompts and capabilities.", a "Coding sessions" button, a solid
"New Agent" button, and the empty state "No custom agents yet" / "Create your first custom agent
with a specialized system prompt."

| Element | Board | Live today | Gap | Phase | Size |
|---|---|---|---|---|---|
| Layout | Two panes. Left list: `flex 1 1 230px`, max 250 px, right border, padding 14 / 10, 4 px gap. Right pane: header, tabs, then the content (max 760 px, padding 24 / 28), then the footer. | One column: card gallery or empty state | Rebuild as the two-pane studio | C | L |
| Agent list | First "+ New agent": dashed `#4A4E57`, radius 10, padding 9 / 12, left-aligned, 8 px below. Rows: 26 px avatar, name, padding 8 / 10, radius 10. Current row: `#24272D`, 500, `aria-current`. **Lead agent is listed.** | Custom agents only; the Lead agent is not shown | List the Lead agent (read-only where it can't be edited) and the custom agents | C | M |
| Agent header | 40 px avatar, name at 18 px/600, description at 13 px muted ("Tells you what moved and what's stuck, every weekday at 6:00 PM"). Status pill "Active": 12 px good, 1 px `#2F5A49` border, radius 8, padding 3 / 8. | None | Build the header. Show status only if it is known; otherwise no pill. | C | M |
| Tabs | Overview · Instructions · Tools and skills · Autonomy · Schedule. Padding 16 / 28 / 0, bottom border. Tab: padding 8 / 12, 2 px bottom border (`#8FA8FF` when selected, else transparent). Selected 500 in `#ECEDEF`; others `#9EA3AD`. | None | A real tablist with arrow keys (brief rule) | C | M |
| Overview | 4 cards: `minmax(200px,1fr)`, 12 px gap, `bg-card`, radius 12, padding 14 / 16, 12 px muted label. Cards: "Works on" (projects) · "Uses" (22 px logos + "+ 2 skills") · "Next run" · "On its own it may". Then "Recent runs" rows: 120 px muted time, outcome, link ("Open" / "Review"); 10 px padding, top border. | None | Build it. "Next run", "Recent runs" and "On its own it may" have no backend today: show "Not set up" (no schedule) or "Can't tell yet". | C | M |
| Instructions | A one-sentence bar: `bg-card`, 1 px **`#8FA8FF`** border, radius 12, padding 10 / 12, 16 px sparkle, input, solid "Draft" button (600, radius 9, padding 7 / 12). Textarea: 9 rows, `bg-card`, 1 px `#3A3E46`, radius 12, padding 12 / 14, line-height 1.6. Caption "Drafted from your sentence · edit freely" at 12 px muted. | The system prompt is edited elsewhere (agent pages) | The draft endpoint (Phase C backend), then the textarea. Show the caption only after a draft. "Draft" is the solid button **in this tab**; the footer's Save stays solid too (the board shows both). | C | L |
| Tools and skills | "Integrations" label at 12 px muted. Chips: `bg-card`, 1 px `#3A3E46`, radius 10, padding 6 / 10, 20 px logo, name, status ("Live" good), and a dashed "+ Add". Then "Skills loaded every run": the same chips, text only. | None | Build it with BrandLogo and the live status from tool sources | C | M |
| Autonomy | Intro: "In chat it always asks you first. On a schedule nobody is there to ask, so choose what it may do on its own." Fieldset: radius 12, 1 px `#3A3E46`, legend "May do on its own (reversible)". Three 18 px checkboxes: "Create and update tasks", "Add notes and decisions", "Archive stale tasks". Card: "Always waits for you: sending messages, permanent deletes, calendar changes that notify others." | None | Autonomy grants (Phase C backend). Store them per agent. Unchecked is the default. | C | L |
| Schedule | Card "Weekdays at 6:00 PM · America/New_York" with an outline "Edit" (radius 9, padding 6 / 12). Checkboxes "Send the result to Telegram" and "Show it on Home". | None | Schedule on an agent. Should become an automation row so that Phase D lists it ("Agent · weekdays 6:00 PM"). | C (with D) | L |
| Footer | Top border, padding 14 / 28, right-aligned: "Test run" outline, "Save" solid. Buttons: radius 10, padding 9 / 16. | Not applicable | Build it | C | S |
| "Coding sessions" button | (Not on the board) | In the Agents panel header | Remove it from the panel. Coding sessions are reached from Home's Coding sessions card (title links to `/workspace/sessions`) and the ⌘K palette. | C | S |

---

## Skill-Studio.dc.html (Skills panel) → Phase C

Live: `SkillsPanel` renders `SkillSettingsPage`. That is "Agent Skills" / "Manage the configuration
and enabled status of the agent skills.", Public / Custom tabs, a solid "Create skill", and one card
per skill with a long description and an enable switch.

| Element | Board | Live today | Gap | Phase | Size |
|---|---|---|---|---|---|
| Layout and list | Two panes, as in Agent Studio. "+ New skill" dashed. Rows: text only, padding 9 / 12, radius 10. Current row `#24272D`, 500. | One column of cards | Rebuild as the two-pane studio | C | L |
| On / off | (Not on the board) | A switch on every card | Keep enable/disable in the detail header (right side), using the board's Automations on-switch pattern: "On" at 13 px + a 40 × 22 switch | C | S |
| Skill header | Name at 18 px/600. "Used by Evening wrap-up and Release manager" at 13 px muted. | None | "Used by" can be derived from the agents' skill lists. If no agent lists any skills: "Not used by a custom agent yet". | C | M |
| Tabs | Details · Instructions · Files · Test (same tab style as Agent Studio) | Public / Custom only | A real tablist | C | M |
| Details | "Name" label at 13 px. Input: max 480 px, `bg-card`, 1 px `#3A3E46`, radius 10, padding 10 / 12. "When should it be used?" textarea: 3 rows, radius 12, plus an outline "Draft" (sparkle 14 px, radius 9, padding 5 / 10, 13 px). Help text: "This sentence decides when the skill loads. Name the situations, not the steps." at 12 px muted. | The description shows only on the card | Build it. Public skills are read-only: inputs disabled, with "Built-in: read only". | C | M |
| Instructions | Draft bar (`#3A3E46` border, outline "Draft", placeholder "Describe it in one sentence and let it draft the instructions"). Editor: 1 px `#3A3E46` border, radius 12. Toolbar: B · I · H · List · `</>` on `bg-card`. Body on `bg-background`, padding 14 / 16, min height 220 px. | The custom skill editor exists (`PUT /skills/custom/{name}`) but is not shown like this | Put the existing editor in this frame. The draft uses Phase C's draft endpoint. | C | M |
| Files | File rows: mono 13 px name, 12 px muted size, `bg-card`, radius 10, padding 10 / 14. Dropzone: dashed `#4A4E57`, radius 12, padding 28, "Drop scripts, references or templates here, or choose files". | None. There is no skill-files endpoint. | Needs a backend endpoint to list and upload skill files. Until then, show "Not set up". | C | L |
| Test | "Try messages and see whether this skill gets picked." Rows: radius 10, quoted message, then "Loads" (good) or "Doesn't load" (muted). Input "Type a test message". | None. There is no endpoint. | Needs a backend "would this skill load" check. Until then, show "Not set up". Never show a guessed "Loads". | C | L |
| Footer | "Cancel" outline + "Save skill" solid | Not applicable | Build it | C | S |
| Public vs Custom | (The board shows one list) | Public / Custom tabs | Use one list with a 12 px muted "Built-in" marker on public skills. The tabs go. | C | S |

---

## Tasks.dc.html (Tasks panel) → Phase D

Live: `TasksPanel` renders `ProjectsPage`. That is "Projects" / "What you are working toward, with
its goals, tasks and decisions.", a solid "+ New project", and the empty state "No projects yet.
Tell the assistant what you're working on, or create one here."

| Element | Board | Live today | Gap | Phase | Size |
|---|---|---|---|---|---|
| Layout and project list | Left pane `flex 1 1 240px`, max 260 px. "+ New project" dashed. "All open tasks" with a muted count (14), a divider, then each project with its open count on the right. Current row: `#24272D`, 500. | One column of project cards | Rebuild as two panes. The counts come from ledger tasks. | D | L |
| Project header | H2 at 20 px/600. "Goal: Feature 005 Project Ledger shipped · 3 of 7 tasks done" in muted. View nav: Tasks · Evidence · Decisions · Chats (padding 6 / 10, radius 8, 13 px; current `#24272D`). | `project-view.tsx` on `/workspace/projects/[id]` | Bring the project view into the right pane with this header and nav | D | M |
| Progress | 6 px bar, radius 3, `border-border` track, `primary` fill | Not in this form | Add the bar | D | S |
| Add a task | Bar: `bg-card`, 1 px `#3A3E46`, radius 12, padding 8 / 10. Placeholder "Add a task, or describe a goal and let the agent break it down". Outline "Break down" with a 14 px sparkle. | Task adding lives inside the project view | Add the bar. "Break down" needs an agent call. Hide that button until the call exists, rather than show a dead one. | D | M |
| Task groups and rows | Groups: "In progress", "To do", "Done this week" (h3 12 px/600 muted). Row: 18 px checkbox (`accent-color` primary), title, 12 px muted evidence line ("Observed: 4 commits today on 005-project-ledger · Reported by Codex: 5 of 7 steps"). Owner chip: radius 7, 1 px `#4A4E57`, 12 px, 18 px logo + "Codex" / "Claude Code" / "You". Then the state ("Waiting on you" warning, "Working" good) or the due date ("Wed, Oct 21" / "No date"). Done rows: muted, title struck through. | Task list in `project-view.tsx`, without owner chips or evidence lines | Rebuild the rows. Evidence must say "Observed" or "Reported by <agent>" in words. Owners come from task↔session links. If there is no link, show no owner chip (not "You"). | D | L |
| Empty state | (Not on the board) | Copy above | Keep the copy. Put it in the right pane. | D | S |

---

## Automations.dc.html (Automations panel) → Phase D

Live: `AutomationsPanel` renders `AutomationsPage`:
- "Automations" / "What I do without being asked: scheduled messages, alerts, and workflows."
- "Scheduled and alert rules": cards with the raw rule id ("blocked-session", "morning-briefing"),
  "When: waiting-on-user", "Last evaluated / Last fired" timestamps, a "Has fired" pill and a switch.
- "New automation": three template cards (Morning brief, Blocked coding session, Weekly review).

| Element | Board | Live today | Gap | Phase | Size |
|---|---|---|---|---|---|
| Layout and list | Left pane `flex 1 1 250px`, max 280 px. "+ New automation" dashed. Rows: name (500) + a 12 px muted schedule ("Weekdays 8:45 AM", "When a session waits on you", "Agent · weekdays 6:00 PM"). An 8 px dot: filled good = On, ring `#9EA3AD` = Off, with `aria-label`. Footer tip at 12 px muted: "Tip: in any chat, say "every weekday at 9, brief me" to create one." | One column of rule cards plus templates | Rebuild as two panes | D | L |
| Names and schedules in words | "Morning brief", "Blocked session alert", "Weekly review" | Raw ids and "When: waiting-on-user" | Show the rule's title, with its id only in Edit. Describe the schedule in words (cron → "Weekdays at 8:45 AM"; event → "When a session waits on you"). | D | M |
| Detail header | Name at 18 px/600. "Weekdays at 8:45 AM · America/New_York · to Telegram" at 13 px muted. "On" at 13 px + a 40 × 22 switch (knob 18 px). | Switch on each card | Build the header | D | M |
| Tabs | History · Edit (underline style) | Edit is a separate page, `/workspace/automations/[ruleId]` (`RuleForm`) | Put `RuleForm` in the Edit tab | D | M |
| Stat cards | `minmax(160px,1fr)`, 12 px gap, radius 12, padding 12 / 14. "Next run" ("Tomorrow 8:45 AM") · "Last checked" ("2 min ago") · "Quiet hours" ("10 PM to 7 AM"). | "Last evaluated" timestamp only | Last checked = `last_evaluated_at` (relative time). Next run: there is no backend field, so Phase D adds one; until then "Can't tell yet". Quiet hours come from the trigger engine config. | D | M |
| History rows | 130 px muted time column. Outcome as a coloured word plus a sentence: "**Delivered** on Telegram" (good); "**Held, then delivered** at 9:02 AM. You were mid-conversation." (accent); "**Delivered with 1 other** (Blocked session alert), one message" (accent); "**Failed**: the agent run errored (model timeout). Not retried." (bad). Link "Open thread" or "Details". | Firings appear only in Settings > Activity log, with raw states and ids | History wording (Phase D backend): map each firing state and reason to these sentences. Batched firings use `BatchMember`. | D | M |
| **Create from scratch** (user request) | "+ New automation" | `/workspace/automations/new` works only with `?template=`. Without one it says "Pick a starting point / Choose a template on the Automations page." | "+ New automation" opens an empty Edit tab: name; trigger (schedule, or an event such as a session waiting on you); what to send; where to deliver; quiet-hours override. The templates become optional "Start from…" chips at the top of that form. The backend `POST /rules` already takes a full rule. | D | L |
| Agent schedules in the list | "Evening wrap-up · Agent · weekdays 6:00 PM" | Not applicable | List the agent schedules from Phase C here | D (after C) | M |

---

## Connections.dc.html (MCP Suite > Connected) → Phase E

Live: `/workspace/connections`. That is "Connections" / "The apps and servers the agent's tools
come from, and whether each is working.", a segmented "Connected | MCP Suite", then "Apps" as
full-width rows (name, a "Live" or "Not configured" pill, a "Disconnect" or "Connect" button, and
"Connected. A conversation must select it to use it.").

| Element | Board | Live today | Gap | Phase | Size |
|---|---|---|---|---|---|
| Title and copy | H1 "MCP Suite" at 24 px/600; "Where your agents' tools come from, and whether each one works right now." in muted, 4 px top margin. Content max 1040 px, padding 32 / 32 / 40, 22 px gap. | "Connections" + different copy | Use the board's copy. The sidebar item already says "MCP Suite". | E | S |
| Primary action | "Browse apps" solid (600, radius 10, padding 9 / 14), top right | None | Add it. It scrolls to Apps and focuses the search, or opens a catalogue of apps that are not connected. | E | M |
| Tabs | Connected · Build, underline style (padding 8 / 12, 2 px accent) | Segmented pills "Connected · MCP Suite" | Use the underline tablist, and rename the second tab "Build" | E | S |
| Count pills | "**5** live" (good), "**1** unreachable" (warning, border `#5A4628`), "**3** not connected" (muted). `bg-card`, radius 10, padding 8 / 12, 600 numbers. | None | Compute from `/tool-sources`. If it fails, show "Can't tell" instead of zeros. | E | S |
| Needs-attention card | `bg-card`, 1 px **warning** border, radius 14, padding 14 / 18. 32 px icon tile. "session-watcher can't be reached". "Agents can't see your coding sessions until it's back." with mono 12 px "connection refused · host.docker.internal:18101". Buttons: "View log" outline, "Retry" **warning-filled** (`#F2B65A`, `#121316`, 600). | None | One card per failing source, using `last_error` (or "Withheld" when redacted). "Retry" has no backend: `/tool-sources` is GET only (see the data list). | E | M |
| Apps filter row | "Apps" at 15 px/600. Filter chips "All" (selected: `#ECEDEF` background, `#121316` text) · "Productivity" · "Communication" · "Dev tools" (radius 16, padding 5 / 12, 13 px, 1 px `#3A3E46`). Search on the right: min 200 px, radius 10. | None | Add search. Add categories only if the toolkit metadata has them; otherwise leave the chips out. | E | M |
| App cards | Grid `repeat(auto-fill, minmax(300px,1fr))`, 14 px gap. Card: `bg-card`, radius 14, padding 16 / 18. 36 px logo (radius 9), name (500), 12 px muted description, status ("Live" good). Footer with a top border: "On in new chats" (13 px `#C9CCD2`), a 36 × 20 switch, and ⋯ options. Not connected: `bg-sidebar`, **dashed** `#3A3E46` border, full-width outline "Connect". | Full-width rows, no logos, "Live" pill, "Disconnect" button | Rebuild as cards with BrandLogo. Disconnect moves into ⋯. "On in new chats" has no backend default (see the data list), so hide the switch until it exists. | E | L |
| MCP servers table | "MCP servers" at 15 px/600. One `bg-card` radius-14 box. Rows: padding 12 / 18, bottom border. Mono 13 px name (flex), "Local · SSE" (90 px), "42 tools" / "— tools" (70 px), status (90 px: "Unreachable" warning, "Live" good, "Off" muted). " · built by an agent" tag at 12 px muted. | Server rows in the legacy style | Rebuild as the table. Columns wrap to two lines on narrow screens. | E | M |

---

## MCP-Suite.dc.html (MCP Suite > Build) → Phase E

Live: the "MCP Suite" tab renders `components/workspace/mcp/mcp-suite.tsx`, a legacy page:
- an H1 "MCP Suite" with a solid "+ New" button to `/workspace/mcp/new` (a name, description and
  template form);
- "Connected Toolkits" and "Agent-Built Servers" (Title Case);
- a "Search your MCPs..." box and a `<select>` "All Statuses / Deployed / Starting / Stopped /
  Not Running".

| Element | Board | Live today | Gap | Phase | Size |
|---|---|---|---|---|---|
| Build card | `bg-card`, radius 16, padding 22 / 24, 16 px gap. H2 "Need a tool that doesn't exist yet?" at 17 px/600. Describe bar: `bg-background`, 1 px **accent** border, radius 12, padding 10 / 12, 16 px sparkle, placeholder "Describe it, e.g. "check my Devpost submissions and their judging status"", solid "Build it" (radius 9, padding 8 / 14). | A separate "/mcp/new" form | Replace it with the inline describe-and-build card, which starts the sandbox build (Phase E backend flow) | E | L |
| Three steps | `ol` grid `minmax(220px,1fr)`, 12 px gap. 24 px numbered circles (`#24272D`, 12 px/600). "You describe it / One sentence is enough" · "An agent builds and tests it / In a sandbox, away from your data" · "You approve its first run / Keys stay hidden from the model". | None | Add them (static copy) | E | S |
| Server list and detail | "Your MCP servers" at 15 px/600. List box `flex 1 1 320px`, radius 14, rows padding 14 / 16: mono 13 px name + 12 px muted "Built today · 3 tools"; status "Needs approval" (warning) / "Live" (good) / "Failed" (bad); current row `#24272D`. Detail `flex 2 1 420px`. | A grid of cards. The detail is a separate page (`/workspace/mcp/[id]`). | Two columns: list and detail. Below 760 px, stack them. | E | M |
| Detail content | Mono 15 px title. Pill "Waiting for your approval": warning, 1 px `#5A4628`, radius 8, padding 2 / 8. Description in `#C9CCD2`. Checklist: ✓ good / ● warning — "Scaffolded server, 3 tools: …", "Tests passed in sandbox: 5 of 5", "Uses secret DEVPOST_TOKEN: stored, never shown to the model", "First real run needs your approval". Actions on the right: "View code" outline, "Discard" outline, "Approve and turn on" solid. | `mcp-server-detail.tsx`: code, secrets, test and deploy tabs | Lead with the checklist and actions, built from `/build`, `/secrets/info`, `/test` and `/approve`. The existing code and secrets views open from "View code". | E | M |
| Legacy controls | No status `<select>`, no "Agent-Built Servers" heading | Present | Remove them. Use sentence case. Statuses in words. | E | S |

---

## Settings.dc.html (Settings > Memory) → Phase E

Live: a settings sub-nav (with icons) and Memory, which has a "Summary | Facts 84" segmented
control, "+ Add fact" (solid), ⋯, and summary cards (Work, Personal, Top of mind) with "Updated …"
lines.

| Element | Board | Live today | Gap | Phase | Size |
|---|---|---|---|---|---|
| Settings sub-nav | Column `flex 1 1 220px`, max 240 px, right border, padding 24 / 12. Heading "Settings" at 18 px/600. Items: padding 8 / 10, radius 8, no icons. Order: **Account, Memory, Safety, Notifications, Activity log, Appearance, About**. Current `#24272D`, 500. | Icons on every item. Order: Safety, Activity log, Account, Appearance, **Notification**, Memory, Tools, Skills, About. | Use the board's order and copy ("Notifications"). Drop the icons. "Tools" goes last, before About. "Skills": see the next row. | E | S |
| Settings > Skills | (Not in the board's list) | Present; it is also what the Skills capsule panel shows today | Once Phase C ships the studio, redirect Settings > Skills to the capsule panel and remove it from the list | E (after C) | S |
| Memory header | H1 "Memory" at 24 px/600. "What OmniHarness has learned about you. Edit anything that's wrong." "Add fact" solid (no icon) + ⋯ outline (aria "More memory actions: import, export, clean up, clear"). | "OmniHarness automatically learns from your conversations in the background. …"; "+ Add fact"; ⋯ | Use the board's copy; drop the plus icon | E | S |
| Memory tabs | "Summary" · "Facts · 38", underline style | Segmented pill "Summary / Facts 84" | Use the underline tablist and the "Facts · N" format | E | S |
| Summary cards | `bg-card`, radius 14, padding 16 / 18, 8 px gap. H2 at 15 px/600 with an accent "Edit" text button on the right. Body in `#C9CCD2`. "Updated 2 hours ago" at 12 px muted. "Show more" muted text button. | Cards present, with a smaller heading. No per-card "Edit" seen. | 15 px/600 heading, an "Edit" text button per card, body in `text-foreground-2` | E | S |
| Stale marker | "Updated 4 months ago · **may be out of date**" with the phrase in **warning** colour | The phrase is present, in muted | Use `text-warning` on the phrase | E | S |
| Sidebar "More" while in Settings | `aria-expanded="true"`, `#24272D`, 1 px `#4A4E57` | Plain | Show a pressed state on More while a Settings page is open | E | S |

---

## Live pages with no board

No new layouts. Each page below takes on the Graphite look from parts the boards already define:

**Frame**
- The sidebar and the Chat-Bar-v2 top bar (title on the left, capsule, Search) on every page.
- The page header: H1 24 px/600, then a muted 14 px subtitle with 4 px top margin. Content max
  1040 px (760 px for forms and settings), padding 32 / 32 / 40, 20–22 px between sections.

**Containers**
- **Section heading:** 15 px/600 (MCP Suite "Apps"). Group heading: 12–13 px/600 muted (Tasks
  groups).
- **Summary card:** `bg-card`, 1 px `border-border`, radius 14, padding 16 / 18 (Settings).
- **Row list:** one `bg-card` radius-14 box. Rows padding 12 / 18 with a 1 px divider. Mono 13 px
  for ids and paths. State as a coloured **word** on the right, not a pill (MCP servers table).
- **Time-and-outcome row:** a 120–130 px muted time column, a coloured outcome word plus a
  sentence, and a link on the right (Automations history).

**Controls**
- **Tabs:** underline style, padding 8 / 12, 2 px `primary` bottom border, real tablist.
- **Inputs:** `bg-card`, 1 px `border-border-strong`, radius 10, padding 10 / 12, label 13 px
  (Skill Studio).
- **Switches:** 36 × 20 (or 40 × 22 in a header).
- **Buttons:** radius 10, padding 9 / 14, one solid primary per screen, the rest outline
  (`border-border-strong`) or ghost.

| Page | Today | How it takes on Graphite | Phase | Size |
|---|---|---|---|---|
| **Coding sessions** (`/workspace/sessions`) | Header + "Watcher live." + a paragraph. Rows are bordered cards with pill badges ("Working", "Finished", "Looks like it's waiting on you"), an excerpt, "Observe only · sha", and "Tasks 3 of 3" bars. | Page header ("Coding sessions" + subtitle). Watcher health as the 12 px muted line from Main's sessions card ("Watcher live · updated 12s ago"), at the top. Sessions in a **row list**: 22 px BrandLogo, mono `repo@branch`, the state as a coloured word ("Working" good, "Waiting on you" warning, "Finished 22m ago" muted). Expanding a row shows the excerpt and the todo progress as the 6 px bar (radius 3). Observed and reported stay in words ("Observed · 6 min ago"). Reached from Home's Coding sessions card title and ⌘K, not from the Agents panel. | E | M |
| **Chats list** (`/workspace/chats`) | Legacy header: a "Workspace > Chats" breadcrumb and a GitHub icon. Full-width search with an accent ring. Plain rows. | Remove the legacy breadcrumb and GitHub icon: the top bar title says "Chats". Search input in the input style, max 760 px. Chats in a **row list**: title 14 px/500, "22 days ago" 12 px muted, and the overlapping 24 px agent avatars (Chat board) for multi-agent chats. | E | S |
| **Activity log** (Settings > Activity log) | "Automation firings" cards. Raw rule ids, ISO-like timestamps, and thread uuids ("watcher · 2fa2e75…"). Pill states ("Suppressed", "Delivered", "Held"). | Settings sub-nav + page header. Day group headings (12 px/600 muted). **Time-and-outcome rows** with the same sentences as the Automations history ("Delivered on Telegram", "Held, then delivered at …", "Suppressed: quiet hours 22:00–07:00"). Rule title instead of id. Ids and uuids only under a "Details" disclosure, in mono 12 px muted. | E | M |
| **Settings > Safety** | "Check a tool's tier" (input + solid "Check"), "What I can't do", and "Rules in force": mono tool names with grey and red "Tier N" pills. | Page header. "Check a tool's tier" in a summary card with an input and an **outline** "Check" (this page needs no solid button). "What I can't do" items as summary cards (15 px/600 title, body in `text-foreground-2`). "Rules in force" as a **row list**: mono 13 px tool name; tier as a coloured word (Tier 1 muted, Tier 2 accent, Tier 3 warning, blocked in bad colour). The policy file path in mono 12 px muted. | E | S |
| **Settings > Account / Appearance / Notifications / Tools / About** | shadcn forms and sections, each in its own style | Sub-nav as on the board. Each section is a stack of **summary cards**. Form fields in the input style. Switches 36 × 20. Choice groups (theme, language) as underline tabs or a radio list, not segmented pills. **Tools:** a row list in the MCP-servers style (mono name, source, status word). **About:** one summary card. | E | M |
| **Policy** (`/workspace/policy`) | A redirect to Settings > Safety | Nothing to style. Keep the redirect. | — | — |
| **Tool sources** (`/workspace/tool-sources`) | A redirect to `/workspace/connections` | Nothing to style. Keep the redirect. Its data feeds the count pills and the MCP servers table. | — | — |
| **MCP server detail** (`/workspace/mcp/[id]`) | Large legacy page: header, tabs, code viewer, secrets, an "Ask the agent to fix, extend, or explain…" box, "Not set" labels | The **Build detail** pattern: mono 15 px title, warning status pill (radius 8), ✓/● checklist, actions on the right. Code in a `bg-card` radius-14 box, mono 13 px. Secrets as a row list (name in mono; "Stored" / "Not set" as words; never the value). The fix box as the one-sentence draft bar (accent border, radius 12). Tabs underline style. | E | M |
| **Projects** (`/workspace/projects`, `/[project_id]`) | Projects page and project view (the same thing the Tasks panel shows) | The same two-pane layout as the Tasks board, rendered in the page frame: the panel's content, not a second design. A deep link to `/projects/[id]` opens it with that project current. | D | S |
| **Automations rule editor** (`/workspace/automations/[ruleId]`, `/new`) | Its own page: a "← Automations" link, H1 at 20 px, `RuleForm` | Becomes the **Edit tab** of the Automations panel. The route renders the same pane in the page frame. Fields in the input style. Footer with a top border: "Cancel" outline + "Save" solid. `/new` with no template opens a blank form (create from scratch). | D | S |
| **Agents / new** (`/workspace/agents/new`) | Its own creation page | Becomes "+ New agent" in Agent Studio, opening on the **Instructions** tab with the one-sentence draft bar. The route renders the studio pane with a new agent selected. | C | S |
| Confirmations, Inbox, Triggers, Workflows | Confirmations is a list; Inbox redirects to Home; Triggers and Workflows are legacy pages | Confirmations uses the Home **approval row**, in a row list. Triggers should redirect to Automations. Workflows uses the row list and the page header until it is retired. | A / D | S |

---

## Data the boards show that the backend can't supply today

Until each of these exists, render **"Not set up"** (the feature has nothing configured) or
**"Can't tell yet"** (it exists but can't be read). Never show a number or a sample value.

1. **Home: Upcoming.** There is no read endpoint for upcoming calendar events. The calendar is only
   a trigger source inside the engine.
2. **Home: What moved today.** There is no single "moved" feed. It has to be merged from firings,
   ledger changes and session finishes. PR merges aren't recorded at all unless a session or the
   GitHub connector reports them.
3. **Display name** ("Good evening, Rishabh", the sidebar footer, the new-chat heading). Today the
   fallback is the account id. Without a set name, use "Good evening" with no name.
4. **Waiting row: "Asked: "…"".** The session's exact question is inferred from its last message.
   Label it "inferred", or show the excerpt.
5. **Agent Studio:**
   - status ("Active");
   - "Next run";
   - "Recent runs";
   - "On its own it may" (autonomy grants);
   - Schedule;
   - "Send the result to Telegram" / "Show it on Home".

   None of these exist yet. Grants and drafts are in Phase C's backend scope.
6. **Skill Studio:**
   - "Files" (no endpoint to list or upload skill files);
   - "Test" (no "would this skill load" check);
   - "Used by" (only derivable when agents declare their skills).
7. **Tasks:**
   - owner chips and "Reported by Codex: 5 of 7 steps" (need task↔session links; the todos are in
     the sessions view);
   - "Break down" (needs an agent call);
   - due dates (only where tasks carry one).
8. **Automations:**
   - **Next run** (no field on `RuleView`);
   - the hold reason in history ("You were mid-conversation"), unless the firing records it;
   - agent-run failure detail ("model timeout").
9. **MCP Suite > Connected:**
   - app descriptions and categories (only if the toolkit metadata has them);
   - **"On in new chats"** (no per-app default);
   - **Retry** and **View log** for a failing source (`/tool-sources` is read-only);
   - transport labels ("Local · SSE"), unless read from config.
10. **MCP Suite > Build:** "Tests passed in sandbox: 5 of 5" counts. Show them only if the build
    status reports them; otherwise "Tests passed" / "Can't tell yet".
