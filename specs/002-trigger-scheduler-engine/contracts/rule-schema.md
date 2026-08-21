# Contract: Rule Schema

**Date**: 2026-08-21 | **Plan**: [../plan.md](../plan.md)

The rule file is this feature's **public interface** — the only surface a user authors by hand.
Changes here are breaking changes.

## Shape

```yaml
quiet_hours:
  start: "22:00"          # inclusive; may span midnight
  end: "07:30"
  timezone: "America/New_York"

defaults:
  coalesce_window_seconds: 60      # heuristic
  presence_threshold_seconds: 300  # heuristic
  queued_turn_max_wait_seconds: 300 # heuristic — AND the primary release path (FR-016b)
  fingerprint_retention: "24h"

rules:
  - id: blocked-session            # unique; the thread-map key
    type: watcher
    match:
      event: waiting-on-user
    prompt: |
      The session in {project} appears to be waiting on you.
      It last said: {last_message}
    destination: auto
    urgent: false

  - id: morning-briefing
    type: cron
    match:
      schedule: "30 7 * * 1-5"
      timezone: "America/New_York"
    prompt: "Summarise what happened across my sessions overnight."
    destination: remote
```

## Field rules

| Field | Required | Notes |
|---|---|---|
| `id` | yes | Unique. Duplicates are a **load-time error** (FR-006) — it is the thread-map key. |
| `type` | yes | `cron` / `watcher` / `completion`. `calendar` is reserved and rejected with "not implemented". |
| `match` | yes | Type-specific. Validated per type at load. |
| `prompt` | yes | Template. Referencing a field the type cannot supply is a **load-time error**, not a render-time surprise. |
| `destination` | no | `remote` / `quiet` / `auto`. Default `auto`. `local` reserved. |
| `urgent` | no | Default `false`. Must be set explicitly; there is no implicit escalation (FR-014). |
| `enabled` | no | Default `true`. |

## Guarantees

**Hot reload** (FR-005): changes take effect on the next evaluation, no restart.

**Invalid config is inert** (FR-006): the previously valid configuration stays in effect and the
error is reported. A typo must not disarm the engine — a config that fails open is worse than one
that fails to load, because nobody notices.

**Renaming an id creates a new rule.** It gets a fresh thread; the old mapping is not inherited.
The id is identity, and inheriting across a rename would silently merge two rules' histories.

## Forward compatibility

`calendar` is accepted by the schema and rejected at load with an explicit not-implemented error
(FR-003) — so adding it later is a new source implementation, not a schema migration.

## What this contract does NOT cover

Rules cannot: name a thread directly (each rule owns one — FR-011a), address a destination not
registered, opt out of redaction, or opt out of the politeness gates other than via `urgent`.
These are deliberate omissions. A rule that could bypass quiet hours implicitly, or delivery
without redaction, would make Articles VII and VIII advisory.
