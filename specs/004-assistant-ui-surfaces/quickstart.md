# Quickstart — Feature 004 Validation

Run in phase order. **Phases 1 and 2 produce no UI**, and that is the point: each closes
a gap that would otherwise make a later surface render a blank column or operate a path
that does not exist.

## Phase 1 — confirmation actually completes

```bash
cd backend
uv run pytest tests/policy/test_confirm_flow.py -q
uv run pytest tests/policy_multiworker/ -q          # at the production worker count
```

Expected: a Tier 3 action proposed in chat, confirmed with a recognised form, executes
once and is audited with the claiming worker.

**Before the phase**, the same test must fail with the action still open — that is the
live defect on main, and seeing it fail is what proves the test measures it.

**Manual check, because this is a user-visible break**: ask the assistant to do something
Tier 3, reply `yes`, and observe it happen. On main today, nothing happens.

## Phase 2 — the trigger record can answer the question

```bash
uv run pytest tests/trigger_engine/test_evaluation_record.py tests/trigger_engine/test_batch_identity.py -q
```

Expected: a rule evaluated without firing is distinguishable from one never evaluated;
firings delivered together share a `batch_id` and none is recorded as anything but
delivered.

## Phases 3–6 — the surfaces

```bash
cd frontend
pnpm vitest run                                       # units
npx playwright test --config=playwright.theme.config.ts   # CI only
```

The pinned browser download stalls at 448 KB on this machine against 369 MB in CI (measured).
That blocks `npx playwright install`, not the specs: pointing a local config at an
already-installed `chrome-headless-shell` runs the same `tests/rendering` directory, and
that is how the run record below was produced. CI (`theme-rendering.yml`) runs the same
directory with the pinned browser and is the record of authority.

Each surface must show, asserted against a rendered page:

- **Confirmations**: an action above the threshold cannot be confirmed by clicking; a
  wrong typed count neither confirms nor resolves it.
- **Sessions**: with the watcher stopped, the page says sessions cannot be seen. It does
  not render an empty list.
- **Triggers**: a quiet-hours suppression is distinguishable from a delivery and from a
  rule that never evaluated.
- **Policy**: a tier and its deciding rule, with no side effect on the tool.
- **Tool sources**: a source on a dead port reads "unreachable" with its error, not absent;
  an authorised connector this conversation has not selected is not called unauthorised.
- **Sessions, confirmations, policy**: content that failed redaction shows as *withheld*,
  never blank and never raw (FR-031).
- **All five**: toggling dark mode changes the computed background colour.

## Gates — each must be seen failing

```bash
uv run pytest tests/gates/ -q
```

Every gate ships with a step that deliberately breaks what it guards. A gate never
observed failing is indistinguishable from one that does nothing, and the sabotage must
be confirmed to fail *at the gate* rather than upstream of it — a run reporting
`skipped`, `error`, or a collection failure has not exercised anything.

## Run record — 2026-10-19, branch `phase-2-ui-surfaces` (T093)

| Step | Where it ran | Result |
|---|---|---|
| Phase 1 `test_confirm_flow.py` | locally | 9 passed |
| Phase 1 `policy_multiworker/` | locally (production worker count) | 8 passed |
| Phase 1 "before the phase it must fail" | not re-run: it was observed failing when Phase 1 was built, on the pre-fix code | — |
| Phase 1 manual Tier 3 `yes` in chat | **not run**: it would perform a real Tier 3 action (delete or decline) on the owner's accounts. The confirm path is exercised end to end by `test_confirm_flow.py` and the multi-worker suite | — |
| Phase 2 evaluation record and batch identity | locally | 15 passed |
| `pnpm vitest run` | locally | 18 files, 90 passed |
| `tests/rendering` (all five surfaces, dark mode, withheld) | locally against the installed headless shell; **and in CI** with the pinned browser | locally 43 passed; CI (PR #39, 'Does the theme change what the user sees?'): pass |
| `tests/gates/` | locally | 10 passed |
| Each gate seen failing | locally, by sabotage, recorded in each commit message | every sabotage failed **at the gate** (reported `failed`, not skipped or errored), and was green again once reverted |
