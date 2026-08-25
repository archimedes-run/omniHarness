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

Rendering assertions do not run locally — the browser bundle stalls at 448 KB here
against 369 MB in CI. That was measured. Push and read the job.

Each surface must show, asserted against a rendered page:

- **Confirmations**: an action above the threshold cannot be confirmed by clicking; a
  wrong typed count neither confirms nor resolves it.
- **Sessions**: with the watcher stopped, the page says sessions cannot be seen. It does
  not render an empty list.
- **Triggers**: a quiet-hours suppression is distinguishable from a delivery and from a
  rule that never evaluated.
- **Policy**: a tier and its deciding rule, with no side effect on the tool.
- **All four**: toggling dark mode changes the computed background colour.

## Gates — each must be seen failing

```bash
uv run pytest tests/gates/ -q
```

Every gate ships with a step that deliberately breaks what it guards. A gate never
observed failing is indistinguishable from one that does nothing, and the sabotage must
be confirmed to fail *at the gate* rather than upstream of it — a run reporting
`skipped`, `error`, or a collection failure has not exercised anything.
