# Phase 1 Spike Results — Feature 003

**Date**: 2026-08-24 · **Tasks**: T004–T016

Four assumptions measured before any policy code is built on them. Each spike carries a **positive control** — an instrument never seen detecting the thing it looks for is not evidence of absence (Article XII).

**Outcome: 3 of 4 measured, 1 BLOCKED.** The blocked one is reported as blocked, not estimated.

---

## Spike 1 — Subagent suspend and resume (FR-032) · **CONFIRMED, then FIXED**

| Step | Result |
|---|---|
| **T004 Positive control** — lead agent (has a checkpointer) | ✅ suspends inside `wrap_tool_call`, resumes, tool runs |
| **T005** — reproduce VP-008 (subagent shape, no checkpointer) | ✅ run **ends** at suspension, tool never runs, **nothing raises** |
| **T006** — attach a checkpointer to the subagent | ✅ done |
| **T007** — confirm **after a delay** | ✅ suspends, waits 1.5 s idle, resumes, tool runs |

**What the control was worth**: an earlier probe of this reported "suspension is unavailable" outright. It was failing on a missing `bind_tools` in the stand-in model, before reaching any suspension logic. The control is what turned a wrong finding of large scope into the correct, narrower one. `test_suspend_resume_control.py` pins that trap so the wrapper is not removed later as ceremony.

**The defect's shape, for the record**: no exception. The caller sees a completed run whose tool did not execute — the same observable as a correct refusal. Any test that declines to confirm passes against the broken code, which is why T007 confirms after a delay rather than instantly.

**Changed**: `subagents/executor.py` — `checkpointer` constructor parameter, resolved from the process checkpointer when not supplied, passed to `create_agent`.

---

## Spike 2 — Per-tool deny at both assembly points (FR-013) · **CONFIRMED**

| Step | Result |
|---|---|
| **T008 Positive control** — tool IS present when not denied | ✅ both paths |
| **T009** — `McpToolSurface` on `McpServerConfig` | ✅ `allow` / `deny`, unprefixed names |
| **T010** — MCP path (`mcp/tools.py`, between `get_tools()` and `extend()`) | ✅ denied tool absent |
| **T011** — connector path (`tools/tools.py`, after `load_connector_tools`) | ✅ denied tool absent |

**Why both**: `GMAIL` and `GOOGLECALENDAR` are already Composio connector toolkits and that path never touches `mcp/tools.py`. A deny at the MCP layer alone leaves `connector:GMAIL` and its send tool fully exposed.

**Confirmed by test**: deny keys are **unprefixed** (`send_email`, not `gmail_send_email`) — and the prefixed form is asserted *not* to work, so the contract is not quietly both.

**Not used: `tool_interceptors`.** The MCP client accepts them and they are the obvious hook. They wrap execution, which yields *guarded*; FR-012 requires *absent*.

---

## Spike 3 — Browser profile isolation (FR-017) · **BLOCKED — NOT MEASURED**

**The isolation claim is unverified. It is not "probably fine".**

| What | Result |
|---|---|
| `@playwright/mcp` package available | ✅ v0.0.79 |
| MCP stdio transport for a new server | ✅ already proven — `extensions_config.json` runs `filesystem`, `github`, `postgres` over stdio |
| Chromium present | ✅ builds 1217, 1228, 1234 in the Playwright cache |
| **Browser launches in this environment** | ❌ **`Target page, context or browser has been closed`** on a minimal `chromium.launch()`, before any profile logic |
| **T012 positive control — cookie persists in a configured profile** | ⛔ **not run** |
| **Isolation — daily profile's cookie absent** | ⛔ **not run** |

**Measured disk footprint** (Article X — measured, not estimated):

| Component | Size |
|---|---|
| `chromium-1234` (full build) | **356 MB** |
| `chromium_headless_shell-1234` | **196 MB** |
| `chromium-1228` (older, present) | 344 MB |
| `ffmpeg-1011` | 2.5 MB |

A single full build plus headless shell is roughly **550 MB of disk**. It runs on demand, so Article VI's <500 MB *idle RAM* budget is not threatened by the binary sitting there — but the disk cost is real and belongs in the honest-limits wording.

**Why it is blocked, precisely**: the version of Playwright installed expects browser build 1217; the cache held 1228 and 1234. `npx playwright install chromium` was started and downloaded the full 1217 build, but had not finished the headless shell when this ran, and every launch attempt — full build via `channel: 'chromium'` included — failed at process start. Whether the cause is the concurrent install, a partially written bundle, or an environment restriction on launching a browser here **was not determined**.

**Consequence**: T012/T013 are NOT complete. Per T016 and the stop-and-report list, **Phase 4's browser worker must not be designed against an assumed answer.** Re-run the probe (`launchPersistentContext` with two distinct `userDataDir`s: set a cookie, reopen, assert persistence; then assert the other profile's cookie is absent) once a browser can start. The probe is written and ready.

---

## Spike 4 — Tool-result message lineage (FR-005, FR-006) · **CONFIRMED**

| Step | Result |
|---|---|
| **T014 Positive control** — the check detects a KNOWN tool result | ✅ `ToolMessage`, dict form, and `tool_call_id` alone |
| Discriminates | ✅ human, AI and system messages are not flagged |
| **T015** — does the distinction hold across every source? | ✅ **uniformly** |

| Source | Reaches the agent as | Result message |
|---|---|---|
| builtin | `BaseTool` in the same list | `ToolMessage` |
| MCP | `BaseTool` in the same list | `ToolMessage` |
| Composio connector | `BaseTool` in the same list | `ToolMessage` |
| ACP | `BaseTool` in the same list | `ToolMessage` |
| `Command`-returning tools (e.g. preview) | — | `ToolMessage` inside `Command.update["messages"]` |

All four sources normalise to `BaseTool` and execute through one tool node, so one check covers every source.

**A limit stated rather than hidden** (`lineage.py` docstring): this determines that a message **is** a tool result. It cannot prove text inside a `HumanMessage` was not copied from a web page by the user — and that is correct, because a user pasting something is the user saying it. What must never happen is the *system* treating tool output as if the user had spoken, which is what this prevents.

**Design consequence**: `eligible_to_confirm` and `eligible_to_initiate` are separate functions, because they are separate requirements. An AI message may initiate a Tier 3 action but may not confirm one; collapsing them into one predicate loses that.

---

## Checkpoint (T016) — verdict

| Spike | Status | Blocks |
|---|---|---|
| 1 · subagent suspend/resume | ✅ measured, defect fixed | nothing |
| 2 · per-tool deny, both paths | ✅ measured | nothing |
| 3 · browser profile | ⛔ **BLOCKED** | **Phase 4 browser work (T063–T065)** |
| 4 · tool-result lineage | ✅ measured | nothing |

**Phases 2 and 3 are unblocked.** Neither depends on the browser: Phase 2 is the policy core against existing tools, and Phase 3's lineage mechanism is Spike 4, which passed.

**Phase 4 is partially blocked** — the email and calendar workers do not depend on Spike 3, only the browser worker does.

**Nothing measured contradicted the plan.** The one open item is unmeasured, not contrary.
