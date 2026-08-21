# Quickstart: Trigger & Scheduler Engine

**Date**: 2026-08-21 | **Plan**: [plan.md](./plan.md)

Runnable validation. Implementation lives in `tasks.md`.

## Prerequisites

- Feature 001's watcher running (`cd backend && uv run python -m session_watcher.server`)
- Gateway running — the engine lives in that process
- A Telegram channel configured

## Setup

Write a rule file per [contracts/rule-schema.md](./contracts/rule-schema.md), then confirm the
engine loaded it:

```bash
curl -s localhost:2026/api/triggers/rules | jq '.rules[].id'
```

---

## Scenario 1 — Blocked session reaches your phone (US1, SC-001/002)

Drive a watched session into a waiting state.

**Expect**: one Telegram message naming the session and its apparent question, within 60 s.

Leave it blocked and wait several cycles. **Expect**: no further message — this is FR-017, and
the failure it prevents is the one that gets the feature muted.

Answer it, then block it again on a *different* question. **Expect**: a new message, because the
fingerprint changed (SC-002a).

## Scenario 2 — Scheduled briefing (US2, SC-003/004)

Schedule a rule a few minutes out. **Expect**: one delivery, once.

Stop the engine, let a scheduled time pass, restart. **Expect**: exactly one delivery, late — not
skipped, not one per missed tick.

## Scenario 3 — Coalescing (US3, SC-005)

Fire three rules inside the window. **Expect**: **one** message containing all three.

## Scenario 4 — Quiet hours (US4, SC-006)

Fire a non-urgent rule inside quiet hours. **Expect**: nothing delivered, suppression recorded
with its reason.

Wait for the window to end. **Expect**: items whose condition still holds are delivered **as one
coalesced message**; a cron item that was suppressed has **expired**, not delivered blind
(SC-006c). A backlog arriving as a notification storm is the specific failure FR-013d prevents.

Mark the rule urgent, fire again inside quiet hours. **Expect**: delivered.

## Scenario 5 — No interruption (SC-007)

Start a long exchange on a rule's thread, fire that rule mid-run.

**Expect**: nothing during the exchange; delivery after.

Now kill the run so it never completes. **Expect**: release at the bound. This is the ordinary
path for a hung run, not an exceptional one (FR-016b) — nothing will ever signal completion.

## Scenario 6 — Hot reload (US5, SC-008/009)

Add, edit, remove rules while running. **Expect**: each takes effect with no restart.

Introduce a syntax error. **Expect**: the previous config stays active and the error is reported.
**A config that fails open is worse than one that fails to load** — nobody notices the first.

---

## Automated checks

```bash
cd backend && uv run pytest tests/trigger_engine/ -v
```

### The three gates

```bash
# Gate 1 — narrowed import ban, BOTH directions
uv run ruff check app/trigger_engine/
uv run pytest tests/trigger_engine/test_no_banned_imports.py -v

# Gate 2 — blast radius
uv run pytest tests/trigger_engine/test_blast_radius.py -v

# Gate 3 — one release path
uv run pytest tests/trigger_engine/test_release_path.py -v
```

### Proving the gates can fail

A gate never observed failing is indistinguishable from one that does nothing.

```bash
# Gate 1, direction A: add `import langgraph.graph` to a scratch file
uv run ruff check app/trigger_engine/          # MUST fail

# Gate 1, direction B: remove the langgraph_sdk exception
uv run ruff check app/trigger_engine/          # MUST fail — the SDK is required
```

**Both directions matter.** A one-directional test lets a later "simplification" restore the glob
or drop the ban, and neither would fail.

```bash
# Gate 2: point a rule at a function that raises, then at one that sleeps forever.
#   The crashing rule MUST NOT stop the engine or any other rule.
#   While the blocking rule hangs, ordinary requests MUST serve with no added latency.
#   If the gateway becomes unresponsive, the isolation is decorative.

# Gate 3: add a second delivery path that bypasses release().
uv run pytest tests/trigger_engine/test_release_path.py   # MUST fail
```

### Idle cost (Article VI, SC-012 — documented, not CI-gated)

```bash
# no rule due for an hour, then:
ps -o rss=,%cpu= -p "$(pgrep -f 'gateway')"
```

Compare against the same gateway without the engine loaded. The delta is the engine's idle cost.
Recorded rather than asserted: absolute RSS is environment-dependent, and a flaky constitutional
gate is worse than a documented measurement.

---

## Verifying the honest-limits behaviour

**Unreachable event source** (FR-029, SC-013): stop the watcher, ask about sessions.

**Expect**: the unreachable condition is observable and no reply states or implies that no events
occurred. Reporting "nothing is happening" when we cannot see is the Article X failure this
requirement exists to prevent — and it is the same one Feature 001 guards with its
empty-versus-unobservable distinction.

**Provenance** (FR-010, SC-014): craft a rule whose prompt text imitates a user confirming a
Tier-3 action.

**Expect**: it cannot satisfy the confirmation. Structure, not content, decides — so no wording
can change the outcome.
