# Quickstart: validating the Project Ledger

How to check, end to end, that each story works in production. Contracts: [ledger-api](contracts/ledger-api.md), [watcher](contracts/watcher.md), [ui](contracts/ui.md).

## Prerequisites
- `make daily` running from this branch.
- `~/.codex` mounted read-only on the watcher. It is in the tracked compose file; `docker inspect omni-harness-session-watcher` shows the mount.
- One test repository linked under `/host/repos/<name>` (read-only).

## US1: capture from chat
1. In a new chat: "I'm launching the beta by Dec 1: landing page, waitlist, announcement."
2. Expect a proposal card listing one project, one goal and three tasks. Edit a title, then Confirm.
3. Open Projects → Beta. The items match the edited card, and the chat is linked.
4. In another chat, ask the agent to plan something, so it makes a todo list. Promote two items to Beta. They appear as tasks linked to that thread.

## US2: Today
1. Open Today. Waiting on you shows what the Inbox showed, with the same count as the badge.
2. Stop the watcher (`docker stop omni-harness-session-watcher`). Moved says sessions can't be read, rather than showing nothing. Start it again.

## US3: Claude and Codex
1. Run a short Codex session in the linked repository that uses a plan. Run Claude Code in another folder.
2. Ask the assistant to "list coding sessions". Both appear, labelled by agent, through the same tool.
3. Link the Codex session to task T-4. Its plan progress appears as **claimed** evidence, and the files it changed as **observed**.
4. Mark T-3 done, then edit one of its declared files. T-3 shows "done, but still changing".

## US4: git, workflows, calendar
- Commit "T-3 hero copy" in the linked repository. It appears once on T-3, observed.
- Assign a workflow to T-4 and run it. Its outcome appears once.
- Disconnect the calendar. The calendar section says it is not connected.

## US5: automations from chat
- "Every weekday at 9, brief me on the beta." Confirm the card. The automation appears in Automations and is valid.

## US6: ledger-aware triggers
- Make a task overdue. One alert arrives, at most, and none during quiet hours.

## US7: hooks (optional)
- Settings → Coding agents → turn on. Run the shown command. Trigger a permission prompt in Claude Code. The session shows waiting on you as **observed**. Run the uninstall command, and `~/.claude/settings.json` is byte-identical to the backup.

## Automated
- `make test` (backend, no config.yaml) and `pnpm test`.
- `npx playwright test tests/rendering`: today, projects, sidebar and contrast.
- Gates: the wiring gate (zero new unwired entries), the watcher tool-surface snapshot, and zero writes to sources.
