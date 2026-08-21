# Gate Verification Record — Feature 002

**Date**: 2026-08-21 | **Branch**: `002-trigger-scheduler-engine`

Per the standing convention: **a gate that has never been observed failing is
indistinguishable from a gate that does nothing.** Each gate below was broken
deliberately, the failure observed, and the sabotage reverted.

This feature is the strongest evidence yet for the convention: **Gate 4 was
configured twice in ways that could not detect the defect it exists for, and
both times only the sabotage revealed it.**

---

## Gate 1 — Article I imports, both directions (T006)

| Sabotage | Observed |
|---|---|
| baseline | `All checks passed!` exit 0 |
| `import langgraph.graph` | `TID251 langgraph is banned` + `TID251 langgraph.graph is banned`, exit 1 |
| `import omniharness` | `TID251 … must not import agent core`, exit 1 |
| **ban `langgraph_sdk` too** | `TID251 langgraph_sdk is banned`, exit 1 — **the SDK became unusable, which is the regression** |

The third row is why both directions matter. A one-directional test passes it
happily, and that is exactly the "simplification" that would restore the glob
and silently re-ban the client turn injection requires.

---

## Gate 2 — Blast radius (T052)

Feature 001 got a crash boundary free from process separation. Sharing the
gateway's process removes it.

| Sabotage | Observed |
|---|---|
| baseline | 8 passed |
| remove the exception barrier | 3 failed, incl. `test_a_crashing_rule_does_not_escape` |
| remove the timeout | **the hanging-rule test was still running after 20 seconds** — an unbounded rule holds the process, which *is* the failure |
| reverted | 8 passed |

---

## Gate 3 — One delivery path (T041)

| Sabotage | Observed |
|---|---|
| baseline | 11 passed |
| add `deliver_now()` bypassing re-check, coalescing and redaction | `AssertionError: 2 call sites invoke destination.deliver in release.py; there must be exactly one delivery path` |
| reverted | 11 passed |

A second structural assertion covers the politeness modules: neither
`quiet_hours` nor `interrupt` may touch a destination — they queue and release
decisions, and only `release()` delivers.

---

## Gate 4 — Wiring (T055). Three attempts, two of them broken.

**Attempt 1 — `vulture --min-confidence 80`.** Both sabotages passed. Vulture
scores unused *functions* at confidence 60; only imports and variables clear 80.
The gate was structurally incapable of seeing the defect it existed for and
would have sat green indefinitely.

**Attempt 2 — `vulture --min-confidence 60`.** Now it sees functions, and
reports **30 findings on a clean tree**, most of them dataclass fields it cannot
model. A thirty-entry whitelist of false positives is how a gate dies: entries
stop being read and a real finding hides among them.

**Attempt 3 — a targeted AST check**, covering public functions, methods **and
module-level constants** (a plain caller-check walks past constants, which was
one of the five observed instances). Its first version *still* missed the
constant case: an assignment target is an `ast.Name`, so a constant counted as
referencing itself.

Final verification:

| Sabotage | Observed |
|---|---|
| unreferenced public function | `{'prune_orphaned_threads': 'threads.py'}` |
| unreferenced module-level constant | `{'ORPHAN_SWEEP_INTERVAL_HOURS': 'threads.py'}` |
| whitelist entry with no reason | `whitelist entries without a reason: ['some_new_thing']` |
| **a whitelist entry whose task is complete** | `{'evaluate_all': 'T056 is complete', 'compute': 'T056 is complete', …}` |

**The gate found a real defect during the build**: `TriggerLoop.run_forever` and
`stop` were fully implemented and nothing started them — the feature-level
instance of the exact shape Gate 4 exists for. That produced task T082
(gateway lifespan registration), which would otherwise have shipped as a library
nobody called.

### The whitelist shrinks by construction

Every deferred entry names the task that wires it, and the gate fails once that
task completes. Observed: **43 → 20 → 13** across phase boundaries. The first
drop was a correction (23 entries exempted things already referenced — an
over-broad whitelist hides a real finding as effectively as a noisy one). The
second happened on its own when T056 closed.

---

## Why this file exists

Defects found during this feature that a green test suite could not see:

- Gate 4 itself, twice, configured so it could not detect anything.
- `TriggerLoop` built and never started.
- Feature 001's waiting window bounded by `inactivity`, so a session blocked
  more than five minutes read as *finished*.
- Feature 001's question detection requiring a trailing `?`, missing the shape
  real assistants actually use — question, then a closing line.
- Three parameters in the injection call that were wrong and returned HTTP 200.

Every one was found by running something. None by the suite.
