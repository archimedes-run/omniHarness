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

## A run that errors returns HTTP 200 with an empty body

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

## `policy.expires_after_seconds` is declared in config.yaml and never read

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
