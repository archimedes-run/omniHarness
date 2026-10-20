# Implementation Plan: Agent Improvement

**Branch**: `007-agent-improvement` (one PR per slice) | **Date**: 2026-10-20 | **Spec**: [spec.md](spec.md) | **Research**: [research.md](research.md)

**Input**: Feature specification from `/specs/007-agent-improvement/spec.md`

## Summary

Scheduled agents get better from their own run history, using the Harness² loop (Propose, Probe, Compose; arXiv:2610.14224 §2.2) and its experience library (§2.3), adapted for real accounts:

- **Probes cannot write.** They run the agent's real runtime and tool registry, wrapped. Explicit Tier 1 reads run; every other call is recorded and not executed. A sabotage test proves the wrapper is what stops the write.
- **Comparison is a fixed rule** (spec FR-020 to FR-029): validity, safety, honesty (loses outright), delivery, execution evidence measured against the baseline's own noise, and blind-judged feedback checks built from the user's history.
- **Nothing applies without approval.** Proposals are diffs with evidence in Agent Studio; every change is a version and can be restored.
- **Cost is bounded** before, during and after each run.

The **first slice** is the read-only replay harness and the simulated-write wrapper with its sabotage test. Nothing else is built until that gate has been seen failing under sabotage.

## Technical Context

- **Language/Version**: Python 3.12 (gateway, policy, new improvement module); TypeScript 5 / React 19 / Next.js 16 (Agent Studio tabs).
- **Primary Dependencies**: existing only. FastAPI, SQLAlchemy and Alembic; the LangChain agent middleware chain; the policy engine; TanStack Query, Radix Tabs and Dialog. **No new dependency**, and nothing from `google-research/harness2` is imported or vendored (research.md R4).
- **Storage**: new SQL tables in one migration (next free number at implementation time; `0014_ledger` is the latest on `main`, and 006 Phase 1 reserved `0015` for `user_preferences`): `agent_versions`, `improvement_runs`, `improvement_candidates`, `improvement_probes`, `simulated_writes`, `feedback_events`, `improvement_proposals`, `agent_lessons`, `improvement_budgets`. A tracked price table `backend/app/improvement/prices.yaml` (Article XIV) with per-user overrides in `improvement_budgets`.
- **Testing**: pytest, including `tests/gates/test_wiring.py`, the `gateway` composition-root fixture pattern from `backend/tests/ledger/conftest.py` (TestClient with lifespan, temp sqlite, policy on), and `backend/tests/trigger_engine/test_production_wiring.py`'s `build_production_loop` pattern. vitest and Playwright for the tabs (`contrast.spec.ts` in both themes, a rendering spec per tab).
- **Target Platform**: the existing daemon profile and full stack. No Docker requirement (Article VI).
- **Performance Goals**: probes run in the background, never on the trigger engine's event loop (AUDIT-2026-10 T-6), at most 2 probes in parallel by default. Improve tab usable in under 1 s; panel open under 150 ms (006 FR-007).
- **Constraints**: probe caps of 60 model turns and 600 s each (defaults; the agent's own scheduled runs are far shorter; the paper's caps of 200 turns and 3,600 s were for benchmark tasks, Appendix D.1). Idle cost zero: nothing runs unless started or scheduled.
- **Scale/Scope**: one user, a handful of scheduled agents, at most one improvement run per agent at a time, about 15 probes per run.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Article | How this plan complies |
|---|---|
| I. Gateway only | The improvement orchestrator is a module (`backend/app/improvement/`) that talks to the core only through gateway endpoints, like the trigger engine: it starts probes with `POST /api/improvement/probes` and makes tool-less model calls with `POST /api/improvement/complete`. The probe wrapper lives in the policy layer (`backend/app/policy/probe.py`) and is installed through a harness hook, like `PolicyMiddleware`. The wiring gate and the import gate cover the new module. |
| II. Three tiers | No new agent tools (spec FR-090). In probes, the policy engine's own `classify()` and tracked rules decide; only explicit-rule Tier 1 calls run; Tier 2, Tier 3 and unknown are simulated; Tier 3 is never executed (FR-012). The probe wrapper sits outside `PolicyMiddleware`, never instead of it: a real call still passes through it. |
| III. Provenance | Evidence, lessons and feedback are passed to the improver as data, in tool-less calls. Approval, rejection and restore are accepted only from the signed-in user's web UI request (FR-044). Probe threads are marked synthetic and cannot satisfy a confirmation. |
| IV. Human in the loop | No coding-agent permissions are touched. Every change to an agent needs the user's approval (FR-048). |
| V. Non-goals | No email is sent or read-and-replied: drafts and sends are simulated in probes. Proposals cannot add recipients (FR-031). |
| VI. Lite | No new process; the orchestrator runs inside the gateway lifespan as a background task only while a run exists. No Docker. |
| VII. Politeness | Probes never deliver, alert or notify (FR-015). Weekly and shadow results wait quietly on the Improve tab (FR-072). Shadow probes start only after the real firing is delivered or held (FR-070, FR-073). |
| VIII. Privacy | Probe evidence stays local. The evidence guard refuses secrets and tokens in improver inputs (redaction at the boundary, fail closed). Approve, reject and restore are written to the audit log (FR-047). |
| IX. Slices | Six slices, each releasable. Slices 1 and 2 need nothing from 006 (spec "Order of work"; research.md R6). |
| X. Honest limits | "Not available", "can't tell", "replayed on today's data", "stopped at your budget", and KEEP_CURRENT are first-class outcomes in words. |
| XI. Production shape | Each slice has an integration test through `create_app()` with its lifespan; slice 1 also through `build_production_loop`. Probes use the real `get_available_tools` and the real middleware chain, not a test registry. |
| XII. Probes seen finding | Every new gate is sabotaged once and the failure confirmed to be the gate (not an upstream error), with the summary line read, not grepped. The honesty checker and feedback judge each get a known-positive case before their negatives are trusted. |
| XIII. Initiation ≠ confirmation | Two separate requirements with separate tests: FR-031 (no new identifiers can be proposed from content) and FR-032/FR-044 (only the user's UI request approves). |
| XIV. Tracked defaults | The write-verb list, the price table, the default caps and thresholds and the probe hook registration are tracked files. Tests read only tracked files; the gate test asserts the paths are tracked (`git ls-files`). |

**Result: PASS.**

## Architecture

```text
Agent Studio (Improve, Lessons tabs)
        │  REST, signed-in user only
        ▼
gateway  routers/improvement.py  ── user endpoints: estimate, start, stop, result,
        │                           approve, reject, restore, versions, lessons, budgets
        │                         ── internal endpoints (service token): probes, complete
        ▼
backend/app/improvement/   (module; HTTP to gateway only)
  orchestrator.py   estimate → baseline ×R → propose 2k → validate → probe → compose → probe → compare → reflect
  compare.py        the comparison rule (pure functions over probe records)
  honesty.py        H1–H4 checks (deterministic part + judge requests)
  feedback.py       feedback checks from feedback_events
  budget.py         estimate, per-call guard, actuals
  validator.py      allow-list of surfaces, locked-surface diff, FR-031 identifier check
        │
        ▼  POST /api/improvement/probes  (gateway builds the run)
lead agent runtime  ── middleware chain: [ProbeMiddleware (outermost) → PolicyMiddleware → …]
                       memory, delivery, disclosure, title and alert side effects disabled for probe runs
```

**Probe wrapper.** `ProbeMiddleware` implements `wrap_tool_call` and `awrap_tool_call`:
1. classify with `app.policy.classify.classify()` and the shared rules loader (`app/policy/registration.py:90`, `shared_loader`);
2. run the call (pass it on to `PolicyMiddleware`) only if the decision is Tier 1 **from an explicit rule** and the tool name is not on the tracked write-verb list (`backend/app/policy/probe_write_verbs.yaml`);
3. otherwise write a `simulated_writes` row and return a `ToolMessage` that says the write was recorded and not executed in a test run.

It must wrap `PolicyMiddleware` from outside, so a simulated Tier 3 call never reaches `_require_confirmation` and never creates a PendingAction. The ordering is asserted by a test that inspects the built chain and by the sabotage test, not assumed from the list order (research.md R6: the code comment at `tool_error_handling_middleware.py:133-137` makes two incompatible claims about which position is outermost, so the order is unverified).

**Fail closed.** The probe endpoint is the only way to start a probe. It builds the agent with the probe wrapper installed and refuses to start if the built chain does not contain it. Regular run endpoints reject any request carrying a probe marker. A probe whose wrapper is missing never runs ungated.

## Slices

Each slice: one PR, CI green, every new gate sabotaged once (Article XII), at least one test through the production composition root. "Done" means called in production, tested, and the sabotage recorded in the PR description with the failing assertion named.

### Slice 1 (FIRST): read-only replay harness and simulated-write wrapper

**Builds**
- `backend/app/policy/probe.py`: `ProbeMiddleware`; `probe_write_verbs.yaml` (tracked).
- Harness hook `omniharness/agents/middlewares/probe_hook.py` (`register_probe_middleware_builder`), mirroring `policy_hook.py:35-94`, wired in `app/policy/registration.py:install()`.
- `backend/app/gateway/routers/improvement.py` with `POST /api/improvement/probes` only (internal service token): input = agent name + stored run id (replay) → a probe run under the wrapper, with the run's stored `kwargs_json` input and config (`app/gateway/services.py:324`), side effects disabled (memory middleware off, no channel delivery, no alerts, no disclosure ledger writes, thread tagged synthetic).
- `simulated_writes` table and its repository.
- A "dry run" API for any agent (useful alone: run an agent on a past input and see what it would have written).

**Gates and sabotages**
| Gate | Asserts | Sabotage that must make it fail |
|---|---|---|
| G1.1 sabotage test (spec FR-016) | A probe calling a test write tool with a real-side-effect counter leaves the counter at 0 and writes one `simulated_writes` row | (a) remove `ProbeMiddleware` from the probe chain; (b) give the test tool a Tier 1 result without an explicit rule |
| G1.2 Tier 3 never reaches policy | A probe calling a Tier 3 tool creates no PendingAction file under `{policy.state_dir}/pending/` and no card | install the wrapper inside `PolicyMiddleware` instead of outside |
| G1.3 write-verb disagreement | A Tier 1-by-rule tool named `archive_*` is simulated and flagged | empty the write-verb list |
| G1.4 no side effects | After a probe: ledger, agent `memory.json`, pending store, disclosure ledger, trigger engine deliveries and Home items unchanged (hash before and after) | re-enable the memory middleware for probe runs |
| G1.5 fail closed | The probe endpoint refuses to run when the built chain lacks the wrapper; regular run endpoints reject a probe marker | make the builder return the chain without the wrapper |
| G1.6 tracked files | The write-verb list and rules files the wrapper reads are tracked (`git ls-files`) | point the loader at an untracked copy |

**Integration tests (production shape)**
- Through `create_app()` + lifespan (the `gateway` fixture pattern from `tests/ledger/conftest.py`, policy ON): store a run for a test agent, call the probe endpoint, assert G1.1 to G1.4 with the real `get_available_tools` (built-ins, ledger tools, and one stub MCP tool loaded through the MCP path) and the real middleware chain. The test names the structural difference it defends against: "probe chain built by the production builder, not a test chain".
- Through the trigger engine: `build_production_loop` (`app/gateway/trigger_engine_wiring.py:370`) with a cron rule for the test agent; run one firing, then a probe of that firing's run. Assert the firing delivered once and the probe produced zero firings, zero deliveries and zero pending entries in the engine's state dir.
- Positive control (Article XII): the same test agent run normally (not as a probe) DOES increment the counter. Without this, a counter stuck at 0 proves nothing.

### Slice 2: agent versions, apply, restore, locked-surface validator

**Builds**
- `agent_versions` table; a snapshot function over the agent's files (`config.yaml`, `SOUL.md`, `memory.json`, the new `TOOLS.md` tool-guidance file, its skill allow-list, the rule prompt it is bound to) and its locked fields.
- A versioning hook at every writer: `routers/agents.py` (POST :191, PUT :259), `setup_agent_tool.py`, `update_agent_tool.py`, and later 006 Studio saves (spec FR-045, Open Question 10).
- `validator.py`: the editable allow-list (spec FR-004), locked-surface diff (FR-005), executable-code rejection (FR-006), identifier check (FR-031).
- Endpoints: `GET /api/agents/{name}/versions`, `POST /api/agents/{name}/versions/{n}/restore`; restore and apply are audited (FR-047).

**Gates and sabotages**
| Gate | Asserts | Sabotage |
|---|---|---|
| G2.1 locked surfaces | An edit to tool_groups, model, schedule, autonomy or a policy file is dropped | remove one locked field from the validator |
| G2.2 initiation (Article XIII) | An edit adding an email address or URL not in the current setup or user text is dropped | disable the identifier check |
| G2.3 restore exactness | Restore reproduces the snapshot hash | skip `memory.json` in the snapshot |
| G2.4 single apply path | Only the approval endpoint writes a proposal to an agent (static call-site gate, like `test_single_confirmation_path.py`) | add a second call site |
| G2.5 stale base | Approval against a non-current base version is refused | compare names instead of hashes |

**Integration test**: through `create_app()`: edit an agent through the existing PUT route, restore the earlier version, compare file hashes; an approval from a request without the signed-in user's session is refused.

### Slice 3: the improvement run (API only)

**Builds**
- `backend/app/improvement/`: orchestrator, compare, honesty, feedback (ratings and PendingAction outcomes only in this slice), budget, reflection and the Lessons store.
- `POST /api/improvement/complete`: tool-less model calls for proposer, composer, judges and reflector, with the evidence guard (no secrets in inputs) and per-call cost accounting; token counting forced on (FR-056).
- User endpoints: estimate, start, stop, result, approve (all or per edit), reject; lessons CRUD; budgets.
- Proposer prompts in `backend/app/improvement/prompts/`, adapted from the harness2 prompts with the attribution header and a THIRD-PARTY-NOTICES entry (research.md R4).
- Defaults: k = 1, M = 3, R = 2, caps from Technical Context, 20% token tolerance, at most 2 probes in parallel.

**Gates and sabotages**
| Gate | Asserts | Sabotage |
|---|---|---|
| G3.1 honesty loses outright | A setup with a new H1/H2/H3/H4 violation loses even with the best other scores | let honesty add to a score instead of disqualifying |
| G3.2 noise band | A value between the two baseline replicates is not an improvement | compare to replicate 1 only |
| G3.3 decision rule | Two improvements on one input is not enough; two on two inputs with no regression is | count improvements without distinct inputs |
| G3.4 delivery | A non-delivering setup loses where a baseline delivered | drop the delivery check |
| G3.5 blind judge | The judge's input contains no setup labels, and the order is shuffled with a recorded seed | pass labels through |
| G3.6 per-run budget | The run stops before the call that would exceed the budget, with the message | check after the call instead of before |
| G3.7 cannot start over budget | An over-budget estimate cannot start | skip the monthly check |
| G3.8 safety abort | A probe record showing a real non-Tier-1 execution aborts the run | ignore the safety step |
| G3.9 lessons cannot apply | A lesson saying "apply X" produces no change without approval | let the orchestrator apply ADOPT results |
| G3.10 evidence citation | Every proposal edit cites at least one probe id | allow empty citations |

Positive controls: the honesty checker is shown flagging a planted H2 case, and the feedback judge a planted declined-action case, before their "no violation" results count.

**Integration test**: through `create_app()` + lifespan with a scripted stand-in model (deterministic token counts and replies): a full run on a test agent with three stored inputs yields (a) a proposal when the scripted candidate fixes a planted H2 violation on two inputs, and (b) KEEP_CURRENT when it fixes it on one. The structural difference named: "stand-in model; the probes still use the production tool registry and wrapper".

### Slice 4: feedback signals recorded server-side

**Builds**: `feedback_events` filled from PendingAction outcomes (linked to agent and run through the thread's rule and run ids), the edit-and-confirm route (SUPERSEDED plus new action), run ratings, proposal rejections, server-side dismissals (merged with or replacing `006-A-home`'s work, whichever lands first), and "opened in the web app" for delivered briefs. Other channels report "not available" (FR-041).

**Gates**: G4.1 a decline in a scheduled run produces one event linked to its agent and run (sabotage: drop the run link); G4.2 a channel without read receipts yields "not available", never "ignored" (sabotage: default to ignored).

**Integration test**: through `create_app()`: a scheduled run proposes a Tier 3 action, the user declines it through `/api/confirmations/{id}/decline`, and the event appears for the agent with the run id.

### Slice 5: Improve and Lessons tabs (after 006 Phase 3; run links after Phase 4)

**Builds**: `frontend/src/components/workspace/shell/panels/agents/improve-tab.tsx`, `lessons-tab.tsx` (inside the Phase 3 agents panel), `frontend/src/core/improvement/{api.ts,hooks.ts}`. The Lessons tab reuses the Settings > Memory card components (`components/workspace/settings/memory/`). Layout per research.md R7.

**Gates**: rendering specs for both tabs in both themes; contrast; colour-token test covers the new directories (sabotage: exclude one); the Improve button is absent for a chat agent (sabotage: always render it); one solid primary button per screen.

**Integration**: Playwright against the production build with a seeded proposal: approve one edit, reject another, restore the previous version; the agent's files change only on approve and restore.

### Slice 6: shadow mode and the weekly run (after 006 Phase 4)

**Builds**: on a firing whose rule names an agent with shadow mode on, after the firing is delivered or held, the orchestrator schedules shadow probes on the same input (via the probe endpoint, off the engine loop). Weekly runs through a cron rule owned by the improvement module, which checks the budget before starting.

**Gates**: G6.1 shadow probes start only after delivery or hold (sabotage: start at firing); G6.2 the real firing's outcome, delivery count and time are unchanged (sabotage: deliver a shadow output); G6.3 a weekly run over budget does not start (sabotage: skip the check); G6.4 quiet hours: no notification (sabotage: notify on completion).

**Integration test**: through `build_production_loop` with a cron rule bound to a test agent, shadow on: one firing, one delivery, M shadow probes, zero extra deliveries and zero pending actions.

## Project Structure

### Documentation (this feature)

```text
specs/007-agent-improvement/
├── spec.md        # this feature's requirements
├── research.md    # Harness² method, risks of the reference code, licence, 006 dependencies, board description
├── plan.md        # this file
├── data-model.md  # next step (/speckit-plan Phase 1)
├── contracts/     # next step: improvement API
└── tasks.md       # /speckit-tasks
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── policy/
│   │   ├── probe.py                  # ProbeMiddleware (slice 1)
│   │   └── probe_write_verbs.yaml    # tracked write-verb list (slice 1)
│   ├── improvement/                  # module; gateway HTTP only (slices 3, 4, 6)
│   │   ├── orchestrator.py  compare.py  honesty.py  feedback.py
│   │   ├── budget.py  validator.py  reflection.py  lessons.py
│   │   ├── prices.yaml               # tracked price table
│   │   └── prompts/                  # adapted from harness2, with attribution
│   └── gateway/routers/
│       ├── improvement.py            # probes, complete, user endpoints
│       └── agents.py                 # versioning hook (slice 2)
├── packages/harness/omniharness/
│   ├── agents/middlewares/probe_hook.py
│   └── persistence/improvement/      # tables + repositories, one migration
└── tests/
    ├── improvement/                  # unit, comparison rule, budget
    ├── policy/test_probe_*.py        # slice 1 gates and sabotages
    └── gates/                        # single apply path; tracked files
frontend/src/
├── components/workspace/shell/panels/agents/{improve-tab,lessons-tab}.tsx
└── core/improvement/{api.ts,hooks.ts}
```

**Structure Decision**: the probe wrapper belongs to the policy layer because it is a classification chokepoint (Article II); the orchestrator is a module beside `trigger_engine/` because it drives runs from outside the core (Article I).

## Post-design Constitution re-check

Unchanged: **PASS**. The one place to watch in review is the probe wrapper's position relative to `PolicyMiddleware`; G1.2 exists for exactly that.

## Complexity Tracking

| Item | Why needed | Simpler alternative rejected because |
|---|---|---|
| A second wrapper outside `PolicyMiddleware` | A simulated Tier 3 call must not create a PendingAction or a card | Putting probe logic inside `PolicyMiddleware` would add a mode flag to the one chokepoint every real call uses; a bug there could disable confirmation for real runs |
| Versioning every agent writer, not just proposals | Undo must work whatever made the last change (Open Question 10) | Versioning only proposals would let a later manual edit make "restore" silently drop it |
| Two baseline replicates per input | Without them there is no noise band, and a single-sample difference would count as evidence (the paper's prompts call it noise, `prompts.py:916-924`) | One baseline run is cheaper but makes the comparison rule meaningless |
