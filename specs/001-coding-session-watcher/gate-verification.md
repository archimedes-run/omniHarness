# Gate Verification Record — Feature 001

**Date**: 2026-08-21 | **Branch**: `001-coding-session-watcher`

Per the standing convention in [plan.md](./plan.md): **a gate that has never been observed
failing is indistinguishable from a gate that does nothing.** Each of the three gates below was
deliberately broken, the failure observed, and the sabotage reverted. This file exists so the
outcomes survive outside a PR description.

---

## Gate 1 — Core-import and shell-out bans (T014)

Guards FR-019, SC-007, SC-008 (Article I) and research R2 finding 2.
Mechanism: `flake8-tidy-imports.banned-api` in `backend/packages/session_watcher/ruff.toml`.

| Sabotage | Observed |
|---|---|
| baseline, clean tree | `All checks passed!` — exit **0** |
| `import omniharness` | `TID251 'omniharness' is banned: Article I…` — exit **1** |
| `import langgraph` | `TID251 'langgraph' is banned: Article I…` — exit **1** |
| `import subprocess` | `TID251 'subprocess' is banned: R2 finding 2…` — exit **1** |
| `os.system(...)` | `TID251 'os.system' is banned: R2 finding 2…` — exit **1** |

Placement was also confirmed live: the pre-commit ruff hooks matched and reformatted files under
`backend/packages/session_watcher/`, which is the property the placement decision was made to
obtain. A watcher outside `backend/` would have made these gates pass by matching nothing.

**Note on scope**: `extend-select` was narrowed from `TID` to `TID251`. Plain `TID` also enabled
TID252, an unrelated import-style rule, which is noise rather than guarantee.

---

## Gate 2 — Model released, never resident (T030)

Guards Article VI (< 500 MB idle) and FR-008a. Verified under **two distinct regressions**,
because "the model got released" fails in more than one way.

| Sabotage | Observed |
|---|---|
| baseline | 7 passed |
| retain the handle on the summarizer instance | `AssertionError: the model is still reachable after the batch — something retained a strong reference` **and** `model retained on the summarizer instance: [FakeModel …]` |
| cache the model across batches | `AssertionError: model was cached across batches (loader called 1x)` — 3 tests failed |
| reverted | 7 passed |

A related defect was found in the test itself: an earlier version compared `id()` across batches,
which failed because CPython reused the freed address **precisely because release works**. Two
live objects shared an id. The assertion now counts loader invocations.

**Measured idle cost** (documented, not CI-gated — absolute RSS is environment-dependent and a
flaky constitutional gate is worse than a recorded measurement): **12 MB RSS, 0.0% CPU** against
a 500 MB budget, watcher idle with two sessions tracked.

---

## Gate 3 — Startup bound asserted on records opened (T017)

Guards SC-004i, FR-005d/e. The assertion is on `RecordSource.stats.records_opened`, **never on
elapsed time**.

| Sabotage | Observed |
|---|---|
| baseline | 5 passed |
| bypass the mtime filter in `select_candidates` | `AssertionError: opened 5000 records from a 5000-record directory; startup cost is scaling with the directory rather than the window (FR-005e)` — `assert 5000 <= 10` |
| reverted | 5 passed |

The wall-clock smoke bound (SC-004j, `test_startup.py`) is deliberately kept separate and
carries a comment saying it is **not** the mechanism protecting FR-005e — it passes on fast
hardware regardless. `test_startup.py` also asserts `records_opened <= 10` directly, so deleting
the timing test cannot quietly remove the real guard.

---

## Why this file exists

Three of the defects found during this feature were invisible to a passing test suite:

- `KNOWN_INERT_TYPES` was defined and never wired — no linter flags an unused module constant.
- The background refresh loop was implemented and never started — every unit test constructed the
  `Reconciler` directly, so 120 tests passed with the loop dead.
- FR-018a's stdio rationale was false — the T006 spike proved SSE *works* without ever attempting
  to falsify stdio (research R6b).

Gates only help if they can fail. Recording that they were seen to fail is the cheapest available
evidence that they still can.
