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

## Accessibility lint rules — Feature 004 task

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

## A rules change orphans the actions already pending under the old rules — OPEN, Feature 004 T090e/f (Phase 2)

Unchanged by Phase 1 by decision: `Outcome.SUPERSEDED` still has no producer. First item of Phase 2.


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
