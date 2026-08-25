# The frontend has no Article XI equivalent

**Status**: known limitation, blocked on tooling. Stated here because a UI feature spec written against this codebase will inherit it, and it is better named than discovered.

## What Article XI requires, and why the frontend cannot satisfy it

Constitution Article XI: _a test environment that differs structurally from production hides defects of exactly the kind the test exists to catch. Where such a difference exists, at least one test MUST exercise the production shape._

The backend honours this. The multi-worker suite runs a real `uvicorn` at the worker count read from the compose file. The cross-worker confirmation test starts a real subprocess and fails if it cannot see two distinct worker pids.

The frontend has no such test, and the structural difference is the largest one there is: **every frontend test asserts component behaviour given props. None asserts what a user sees.**

## Two bugs that lived exactly in that gap

Both were reported by the user, and neither was detectable by any check in the repository.

### Dark mode did nothing

The toggle rendered, called `useTheme()`, ran `setTheme("dark")`, and next-themes correctly set `class="dark"` on `<html>`. Every step worked.

`.dark` defined 31 tokens of which **24 were byte-identical to `:root`** — including `--background` (white in both), `--foreground`, `--card` and `--primary`. The theme switched to itself.

- A unit test asserting the toggle calls `setTheme` would have **passed**.
- A test asserting `class="dark"` lands on `<html>` would have **passed**.
- Type checking, linting and every existing test **passed**.

The assertion that catches it is: _toggle, then read the computed background colour_. That is a rendering assertion.

### Model selection stuck on Flash

Not a frontend bug at all — the single configured model declared `supports_thinking: false`, and `getResolvedMode` correctly collapses every mode to `flash` in that case. Diagnosing it required tracing the frontend resolver to a backend config value, which no frontend test has visibility into.

## The tool that would close it, and why it is not here

A rendering assertion needs a real browser. Playwright is the tool, it is already a dependency (`@playwright/test`), and the e2e suite is scaffolded.

**A browser bundle cannot be produced in this environment.** After repeated clean removals and `npx playwright install chromium`, the browser directory is created and stays at **448 KB** against roughly 350 MB for a complete build. The download does not progress. Every launch fails at process start, which a 448 KB bundle fully explains.

This is the **same blocked bundle** that cut the browser worker (FR-016, FR-017, SC-007) from Feature 003. One tooling limitation, two consequences: a feature cut, and a testing tier absent.

Whether a _complete_ bundle would run here is **untested** — one cannot be obtained to test with. The limitation is about acquiring the browser, not about running it.

## What this means for UI acceptance criteria

Until a browser is available, UI acceptance criteria will assert **component behaviour given props**, not **what the user sees**. Write them knowing that, and prefer criteria a props-level test can actually check.

Where a criterion genuinely requires rendering, say so in the spec rather than substituting a weaker assertion that looks equivalent. A criterion asserting `setTheme` was called reads as if it covers "dark mode works". It does not, and that gap is invisible once the criterion is written.

### What is available, and worth using

Cheap checks that catch _specific_ failures without a browser:

- **`tests/unit/theme.test.ts`** parses `globals.css` and asserts `.dark` and `:root` differ on the tokens that govern the page. Not a rendering assertion — it cannot prove dark mode works — but it catches the exact failure that occurred, which is easy to reintroduce because scaffolding a theme block by copying is the natural way to write one. Verified by sabotage: 8 of its 9 assertions fail against the original CSS.
- **`noUnusedLocals` / `noUnusedParameters` / `no-unused-vars: error`** catch "a handler nothing references". Free, and enabled.

### What was considered and NOT built

An AST check for _a rendered control with no handler_. Roughly an afternoon: walk the TSX for interactive elements and assert each has a handler prop resolving to something.

Rejected for now because **it would have caught neither bug**. Both had handlers, both wired correctly, both ran. The backend gates that earned their keep all catch "this code is unreachable"; these bugs are the opposite — reachable code doing exactly what it says, against data that was wrong.

Building the check the last project needed rather than the one this project has is a failure mode worth naming. Revisit when a bug of that shape actually appears.

## What would close this

Any of:

1. A working Chromium bundle — a machine with access to the Playwright CDN, or a vendored bundle committed or fetched from elsewhere.
2. A CI job that installs the browser where the network permits, so rendering assertions run there even if not locally.
3. A different rendering target — jsdom plus a CSS-computation library — which is weaker than a real browser but not nothing.

Option 2 is likely the cheapest real fix: CI already installs Playwright for the e2e job, so the constraint may be local rather than universal. Worth measuring before assuming.
