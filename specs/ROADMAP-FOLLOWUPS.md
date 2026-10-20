# Carried-forward work

Items deliberately not built, each with the reason and the condition that reopens it. A deferral without a checkable condition becomes a permanent absence nobody decided on.

---

## Browser worker — REOPENED, awaiting a feature

**Was**: cut from Feature 003 (FR-016, FR-017, SC-007) on 2026-08-24.

**Cut because** SC-007 — *"a browser session started by the assistant carries none of the user's everyday browser cookies or sessions"* — could not be demonstrated. No browser bundle could be produced: repeated clean installs left 448 KB against ~350 MB. That is a claim about the user's private browsing state, and not one to make on reasoning.

**Reopened 2026-08-25** because the information changed. A standalone CI job downloads a 369 MB bundle in ~4 s and runs rendering assertions, including toggle-a-class-and-read-computed-style. **The 448 KB failure is local and environmental.** SC-007 is verifiable — in CI.

**Scope**: its own feature, not folded into 004. Carries forward unchanged:

- the requirements as written;
- the **positive-control-first** spike design — prove the profile persists a cookie BEFORE trusting that it excludes one, because an isolation test against an inert profile passes for the wrong reason;
- the measured ~550 MB disk figure (FR-023a), stated as measured.

**New constraint**: verification runs in CI, not locally. Write the acceptance criteria knowing a developer cannot check them before pushing.

---

## Accessibility lint rules — DONE in Feature 004 (T085/T086, 0b8b0b7)

The six rules below are `error` in `frontend/eslint.config.js`; CI `lint-frontend` is the blocking gate (the Next 16 build does not lint). The rest of this entry is kept for the non-promoted list at its end, which is still open.

**Six `jsx-a11y` rules are configured at `warn` and cannot fail a build**, because `pnpm lint` passes no `--max-warnings`: `alt-text`, `aria-props`, `aria-proptypes`, `aria-unsupported-elements`, `role-has-required-aria-props`, `role-supports-aria-props`.

Same shape as `no-unused-vars`, which sat at `warn` through three features and had never failed anything.

**Held until 004 deliberately.** Promoting them now means fixing violations across a frontend about to be rewritten. Promoting them **as part of the UI feature** holds new code to them from the start, which is the cheaper order and the one that sticks.

**Task for 004**: promote the six to `error` in the same change that establishes the new UI, and fix whatever the existing surface violates at that point.

Also at `warn` and non-blocking, not proposed for promotion yet: 12 `@next/next/*` correctness rules, `react-hooks/exhaustive-deps` (2 live violations), `incompatible-library`, `unsupported-syntax`, `consistent-type-imports`, `import/no-anonymous-default-export`.

---

## Python type checking — wired but not enforced

mypy is configured — permissive globally, strict on `app.policy`, `app.trigger_engine`, `session_watcher` — and **deliberately not in CI**, because it currently reports 72 errors in that strict scope. Wiring a failing check non-blocking would make it decorative on day one, the exact antipattern found in the lint audit.

**Condition to wire it**: the 72 closed. Then it goes in as a blocking step, or not at all.

---

## Feature 003 remainders

- **T075** partial — the calendar source supplies attendees and subject; memory lookup for "anything relevant about that person" is not wired.
- **T079** — architecture doc for the policy layer, deferred; the close-out records carry the reasoning.
- **`config.example.yaml` `models:`** now ships a verified `gpt-5` entry. Revisit when the default should be something else.
- **The e2e workflow starts no backend**, so two landing-page tests fail by design. Red since June, unrelated to any feature here.

---

## A run that errors returns HTTP 200 with an empty body — FIXED 2026-10-19 (a82e705)

**Closed** in the Phase 1 wiring pass. Both `runs/wait` routes now share `services.wait_result`, which raises for a run that did not succeed: `error` → 500, `timeout` → 504, `interrupted` → 409, each with `{run_id, status, error}`. The trigger engine, the in-repo consumer, resolves such a firing FAILED with the run's own reason and retries it up to three times; it no longer delivers "(the assistant returned nothing)". The original report follows.


**Found 2026-08-25 during Feature 004's T027 walkthrough.** Opened as a follow-up rather
than fixed inline: it is a gateway concern, not a policy one.

Posting to `/api/threads/{id}/runs/wait` with a bad `assistant_id` returned:

```
HTTP/1.1 200 OK
{}
```

The run had failed — `FileNotFoundError: Agent directory not found` — and the only place
that said so was the server log. A caller checking the status code sees success. A caller
checking the body sees nothing to distinguish "the run produced no messages" from "the
run never started".

This cost real time during T027: an empty response read as "the model said nothing", and
the actual cause was found only by reading the gateway log.

**Why it matters beyond the inconvenience.** "Assert on state, not status" has been a
lesson about how we write tests. This makes it a defect in the product: the transport
layer reports success for a failed run, so any consumer that trusts the status code is
wrong, and every consumer written against this API has to know that. Feature 004's four
surfaces are exactly such consumers.

**What a fix looks like**: a failed run returns a non-2xx status, or the 200 body carries
an explicit error the caller can read. Either is fine; silence is not.

---

## `policy.expires_after_seconds` is declared in config.yaml and never read — FIXED 2026-10-19 (c7e4275)

**Decided: the rules file wins.** The config key is deleted, and setting `expires_after_seconds` or `threshold_targets` in config.yaml is now a validation error naming the rules file's `confirmation:` block — rejected, not ignored, since pydantic ignores unknown keys and a silently inert key is the defect. Reasons: `threshold_targets` already lived only there, the rules file hot-reloads, and it is what enforcement already read. The original report follows.


**Found 2026-08-25 while enabling the engine.** `PolicyConfig` declares
`expires_after_seconds`, and nothing reads it: `PolicyMiddleware` takes expiry from
`ruleset.expires_after_seconds`, which the `ConfigLoader` parses out of the RULES file's
`confirmation:` block. Setting it in `config.yaml` changes nothing.

`threshold_targets` is the same story from the other direction — it exists only in the
rules file, so a reader of `config.yaml` has no way to discover it.

This is the built-but-never-consumed family on a **configuration** surface, which is
worse than on a code one: a config key that looks settable and is inert gives an operator
a false belief about a security setting they deliberately changed. Nobody would notice
until an action expired at four hours after they had set forty.

**Where it should be decided**: either `build()` passes the config values through to the
loader (config wins), or the key is deleted and the rules file is documented as the only
home (rules win). Either is defensible; two homes for one setting is not.

The generalised wiring gate planned for Feature 004 Phase 6 scans code, not config
schemas — so it would not catch this. Worth widening its scope, or noting the limit.

---

## A rules change orphans the actions already pending under the old rules — FIXED in Feature 004 (T090e/f: 1c7af03, 7d1c786)

A rules change now supersedes every pending action the new rules no longer require confirmation for, on the next use of the rules. It is claimed through the single confirmation path and NOT run. A read surface (the inspector) never triggers the sweep, nor consumes the change (7f0e683). The history below is kept as the occasion.


**Found 2026-09-23, by walking into it.** A user asked the assistant to read their email.
The classification rules did not match the connector tool names, so three read-only calls
became Tier 3 and sat in the pending store. The rules were then fixed — those tools are
Tier 1 now — and the three pending actions became **permanently un-confirmable**:

- `recognise` refuses a bare "approved" while more than one action is pending, correctly.
- The user cannot name one, because at the time those were created the plan text did not
  show the action id (fixed separately).
- Nothing supersedes an action whose tool is no longer Tier 3.

So they blocked every subsequent confirmation for their full four-hour expiry, and the
only remedy was running a script inside the container. The user could not clear their own
inbox-reading request.

**Why it is not just a migration nuisance.** `PendingAction` records `tier_at_statement`
deliberately — the tier in force when the plan was stated — so that a later rule change
cannot retroactively authorise something. That is the right property. Its consequence is
that a pending action outlives the rules that produced it, and nothing reconciles the two.

**Proposed fix**: on rule-set reload, supersede any pending action whose tool no longer
classifies Tier 3, with a reason naming the change. `Outcome.SUPERSEDED` already exists
and had no producer. The direction is safe: it can only ever *remove* a confirmation
demand that the current rules say is unnecessary, never grant one.

**What it must not do**: execute the superseded action. The user asked for a tool call
under rules that required approval; the answer is to stop asking, not to proceed
unasked.

**Related**: this is also the second time in one day that the unbuilt pending-confirmations
surface (Feature 004, Surface 1, Phase 3) was the thing standing between the user and a
working feature. A decline control would have cleared this in one click.


---

# Carried forward from the October audit (specs/AUDIT-2026-10.md)

Phase 1 (branch `phase-1-wiring`) fixed the items listed in the audit's Decisions section. These were found and deliberately not fixed in it. Each has the condition that reopens it.

## Real-world target drift needs live resolvers — DEFERRED (owner, 2026-10-19)

Phase 1 (a214aaf) made the FR-029 re-check run on both confirmation routes, computed in one place. But targets are resolved from a call's ARGUMENTS, which are frozen into the pending action, so the re-check catches a changed resolver or an altered record and **cannot see the world move**. That needs a live, per-tool resolver, plugged in at `PolicyMiddleware.recheck_targets`.

**Scope, as decided**: two tools only, the ones where acting on a stale set does damage:
- **calendar decline / delete**: re-read the named events and confirm each still exists, unchanged, before acting;
- **email send**: re-read the draft and recipients and confirm they are what was stated.

**Reopens when**: those workers (calendar, email) are in daily use. Not before: a resolver for a worker nobody runs is code with no production caller.

## Subagent provenance: `delegation_chain` is never set (audit P-5)

Nothing in production sets it; the subagent executor's context is `{thread_id, app_config}`, so a subagent's Tier 3 request is recorded as `lead_agent` with an empty chain (FR-033 unmet). `PolicyMiddleware` also never suspends, so confirming a subagent-only tool raises `LookupError`. **Reopens with**: the subagent suspend/resume work (003 FR-031/032).

## The watcher's UNKNOWN state is unreachable (audit W-2)

The Claude adapter drops undated records, so every discovered session has dated records, and a session whose records are all uninterpretable resolves to a confident WORKING/STALLED — what FR-006 forbids. **Reopens with**: Feature 005's Codex adapter, which touches the same resolution path.

## The live e2e test inherits its condition (audit §3)

`test_client_e2e.py::...test_a_requested_tool_is_called_and_its_result_comes_back` runs only when `OPENAI_API_KEY` is set and defaults to model `ep-20251211175242-llcmh`, which does not exist on OpenAI. Skipped in CI, red on any machine with a key: Article XIV's "a test must not inherit the condition it asserts". **Fix**: a deterministic fake model, or delete.

## Presence is never observed (audit T-7)

`TriggerLoop.recent_runs` is not wired and two `PresenceSignal` objects are built. Harmless until a local destination exists (`auto` resolves remote with no local one). The run store has no cross-thread "recent runs" query to feed it. **Reopens with**: the voice / local destination feature.

## A cron firing held behind an exchange is expired, not delivered — QUESTION

`release_queued` releases with `QUEUE_EXPIRED` whether the exchange ended or the bound ran out, and FR-013c expires un-recheckable types (cron) on any non-immediate release. So a morning briefing that waited for an exchange to end is dropped. Literal FR-016c; probably not the intent for "the exchange ended". **Reopens when**: the owner rules on it.

## The embedded Python client now refuses tools by default

With the policy on by default and failing closed (4dd013c), the embedded client — which builds agents without the gateway — refuses every tool call until it calls `app.policy.registration.install()` or sets `policy.enabled: false`. Intended, and a visible change for library users. **Reopens if**: the client should install the policy layer itself (it lives in the harness, which must not import `app`).

## Smaller engine items not taken in Phase 1

- T-9: `RuleRunner.default_tools` is never set, so `configure_tools` never runs.
- T-10: hot reload covers rules only; `quiet_hours` and `coalesce_window` need a restart.
- T-12: the firing-retention window is never read; a deleted rule thread fails forever rather than being recreated.
- A delivery failure is recorded FAILED and not retried (FR-017's trade). A proactive message is not added to the destination conversation's thread, so a reply to it in Telegram lacks its context.

## Smaller policy and watcher items not taken in Phase 1

- P-6: `explain()`/`render()` and `limits.describe_*` have no production caller — Feature 004 Phase 6 (T070, the policy inspector).
- P-7: lazy expiry is read-check-resolve without a claim; two workers can both announce an expiry.
- P-8 (unverified): the web confirm route invokes tools without the injected runtime the chat path adds.
- W-3/W-4: `OnDemandModelSummarizer` and `observe_only_notice` have no production caller. W-5: `SessionState.FAILED` is never produced.

## An intermittent multi-worker failure, seen once

`tests/policy_multiworker/test_cross_worker_confirmation.py::test_confirming_through_both_routes_at_once_executes_once` failed once inside a long `-x` run on 2026-10-19, before any Phase 1 policy change. Not reproduced in 24 runs since. Because it is a concurrency test, a flake may be a real double-execution race. **Reopens on**: a second occurrence; capture the assertion.

---

# Found in the Phase 1 live end-to-end check (2026-10-19)

Fixed in Phase 1 and recorded here because the suite could not have found them, since its test world lacked the condition: the Telegram token written to the gateway log by httpx (9ee53cc); the engine's own gateway calls rejected by CSRF (d99cf1a); the busy check refused by the SQL run store for want of a user context, and the 30 s rule timeout cancelling ordinary agent runs (0bffde7); an unhelpful watcher error and a hold reason that claimed an observation it had not made (540cf5e). Each test world now includes the condition: the fake gateway mounts the real CSRF middleware; the busy tests use RunRepository.

Still open:

## Held proactive messages live in memory

`InterruptQueue` (messages held behind an exchange) and the coalescing window's in-flight firings are not persisted across a gateway restart, and the event is already fingerprinted when it is held. A restart — including the dev server's `--reload` — while a message is held loses it silently. **Reopens with**: Feature 004 T051 (triggers surface), which needs held firings to be readable anyway.

## A newly enabled daily rule fires its previous instant, late

With the 24 h catch-up window, enabling a daily rule two minutes before its time also fires yesterday's instant immediately, labelled late. Seen while preparing the E2E (worked around with a date-pinned schedule). **Reopens with**: the cron catch-up question above; recording a rule's first-seen time would fix it.

## The dev gateway reloads on any change under backend/, tests included

`uvicorn --reload` watches all of `backend/`, so editing a test restarts the gateway, and with it the trigger engine and any held message (see above). **Reopens with**: the first time it costs a held message; `--reload-dir app --reload-dir packages` would narrow it.

---

## Feature 004 — what it deliberately did not do (T094)

- **No rule editor** (FR-036). The policy and trigger surfaces are read-only. `tests/gates/test_read_surfaces_do_not_write.py` enforces that the read routers and views write nothing. An editor would have to write through one of them. **Reopen** when editing rules by hand in the file is the thing the owner actually complains about.
- **Mobile is out of scope.** The surfaces are laid out for a desktop browser. They are not tested at phone width.
- **The browser worker is still open** (its own entry above). Feature 004 neither built nor unblocked it.
- **Trigger firing reasons are shown verbatim, not redacted** (FR-019 says verbatim). They are written by the engine, not taken from sessions, pages or email. If a reason ever quotes outside content, route it through `app/gateway/display_redaction.py` like the others.

## Gates the Feature 004 audit judged one-off and did not generalise

From `specs/004-assistant-ui-surfaces/gate-scope-audit.md`. Each is a real gap and none is in 004's scope. **Reopen any one** when its "next instance" occurs, or when the code it guards is next touched.

- **Single dispatch** (`tests/policy/test_gate_single_dispatch.py`). It matches only a bare-name `create_agent(` call, and compliance is a substring anywhere in the file. An aliased or attribute call, or a second bypass in a compliant file, slips through.
- **Tool surface** (`tests/workers/test_gate_tool_surface.py`). It covers Gmail only, calls the filters directly although its docstring says "final assembled list", and supplies its own deny list rather than the shipped one. A non-Gmail email toolkit with no `mcpServers` entry would keep every tool.
- **Transitive import lists** (`test_no_banned_imports.py`, `test_no_core_imports.py`). Hand lists: the engine's misses `election.py` and the sources; the watcher's misses `server.py`. Fix: import every submodule.
- **Channel send boundary** (`tests/test_channel_redaction_boundary.py`). It checks only `self.send` in direct `Channel` subclasses. Not covered: `send_file`, calls from outside the class, and raw client calls (`telegram.py:183`, `slack.py:194`, fixed text today).
- **Read surfaces** (`tests/gates/test_read_surfaces_do_not_write.py`). An enumerated list, one call deep. A new read router not added to the list, or a write two calls deep, would pass.
- **Zero writes** (`tests/session_watcher/test_zero_writes.py`). One adapter. Parametrise it when Feature 005's Codex adapter lands.
- **MCP page colours.** `components/workspace/mcp/mcp-server-detail.tsx` hardcodes `bg-white` and hex colours with no dark variant. The T088 token check covers the Feature 004 surfaces only. Extend its surface list when that page is next touched.
- **Frontend exports nothing imports.** ESLint's `no-unused-vars` cannot see one. That needs knip or ts-prune.

## Unwired code the generalised wiring gate found — wire it or delete it — TRIAGED 2026-10-19 (pre-005 hygiene PR)

**Resolved:**
- **Wired 6:** `limits.py` describe_absent, describe_tier and describe_expiry, plus ABSENT_CAPABILITIES; `confirm.restate` (FR-035 was unmet); `McpSecretsVault.delete_all_for_server` (secrets outlived their server).
- **Deleted 35.**
- **Reclassified 3:** they were reached all along, by langgraph.json, by the public client API and as a type bound.
- **Left 10 for Feature 005:** listed in `specs/005-project-ledger/plan-inputs.md` and tagged in the whitelist.

The original report follows.

`tests/gates/test_wiring.py` (T079) found **54 public definitions that nothing in production reaches**. Each is whitelisted as `UNWIRED` in `tests/gates/wiring-whitelist.txt`, so the gate is green today only because of them. They are not all bugs: some are leftovers, some unfinished work. The notable ones:

- `app.policy.limits` (6): the FR-023 honest-limits wording, `describe_absent`, `describe_tier` and `describe_expiry`, plus their constants. This is the fifth "built and never called" instance.
- `app.trigger_engine.sources.calendar` / `completion`: sources whose rules are rejected at load since Phase 1. Delete the modules, or wire them with the feature that needs them.
- `app.policy.confirm.restate`, `explain.render`, `lineage.latest_user_turn`, `provenance.firing_rule`, and `PolicyDecision.explain`.
- `session_watcher.reply.observe_only_notice`, `summarize.on_demand_model.OnDemandModelSummarizer`, and two registry predicates.
- Harness helpers: memory queue introspection, OpenAI converters, idempotency helpers, `skill_storage` archive install.

**Rule:** removing an entry is the only way to resolve one, by wiring the definition or deleting it. The gate fails a stale entry, so neither can be forgotten.

## `tests/test_mcp*.py` fail in isolation (27 tests, NoReferencedTableError)

Run alone, they fail with `NoReferencedTableError`. In the full suite they pass, because another test's import registers the referenced table's model first. This is the same on `main`, so it was not introduced here. It is a test-isolation defect, not a production one: the gateway imports every model at startup. **Fix:** import the models in the MCP tests' conftest. **Reopen** if CI ever shards the suite.

## `e2e-tests` fails on main: two landing-page specs — FIXED 2026-10-19 (pre-005 hygiene PR)

**The cause was not a missing backend.** The landing page changed in 7639b43 (2026-06-11): the brand moved from a header h1 into the nav, and "Get Started" became "Start building" -> /workspace. The specs still asserted the old page. They now assert the current page and still use mock-api for the workspace step. The earlier note above ("the e2e workflow starts no backend, so two landing-page tests fail by design") was wrong about the cause.


`tests/e2e/landing.spec.ts` fails twice: "renders the header and hero section" (element not found) and "Get Started link navigates to workspace" (click timeout). It fails the same way on main's last three runs (7daced7, 14e857e, e3e23e2, back to 2026-08-25), and on PR #39, which touches no landing or e2e file. The job runs only when `frontend/**` changes, so a backend-only PR never shows it. It is red on every frontend PR, and that is the "red build that tells you nothing" problem the backend config step was added to fix. **Fix**: update the spec to the current landing page, or delete it if the landing page is no longer the product's entry.

## Phase 2.5 (navigation and speed) — left open

- **Creating automations from chat** ("every weekday at 9, brief me"): Feature 005. The write path it would use exists (`/api/automations`, validated, atomic, version-checked).
- **The Button `outline` variant is a solid black fill**, and was before Phase 2.5 too; the colour pass kept it, mapped to `primary`. Rows with an action (Connections, Automations' delete) therefore show solid buttons. A real outline (`border bg-background hover:bg-accent`) is the shadcn default; changing it touches every outline button, so it is a design call for the owner.
- **Contrast coverage**: `tests/rendering/contrast.spec.ts` covers the landing page and twelve workspace pages in both themes, but not a deployed MCP server's page (`/workspace/mcp/[id]`, which needs a running build to render) or the chat thread with real messages. The source check (`colour-tokens.test.ts`) covers every file.
- **Chat pages still ship katex and shiki** (~2.6 MB parsed): streamdown imports them statically. Lazy-loading them means patching or replacing the markdown renderer.
- **Dev mode** (`make daily-dev`) still sits at ~2.6 GiB at boot; with no Turbopack disk cache it can no longer grow and OOM-loop. Recommended Docker Desktop memory for dev mode: 12 GB. `make daily` needs well under the current 7.75 GiB.
- **The trigger engine's watcher client keeps its 10 s timeout**; the sessions page uses 2 s with a labelled last-known fallback. With the watcher now reading appends only (67 ms answers), the engine's timeout is not exercised; revisit if it is.
