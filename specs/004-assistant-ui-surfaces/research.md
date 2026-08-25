# Phase 0 Research — Feature 004

Every load-bearing mechanism was executed or read before being planned on. Where a
probe was used, its positive control is recorded alongside its result, because a probe
that has never been seen succeeding cannot support a negative finding (Article XII).

---

## R1 — Can `before_model` carry the chat confirmation path?

**Decision**: Yes. Chat confirmation is implemented as a `before_model` /
`abefore_model` hook on the policy middleware.

**Measured, not assumed.** A probe built a real agent via `create_agent` with a
tool-capable fake model — the same `ToolCapableFake` pattern 003 needed after a plain
fake failed at `bind_tools` before reaching its subject.

| Step | Result |
|---|---|
| **POSITIVE CONTROL** — is `before_model` invoked at all in a real agent run? | **invoked 1 time** — the seam exists in this stack |
| Read the latest human turn from `state["messages"]` | works |
| `recognise(...)` against `open_actions(now)` | returned `CONFIRM` |
| `claim(action_id, claimant)` | returned the claimed action |
| Result reaches the conversation | `['yes', 'Executed calendar_decline on 2 target(s).', 'ok']` |

The injected message lands **before** the model's own reply, so the assistant narrates
the outcome rather than the user seeing a bare system line.

**A first run of this probe failed, and the failure was not the seam.** It sent
`"yes, do it"`, which normalises to `"yes do it"` and is not in `_CONFIRM_FORMS` — a
closed set, exactly as designed. The probe was wrong, not the mechanism. Recorded
because "recognise never completed" would have read as a finding about `before_model`.

**Signature confirmed from the installed package**, not from memory:
`before_model(self, state, runtime) -> dict[str, Any] | None`, returning state updates.
langchain 1.2.17 exposes `before_agent, before_model, wrap_model_call, wrap_tool_call,
after_model, after_agent` and their `a*` variants.

**Alternatives considered**: `wrap_tool_call` — rejected, and this is why the path was
never built: it fires only when the model requests a tool, and a bare "yes" produces no
tool call. `wrap_model_call` — would work, but wraps the call rather than preceding it,
giving no benefit and more surface. An out-of-band gateway route only (Option B from the
verification findings) — rejected by decision: it leaves chat confirmation broken, which
is the live defect.

**Note for implementation**: the probe stopped at `claim` and left the action open.
`execute_confirmed` (which resolves and audits) must follow, or the claim leaks.

---

## R2 — Surface 2: how does the gateway reach the session registry?

**The constraint**: `SessionRegistry` is **in-memory in the watcher's own process** —
verified, it has no path, no serialisation, no persistence. The gateway imports only
`session_watcher.redaction`. The watcher exposes `list_sessions` and `session_status` as
MCP tools over SSE, plus a `/health` route on a Starlette app.

### The options, with the tradeoff stated before the choice

**Option A — the gateway reaches the watcher's server per request.**

- No change to Feature 001's package. `list_sessions` already returns an envelope
  carrying observability and staleness — precisely what FR-013 needs.
- Freshest possible data.
- **The failure mode the other three surfaces do not have**: rendering this page
  depends on a second process being up. The other three read local files or in-process
  state and cannot fail this way.

**Option B — the watcher publishes its registry to shared storage.**

- The gateway reads a local file, so its failure profile matches the other surfaces.
- Requires new code in the 001 package, which currently persists nothing.
- **Blurs two conditions that FR-011a of Feature 001 exists to keep apart.** A stale
  file means either "the watcher is running but has not observed anything recently" or
  "the watcher is dead". Those are different facts, and the registry's own
  `Observability` enum was built specifically so they never collapse.

### Decision: Option A

The deciding argument is not freshness, it is **distinguishability**. FR-013 and FR-014
require live, stale-with-age, and unavailable to remain three separate things, and
FR-014 forbids rendering an empty list when the truth is "we cannot see". Option A keeps
four conditions distinct — unreachable (transport), never-observed, stale, live — because
unreachability is a transport fact and the other three arrive inside the envelope.
Option B conflates unreachable with stale in the one artifact it has to work from.

**The failure mode is acknowledged, and it is converted rather than ignored.** The
sessions surface must render "the watcher cannot be reached" as a first-class state, not
as an error page or an empty list. FR-013 and FR-014 already require exactly that
affordance, so the dependency shows up as a specified state rather than as an outage.
This is recorded so that a later reader does not mistake the dependency for an oversight.

**Alternatives considered**: having the gateway host the watcher in-process — rejected,
it would undo Feature 001's process separation and Article I's gateway-only rule cuts
the other way here. Polling the watcher into a gateway-side cache — a variant of B with
the same conflation, plus a second staleness clock.

---

## R3 — The built-tested-never-called gate: a real gap, measured

**Decision**: Add a wiring gate scoped to `app/policy`, generalised from Gate 4, and run
it against every feature module rather than one.

**This was tested, not argued.** Gate 4's detection logic was extracted and pointed at
`app/policy`. It flags 21 names as defined-but-unreferenced-inside-the-module, and the
list contains **`recognise`, `execute_confirmed` and `open_actions`** — precisely the
three functions that constitute the missing confirmation path.

So the answer to "should an existing gate have caught this" is: **yes, and the reason it
did not is that Gate 4 is hardcoded to one module.**

```python
MODULE = Path(__file__).resolve().parents[2] / "app" / "trigger_engine"
```

Feature 003 shipped four gates — single-dispatch, structural, raise-only, tool-surface —
and no wiring gate. The repo-level gate (`tests/test_module_wiring.py`) does cover
`app/policy`, and correctly passes it: `app/gateway/app.py:313` imports
`app.policy.registration`. **The module has a consumer; three of its functions do not.**
That is exactly the gap the user identified, and the two existing gates sit on either
side of it.

### What the generalised gate must do differently

Running Gate 4's logic verbatim over `app/policy` produced two classes of false positive,
both of which the real gate must handle:

1. **Framework-invoked methods.** `wrap_tool_call` and `awrap_tool_call` have no caller in
   any repository file; the agent runtime calls them. Needs an exemption list in the same
   shape as the existing `abstractmethod` exemption. `before_model` joins it.
2. **Cross-module consumers.** References must be scanned across `app/` and `packages/`,
   not only within the module — otherwise every entry point is flagged.

A third issue is a genuine scanner bug worth fixing in Gate 4 itself:
`from app.policy.registration import install as install_policy` records only
`install_policy`, so the original name `install` reads as unreferenced. The gate must
record **both** the alias and the imported name.

### What the gate finds today, beyond the confirmation path

After a repo-wide reference scan with framework hooks exempt, 17 names remain. They are
not all defects — several are read APIs this feature is about to consume — but two more
are live:

- **`expire_due` has no production caller.** Its own docstring says it exists so "the
  user can be told rather than seeing silence" (Feature 003, FR-019). `open_actions`
  filters expired actions at read time, so nothing displays wrongly — but nothing ever
  tells the user their action expired, which is the requirement.
- **`Outcome.DECLINED` and `Outcome.SUPERSEDED` are never produced.** Consistent with
  there being no completion path: nothing can decline what nothing can confirm.

**Alternatives considered**: `vulture` — already tried and rejected during 002 for
producing 30 findings on a clean tree, which is how a whitelist stops being read. That
reasoning still holds.

---

## R4 — Frontend conventions

**Decision**: Follow the existing shape exactly; introduce nothing new.

Verified by reading: `@tanstack/react-query` v5.90.17, per-domain hooks at
`src/core/<domain>/hooks.ts`, routes under `src/app/workspace/<area>/`, components under
`src/components/workspace/<area>/`.

Rendering assertions run in CI only. `frontend/tests/rendering/` with
`playwright.theme.config.ts` is the established pattern, measured working; local
Playwright cannot obtain a browser bundle in this environment (448 KB against 369 MB in
CI).

**Colour tokens only.** There are 99 hardcoded colour utilities across 20 existing files;
new surfaces must not add to that count, and the theme-rendering job is the check.

---

## R5 — Threshold default for FR-009

**Decision**: 10 resolved targets, **and it is a guess**.

It is labelled as a guess in FR-009 itself — the artifact a reader sees — not only here.
There is no usage data to set it from: the confirmation path has never run in production,
so no distribution of target counts exists. The value is set where a single click stops
feeling proportionate to the blast radius, and is expected to move once the surface has
been used (Article X).
