# Quickstart: Read-Only Coding-Session Watcher

**Date**: 2026-08-20 | **Plan**: [plan.md](./plan.md)

Runnable validation that the feature works end to end. Implementation lives in `tasks.md`.

## Prerequisites

- Python 3.12, `uv` (already used by `backend/`)
- At least one Claude Code session run on this machine (records under `~/.claude/projects/`)
- Backend running, either locally or in Docker

## Setup

```bash
cd backend && uv sync
```

Add the SSE entry from [contracts/mcp-tools.md](./contracts/mcp-tools.md) to
`extensions_config.json`, then start the watcher on the **host** (not in a container):

```bash
cd backend && uv run python -m session_watcher.server --port 18101
```

Confirm it appears as `local:session-watcher` in the tool catalog before going further. If it
does not, nothing below will work and the fault is in registration, not the watcher.

---

## Scenario 1 — Roll-up (User Story 1, SC-001)

Start two Claude Code sessions in different projects. Ask, from any channel:

> what are my sessions doing?

**Expect**: one line per session with project, state, and last activity, within 10 seconds.

## Scenario 2 — Blocked session (User Story 2, SC-002)

Drive one session to a point where it asks a question. Ask:

> is anything stuck waiting on me?

**Expect**: only the waiting session named, with its pending question. Per R2 finding 3 this is an
**inference**, so the wording must not claim observation.

Then ask the assistant to answer it. **Expect**: a plain statement that externally-started
sessions are observe-only (FR-015, SC-010). There is no tool to call — verify it does not
pretend otherwise.

## Scenario 3 — Completed vs stalled (SC-004a)

Let one session finish normally; `kill -9` another mid-run. Wait out the inactivity period, then
ask for a roll-up.

**Expect**: the first described as finished; the second as *may have stalled or been killed*.
**The two must not be conflated** — this is the Q1 clarification's whole purpose.

## Scenario 4 — Watcher down (SC-004e, SC-004f)

With sessions running, stop the watcher. Wait past the staleness threshold (90 s), then ask for
status.

**Expect**: a reply stating sessions cannot currently be observed, **leading** with that caveat,
then last-known data with its age. **It must never say "no sessions running"** — that is the
false negative FR-011a exists to prevent, and it is the single most important assertion here.

## Scenario 5 — Sleep/wake (SC-006)

Sleep the machine with a session running; wake it; ask for status.

**Expect**: correct status with no watcher restart and no user action.

---

## Automated checks

```bash
cd backend && uv run pytest tests/session_watcher/ -v
```

### The three gate tests specifically

```bash
# Gate 1 — zero writes, zero core imports
uv run pytest tests/session_watcher/test_zero_writes.py tests/session_watcher/test_no_core_imports.py -v
uv run ruff check packages/session_watcher/     # banned-api: omniharness*, langgraph*

# Gate 2 — model released, not resident
uv run pytest tests/session_watcher/test_summarizer_lifecycle.py -v

# Gate 3 — startup bound on RECORDS OPENED, not elapsed time
uv run pytest tests/session_watcher/test_discovery_window.py -v
```

### Proving the gates can fail

A gate never observed failing is indistinguishable from a gate that does nothing. Confirm each
one bites:

```bash
# Gate 1: add `import omniharness` to a scratch file under packages/session_watcher/
uv run ruff check packages/session_watcher/     # MUST fail
```

For Gate 3, temporarily bypass `RecordSource.select_candidates` so startup scans the whole
directory; `test_discovery_window.py` **must** fail on `records_opened`. If it still passes, the
assertion is on the wrong quantity — most likely elapsed time — and the requirement is unprotected.

### Idle RAM (Article VI — documented, not CI-gated)

```bash
# start the watcher with no sessions active, idle 60s, then:
ps -o rss= -p "$(pgrep -f session_watcher.server)"
```

Record the value. Not asserted in CI: absolute RSS is environment-dependent, and a flaky
constitutional gate is worse than a documented measurement. The deterministic half of Gate 2 is
the weakref assertion above.

---

## Cross-platform

`test_adapter_claude_code.py` includes a fixture directory whose name begins with a hyphen,
reproducing the real `-Users-...` slug. This is not incidental: a leading `-` reads as an option
flag in shell tooling, so it works on the developer's machine and breaks in any shell-out
(FR-020, R2 finding 2).
