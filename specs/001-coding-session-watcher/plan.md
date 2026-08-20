# Implementation Plan: Read-Only Coding-Session Watcher

**Branch**: `001-coding-session-watcher` | **Date**: 2026-08-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-coding-session-watcher/spec.md`

## Summary

A host-resident process observes Claude Code's local session records, maintains an in-memory
registry of sessions and their states, and exposes two read-only tools to the agent as an **SSE
MCP server** declared in `extensions_config.json`. The agent answers status questions from any
channel; the watcher never writes to what it observes and never acts on a session.

The corrected integration point (spec clarification 6) is the load-bearing technical decision: the
gateway has no external tool-registration API, so the watcher is an MCP server — which satisfies
Constitution Article I more strongly than the originally-assumed design, since a separate process
speaking a standard protocol imports nothing from core by construction.

## Technical Context

**Language/Version**: Python 3.12 (`requires-python = ">=3.12"`, matching `backend/pyproject.toml`)

**Primary Dependencies**: `mcp` (SSE server transport; already used in-repo by
`tools/composio_mcp_server.py`), `watchdog` (**new dependency** — filesystem change notification
per FR-022), `uvicorn` + `sse-starlette` (already present). No dependency on
`omniharness-harness` — that absence is enforced, not merely intended (see Gate 1).

**Storage**: In-memory registry only. No database, no cache file, no persistence across restarts.
Session records are read from the observed agent's own directory and never copied.

**Testing**: `pytest`, in `backend/tests/`, matching existing project layout and conventions.

**Target Platform**: Host process on macOS and Windows (FR-020, FR-021). Explicitly *not*
containerised — this is the reason stdio transport is excluded (FR-018a).

**Project Type**: Host-resident sidecar exposing an MCP tool surface. Not a web service, not a
library consumed in-process.

**Performance Goals**: First status query answerable within 5 s of launch regardless of history
size (SC-004j). State change reflected within 10 s (SC-004). Roll-up answered within 10 s
(SC-001).

**Constraints**: Near-zero idle CPU and negligible idle RAM contribution (Article VI, FR-022).
Zero writes to observed files (FR-019). Records opened at startup scale with the recency window,
not the directory (FR-005e).

**Scale/Scope**: Tens of live sessions; session-history directories of several thousand records.
Only the 24 h window (plus stickily-held live sessions) is ever parsed.

## Constitution Check

*GATE: evaluated before Phase 0, re-evaluated after Phase 1 design.*

| Article | Requirement | Design response | Status |
|---|---|---|---|
| I — Gateway-only | No core imports, no reaching into other modules | Separate process, separate uv package, MCP protocol boundary. Import ban enforced by ruff `banned-api` + a test. | **PASS (strengthened)** |
| II — Three-tier policy | Every tool classified before dispatch | Both tools are Tier 1 (read), declared as such (FR-014). No Tier 2/3 surface exists in this feature. | **PASS** |
| III — Provenance | External content is data, never instructions | Session records are parsed into typed events; no record content is ever interpreted as instruction. Reinforced by the redaction boundary (FR-011c). | **PASS** |
| IV — Human-in-the-loop | Never auto-approve coding-agent permissions | No write path exists. Observe-only is structural, not policy (FR-015). | **PASS** |
| V — Non-goals | No autonomous email/browser/companion behaviour | Not applicable; feature adds none. | **PASS** |
| VI — Lite by default | < 500 MB idle RAM, near-zero idle CPU, no hard Docker requirement | Mechanical summarizer is the default path (FR-008b); model is load→summarize→release (Gate 2). Watchdog events, not polling. Runs on host without Docker. | **PASS (gated)** |
| VII — Politeness | Quiet hours, coalescing, presence routing | **Not applicable this phase** — FR-025 forbids proactive push. The waiting-on-user event is emitted (FR-010) but has no consumer here. Article VII binds the Phase 2 trigger engine. | **N/A — deferred by design** |
| VIII — Privacy defaults | Local engines default, cloud opt-in, audit log | Summarization on-machine by default (FR-008a); cloud explicit opt-in only. **Audit log: see Deviation below.** | **PASS w/ noted scope** |
| IX — Ship in slices | Independently useful and releasable | User Story 1 alone is a shippable product. This is the roadmap's first phase. | **PASS** |
| X — Honest limits | State partial capability plainly; no fake precision | FR-006 (unknown state), FR-011a/b (unobservable ≠ empty), FR-015 (observe-only), FR-016a (inference vs observation), FR-011d (recognized patterns, not "secrets"). | **PASS (central)** |

**Article VIII scope note (not a violation):** Article VIII requires an audit log of *Tier-3
executions and relayed session approvals*. This feature has neither — every tool is Tier 1 and no
approval is relayed. No audit log is therefore required by the letter of the article, and adding
one would log only reads. Recorded here so the omission is a decision rather than an oversight;
the audit log becomes mandatory in the phase that introduces Tier-3 actions.

**No violations require justification.** Complexity Tracking is therefore empty and omitted.

## Plan-Review Gates

*Three constraints carried from the clarify pass. Each fails **silently** if dropped — the
system reports success while verifying nothing. Each gets a named task and a verification step,
not a passing mention.*

### Gate 1 — Hooks scoping (FR-019, SC-007, SC-008)

**The risk:** all four hooks in `.pre-commit-config.yaml` carry `files: ^backend/`. A watcher
placed outside `backend/` would make FR-019's "zero writes" and SC-008's "zero core imports"
gates pass because they matched no files.

**Resolution — placement:** the watcher lives at **`backend/packages/session_watcher/`**, a new
uv workspace package sibling to `harness`. This is inside `^backend/`, so the existing ruff hooks
cover it with **no hook-config change required**. Placement is the fix; the alternative (a
top-level `watcher/` plus four new hook entries) was rejected as strictly more moving parts for
the same result.

**Resolution — the checks themselves.** Being inside the linted surface makes hooks *run*; it
does not make them *check the right things*. Two mechanisms are added:

- **Core-import ban.** `backend/packages/session_watcher/ruff.toml` sets
  `flake8-tidy-imports.banned-api` on `omniharness*` and `langgraph*`. Any such import fails
  `ruff check` in the existing hook and in CI. Satisfies SC-008.
- **Shell-out ban.** The same `banned-api` list carries `subprocess`, `os.system`, `os.popen`,
  and `shell=True`. Observed project directories are path-slugs beginning with `-`, which a shell
  reads as an option flag (research R2, finding 2). Path handling is `pathlib`-only, module-wide.
  The hyphen fixture proves the rule holds; the ban stops it being broken later — a fixture only
  covers the paths some test happens to exercise.
- **Zero-write assertion.** A test snapshots content hash, size, and mtime of every fixture
  record before a full observation cycle and asserts all three unchanged afterwards. Hash
  *and* mtime, because a write-then-restore would leave content equal. Satisfies SC-007/FR-019.

**Verification step:** a task that deliberately adds `import omniharness` to a scratch file under
the package and confirms `pre-commit run --files ...` fails. A gate never observed failing is
indistinguishable from a gate that does nothing.

### Gate 2 — Process model: local on demand, not resident (Article VI, FR-008a)

**The risk:** a summarization model held resident exceeds the < 500 MB idle budget on its own,
and does so invisibly — the feature works perfectly while violating the constitution.

**Resolution — ownership.** The lifecycle is owned by `SummarizerPort`, with exactly two
implementations:

- `MechanicalSummarizer` — the **default**, zero resident cost, no model (FR-008b).
- `OnDemandModelSummarizer` — acquires the model inside a context manager scoped to a single
  summarization batch and releases it on exit. The model handle is never stored on the registry,
  the adapter, or any module-level singleton.

**Verification step — two layers, because the cheap one is the reliable one:**

- **Deterministic (CI):** after a summarization batch completes, a `weakref` to the model handle
  is asserted dead following a forced collection. This fails loudly on any retained reference and
  needs no memory measurement at all.
- **Measured (documented, not CI-gated):** an idle-RSS procedure in `quickstart.md` — start the
  watcher, idle 60 s with no sessions, sample RSS. Recorded rather than asserted, since absolute
  RSS is environment-dependent and a flaky constitutional gate would be worse than a documented
  one.

### Standing convention — every gate must be observed failing

*Adopted for this feature and for every future gate.* A gate that has never been seen to fail is
indistinguishable from a gate that does nothing. Each gate below therefore ships with a task that
deliberately breaks the thing it guards and confirms the gate bites; `quickstart.md` carries the
commands under "Proving the gates can fail". A gate without that step is not done.

### Gate 3 — Startup bound asserted on records opened (SC-004i, FR-005d/e)

**The risk:** a wall-clock assertion passes on fast hardware even after someone reintroduces a
full directory scan. The test stays green while the requirement is dead.

**Resolution — instrumentation.** Every record open goes through one seam, `RecordSource.open()`,
which increments `RecordSource.stats.records_opened`. There is no second path to opening a record
— the ban is enforced by the same ruff `banned-api` mechanism as Gate 1, applied to direct
`open()`/`Path.read_text` use inside the adapter module.

**Verification step:** a test builds a synthetic history of 5 000 session records of which 5 fall
inside the recency window, runs startup, and asserts `stats.records_opened <= 10` — a bound
proportional to the window, not the directory. Elapsed time is *not* asserted. SC-004j's 5-second
figure is checked separately as a smoke assertion with generous margin, and is explicitly not the
mechanism that protects FR-005e.

## Project Structure

### Documentation (this feature)

```text
specs/001-coding-session-watcher/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── mcp-tools.md     # Phase 1 output — the two Tier-1 tools
├── checklists/
│   └── requirements.md  # From /speckit-specify, re-validated by /speckit-clarify
└── tasks.md             # Phase 2 — NOT created by /speckit-plan
```

### Source Code (repository root)

```text
backend/packages/session_watcher/
├── pyproject.toml                 # uv workspace member; MUST NOT depend on omniharness-harness
├── ruff.toml                      # banned-api: omniharness*, langgraph*, subprocess, os.system,
│                                  #             os.popen, shell=True  (Gates 1 + shell-out ban)
└── session_watcher/
    ├── __init__.py
    ├── models.py                  # Session, SessionEvent, SessionState, IdleReason
    ├── server.py                  # SSE MCP server: the two Tier-1 tools (FR-018/018a)
    ├── registry.py                # Session registry, liveness/heartbeat (FR-002, FR-024a)
    ├── discovery.py               # Recency window + sticky membership (FR-005a-c)
    ├── state.py                   # Marker-first, timeout fallback, UNKNOWN (FR-006, FR-006a/b)
    ├── events.py                  # Normalized SessionEvent vocabulary + mapping (FR-007)
    ├── record_source.py           # THE record-open seam + stats counter (Gate 3)
    ├── reply.py                   # Caveat-first composition, hedged wording (FR-011b, FR-016a)
    ├── redaction.py               # Channel-aware, fail-closed, visible markers (FR-011c-f)
    ├── watcher.py                 # watchdog observers + reconciliation sweep (FR-022, FR-024)
    ├── summarize/
    │   ├── port.py                # SummarizerPort (Gate 2)
    │   ├── mechanical.py          # Default path (FR-008, FR-008b)
    │   └── on_demand_model.py     # load -> summarize -> release (Gate 2)
    └── adapters/
        ├── base.py                # SessionAdapter interface (FR-023)
        └── claude_code.py         # THE only format-aware file (FR-023)

backend/tests/session_watcher/
├── fixtures/                      # Valid + malformed + truncated + hyphen-prefixed dir
├── test_adapter_claude_code.py    # Fixture-based parsing, drift tolerance (FR-009)
├── test_paths.py                  # Hyphen-prefixed + Windows path handling (FR-020)
├── test_state_machine.py          # completed vs stalled vs UNKNOWN (SC-004a/b, FR-006)
├── test_registry_liveness.py      # heartbeat/staleness (FR-024a, SC-004e/f)
├── test_discovery_window.py       # sticky membership + records_opened bound (Gate 3)
├── test_redaction.py              # fail-closed, visible markers (SC-004k/l/m)
├── test_summarizer_lifecycle.py   # weakref release (Gate 2) + no-egress (SC-004c)
├── test_zero_writes.py            # hash+size+mtime unchanged (Gate 1)
├── test_no_core_imports.py        # backstop for the ruff ban (Gate 1)
├── test_reconciliation.py         # sleep/wake, missed events (FR-024, SC-006)
├── test_startup.py                # first-query smoke bound (SC-004j)
├── test_contract.py               # tool surface, sole-reachability, honest absence
├── test_us1_rollup.py             # US1
├── test_us2_blocked.py            # US2 incl. wording assertions (FR-016a)
├── test_us3_detail.py             # US3
└── test_us4_lifecycle.py          # US4

extensions_config.json             # + "session-watcher" SSE entry (FR-018)
```

**Structure Decision**: a new uv workspace package under `backend/packages/`, sibling to
`harness`, chosen specifically to land inside the `^backend/` hook surface (Gate 1) while keeping
a hard process and dependency boundary from core (Article I). It is *packaged* with the backend
and *deployed* as an independent host process — those are different things, and the distinction is
what lets one placement satisfy both constraints.

## Post-Design Constitution Re-Check

*Re-evaluated after Phase 1. Design artifacts: [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/mcp-tools.md](./contracts/mcp-tools.md),
[quickstart.md](./quickstart.md).*

All ten articles hold after design. Four became **stronger** than the pre-design assessment,
because the design made structural what had been merely intended:

- **Article I** — the separate uv package with a ruff `banned-api` rule turns "does not import
  core" from an intention into a build failure. Verified by a task that observes the gate fail.
- **Article II** — the contract has no mutation argument and no third tool. Tier-1-only is
  enforced by the shape of the surface, not by policy applied to it.
- **Article IV** — likewise. There is no write path to auto-approve *through*, so the
  human-in-the-loop guarantee cannot regress without adding a tool.
- **Article X** — the `observable` flag in the tool contract makes the unobservable-vs-empty
  distinction a required field rather than a convention. `IdleReason` does the same for
  observation-vs-inference. Both are the difference between a defect that is possible and one
  that is unrepresentable.

**One design decision reviewed and resolved**: R2 finding 3 establishes that waiting-on-user has
no explicit record type and must be *inferred*. This is the feature's single largest honesty risk
under Article X, since User Story 2 is P1 and rests entirely on an inference. Three rulings
settle it:

- **Err toward flagging.** The errors are asymmetric. A false "waiting on you" costs one wasted
  walk to the machine; a false "working" leaves a blocked session sitting all evening, which is
  the exact failure the feature exists to prevent. When uncertain, report possible-blocked with
  honest wording rather than staying silent.
- **The hedge is a testable criterion, not a style note.** Story 2's tasks assert on reply shape:
  a qualifier leading, and the observable evidence accompanying it — "Looks like it's waiting on
  you — last activity was a question 8 minutes ago, nothing since", never "It's waiting for your
  input." Same qualifier-leads rule as stale data (FR-011b) and mechanical summaries.
- **Corroboration is timeboxed.** The `mode`/`permission-mode` investigation is one bounded task.
  If it upgrades the inference toward observation, good; if a bounded look comes back empty,
  state the limit plainly and ship. A P1 story must not block on an open-ended dig through a
  format that is explicitly not a public API.

**No violations. Complexity Tracking below remains empty.**

## Complexity Tracking

No constitutional violations require justification. Section intentionally empty.
