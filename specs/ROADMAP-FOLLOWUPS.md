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
