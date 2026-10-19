# Gate scope audit (T077, T078)

**Date**: 2026-10-19 · **Tree**: `phase-2-ui-surfaces` before any gate was changed (FR-039: report before changing).

A *gate* here is a test that scans code or config structurally. Behavioural tests that call themselves "gate" are listed and marked as such, because a behavioural test cannot observe wiring.

Verdicts:
- **general**: the scope matches the property.
- **correctly narrow**: the subject really is one module.
- **one-off**: scoped to the module or shape that motivated it, so it misses the next instance (FR-039).

Spot-checked by hand and confirmed: the `limits.py` orphans, the `import … as` bug at `test_wiring.py:126`, the state of `DisclosureLedger.apply` at `fe83293~1`, and the undeclared `cryptography` import.

## Findings that change the plan

1. **A fifth unwired instance is live, and both wiring gates are green on it.**
   - `app/policy/limits.py` defines `describe_absent`, `describe_tier` and `describe_expiry` (lines 28, 33, 42). That is the FR-023 honest-limits wording.
   - Nothing calls any of them: not in `app/`, not in `packages/`, not in `tests/`.
   - Gate 4 cannot see them, because it scans only `app/trigger_engine`.
   - `test_module_wiring.py` cannot see them either, because its unit is a whole top-level package and `app.policy` is imported.
2. **Submodule orphans.** `app/trigger_engine/sources/calendar.py` and `completion.py` have no production importer. This is admitted in a comment and enforced by no gate. Phase 1 made such rules rejected at load, but the modules remain.
3. **FR-043's narrative needs a correction.** Before `fe83293`, `DisclosureLedger.apply` had *no* non-test reference, not even within `disclose.py`. Gate 4 missed it purely through scope.
   - The own-module rule is still needed, and a live case exists: `expire_due` is called by its sibling `open_actions` (`pending.py:134`).
   - The rule means something only if a reference counts **when its referrer is itself wired**.
4. **The `import … as` bug is real, and a flat-name gate hides it by accident.**
   - Gate 4 records only the alias (`test_wiring.py:126`). `app.py:298` imports `install as install_policy`.
   - `app.py` also calls `log_redaction.install()`, so a flat name set marks `registration.install` as wired by coincidence.
   - 153 of 953 public function names in `app/` + `packages/` are defined in more than one file.
   - 17 aliased from-imports exist in production.
5. **T079's hook-exemption list is incomplete.** This codebase also defines `wrap_model_call`, `awrap_model_call`, `aafter_model`, `before_agent` and `after_agent`. Exempt the whole `AgentMiddleware` hook set, on `AgentMiddleware` subclasses, not by bare name.
6. **The runtime-dependency gate's next instance already exists.**
   - `cryptography` is imported at module top in `app/gateway/mcp_secrets.py:23`, declared in no pyproject, and present only transitively.
   - `discord` (`app/channels/discord.py:47`, imported lazily) is absent from `uv.lock`. Whether that is a deliberate optional extra is UNSURE.

## Table

| Gate | Checks | Scope (file:line) | Verdict | Next instance, and plausibility (T078) |
|---|---|---|---|---|
| `tests/trigger_engine/test_wiring.py` (Gate 4) | Each public function and UPPERCASE constant has a non-test reference; whitelist with reasons and task expiry | Defines and references from `app/trigger_engine` only (`:34`, `:61-62`, `:106`); task ids resolve against spec 002 (`:38`) | **one-off** | Already happened: `recognise`, `claim`, `execute_confirmed`, `expire_due`, `DisclosureLedger.apply`. **Live:** `limits.describe_*`. Certain |
| `tests/test_module_wiring.py` | Each top-level package under `app/` has an importer outside itself | Subjects are the top level of `app/` (`:53-63`); misses `from app import x` (`:84`) | **one-off in granularity** | **Live:** `policy/limits.py`, `sources/{calendar,completion}.py`. Certain |
| `tests/policy/test_gate_single_dispatch.py` | Every `create_agent` site reaches the shared middleware | `app` + `packages` (`:20`) | **general** scope, narrow detector: bare-name call only (`:56`); compliance by substring (`:62-64`) | An aliased or attribute `create_agent`. Medium. Fix the detector, not the scope |
| `tests/policy/test_gate_raise_only.py` | *Behavioural*: a lowering exception fails the load | the policy `ConfigLoader` | **correctly narrow** | — |
| `tests/policy/test_gate_structural.py` | *Behavioural*: `recognise` and `apply` work | constructs its subjects itself | **correctly narrow, but a unit test**; cannot observe wiring, and was green while both were unwired | Belongs to the generalised gate |
| `tests/workers/test_gate_tool_surface.py` | The email send capability is absent | Gmail-only names (`:28`, `:38`, `:47`); calls the filters directly (`:24-25`) although its docstring says "final assembled list" | **one-off** | A third assembly path, or another email toolkit with no `mcpServers` entry (surface `None` keeps everything). Medium to high |
| `tests/test_shipped_paths.py` | Required files are tracked; no test reads a gitignored path | Hand-enumerated lists (`:45-59`, `:120-141`); gitignored names hardcoded (`:184`); line-based (`:204`) | **one-off (enumerations)**, correct roots | A Prettier-wrapped `join(\n __dirname, …)` (already present at `frontend/tests/unit/theme.test.ts:130`); `.env` is not in the list. High |
| `tests/test_harness_boundary.py` | The harness never imports `app` | `packages/harness` (`:13-15`) | **correctly narrow** | String `use:` loading is by design |
| `tests/trigger_engine/test_no_banned_imports.py` | The engine never imports core, statically or transitively | Static check: the module (correct). Transitive check: imports only `runner`, `loop`, `lifespan` (`:43`) | static **correctly narrow**; transitive **one-off** | `election.py` and the source modules are not covered. Medium to high |
| `tests/session_watcher/test_no_core_imports.py` | Same, for the watcher | Transitive list hardcoded (`:58-64`), omits `server.py` | transitive **one-off** | `server.py` gaining a core dependency. Medium |
| `tests/session_watcher/test_zero_writes.py` | *Behavioural*: observation writes nothing | One adapter (`:17`) | **correctly narrow** today | A second adapter (Feature 005's Codex adapter). Medium |
| `tests/test_channel_redaction_boundary.py` | `Channel.deliver` is the only `self.send` caller | `self.send` in direct `Channel` subclasses (`:127`, `:133`) | **one-off in pattern** | `send_file`; `channel.send(...)` from outside the class; raw client calls (`telegram.py:183`, `slack.py:194`, which carry fixed text today). High |
| `tests/test_runtime_dependencies.py` | Named production imports are runtime dependencies | A hand list of two (`:20-23`) | **one-off** | **Live:** `cryptography` (transitive only), `discord` (UNSURE) |
| `tests/session_watcher/test_dependency_bounds.py` | `mcp<2` | One package | **correctly narrow** | — |
| `tests/gates/test_single_confirmation_path.py` | One `.claim(` site | `app` + `packages` | **general** | A bound-method alias. Low |
| `tests/gates/test_read_surfaces_do_not_write.py` | Read surfaces: GET only, no writes | Enumerated surfaces, one call deep | **correctly narrow subject** (FR-030 names them), enumerated | A new read router not added; a write two calls deep. Medium |
| `tests/test_skills_bundled.py` | Every SKILL.md front matter parses | `skills/public` | **general** | — |
| `frontend/tests/unit/sidebar-tokens.test.ts` | No literal text colour in one cva call | One file | **one-off** | **Live:** `components/workspace/mcp/mcp-server-detail.tsx` hardcodes `bg-white` and hex colours. T088's surface check covers the Feature 004 surfaces; the MCP page is outside its scope and is logged below |
| `frontend/eslint.config.js` `no-unused-vars` | Unused locals and imports | Per file | **narrow by tool design** | An exported symbol nothing imports. Medium |

## Decisions (T078, T080)

**Generalised now:**
- **Gate 4 becomes `tests/gates/test_wiring.py`** (T079), covering every module under `app/` and `packages/`. It keys references by name with the referring file recorded, records **both** alias and original name for `import … as`, and counts a reference only from code that is itself reached from production (FR-043). It exempts framework hooks on `AgentMiddleware` subclasses and decorator-registered handlers. Its whitelist carries mandatory reasons.

**Fixed in place, because the defect is the detector rather than the scope:**
- **`test_runtime_dependencies.py`** now collects third-party imports from `app/` and checks each one against the declared dependencies. That surfaces `cryptography`, which then becomes a runtime dependency.

**Left narrow, with the reason recorded at the gate:**
- **`test_gate_raise_only`, `test_harness_boundary`, `test_skills_bundled` and the read-surfaces gate.** The subject genuinely is that scope.

**Logged as follow-ups, not changed in this feature:**
- The single-dispatch detector.
- The Gmail-only tool-surface gate.
- The line-based shipped-paths scan.
- The transitive import lists.
- The outside-the-class channel send.
- The MCP page's hardcoded colours.

Each is a real gap. None is in Feature 004's scope, and each is listed in `ROADMAP-FOLLOWUPS.md` with what would reopen it.
