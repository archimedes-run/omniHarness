# Phase 1 Contracts — Feature 004

Four routers under `app/gateway/routers/`. Three are read-only; one is not.

Every response distinguishes **"nothing to report"** from **"cannot tell"**. That is not
politeness — FR-008 and FR-014 both turn on it, and an empty list that means "we cannot
see" is the specific failure the sessions surface exists to avoid.

## `confirmations` — the only writing surface

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/confirmations` | Open actions across all workers, with `threshold_targets` and whether each action exceeds it |
| POST | `/api/confirmations/{id}/confirm` | Body carries `typed_count` when above threshold |
| POST | `/api/confirmations/{id}/decline` | |

Both POSTs call the **same** `confirm_flow` function the `before_model` chat path calls.
This is FR-004, and a gate asserts a single implementation exists.

Outcomes are distinct, never collapsed into a generic failure:
`executed`, `declined`, `already_resolved` (naming the prior outcome), `expired`,
`targets_drifted` (with old and new target lists), `threshold_not_met`.

`threshold_not_met` **must not consume or resolve the action** — a wrong count is a
failed attempt, not a decline.

## `sessions` — read-only

`GET /api/sessions` returns `{observability, staleness_seconds, sessions[], reachable}`.

`reachable: false` is the gateway↔watcher transport fact and is **separate from**
`observability`, which arrives inside the watcher's envelope. Collapsing them would undo
Feature 001's FR-011a. Each session carries `state`, `inferred` (whether the state was
observed or inferred), `idle_reason`, `observe_only`, `last_activity_at`, `summary`.

## `triggers` — read-only

`GET /api/triggers/rules` → `id`, `type`, `enabled`, `last_evaluated_at`, `last_fired_at`.
Both timestamps are nullable, and `null` renders as "not recorded", distinct from "never".

`GET /api/triggers/firings` → recent window: `rule_id`, `event_type`, `event_id`,
`outcome`, `reason`, `batch_id`, `at`. Reasons are passed through verbatim rather than
summarised into a status word (FR-019).

## `policy` — read-only

`GET /api/policy/rules` → the rules actually in force, including after a failed reload
left previous rules active (FR-029).

`GET /api/policy/explain?tool=<name>` → `{tier, deciding_rule, from_default}`. **Must not
execute the tool**; calls the same `classify()` used at live dispatch.

`GET /api/policy/audit` → recent Tier 3 executions: `actor`, `plan_as_stated`, `targets`,
`outcome`, `authorised_by`.

## Read-only, provable

The three read routers are asserted to contain no write call — no `save`, `claim`,
`resolve`, `record`, or `write` — by a test that sabotages itself by adding one (FR-030,
SC-014).
