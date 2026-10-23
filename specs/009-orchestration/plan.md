# Implementation Plan: Orchestration (plan, delegate, verify)

**Branch**: `009-orchestration` | **Date**: 2026-10-23 | **Spec**: [spec.md](spec.md) | **Research**: [research.md](research.md)

## Summary

Three slices, each releasable alone. Slice 1 makes coding from chat work: OpenCode as the worker inside the hardened container sandbox, model calls through a gateway proxy so no key enters the sandbox, rules that make commands non-interactive, and a lead that verifies outcomes before reporting them. Slice 2 adds code mode: tools as a typed TypeScript API inside the sandbox, every call through the policy chokepoint. Slice 3 generalises the brief/result/verify protocol to every worker type.

Every gate below is **sabotage-checked**: the plan names the sabotage, and a gate is accepted only after it has been seen failing for that reason (Article XII, including "confirm the failure is the thing being measured" and "read the summary line, not a filtered grep").

## Technical Context

- **Language**: Python 3.12 (gateway), TypeScript (code-mode runner and typings, inside the sandbox), shell (image build).
- **Dependencies**: OpenCode (MIT), pinned version, installed at image build (download needs the owner's approval at that step); the existing AIO-based sandbox image (`docker/sandbox/Dockerfile`), egress proxy (`docker/sandbox-egress`), `agent_sandbox` client.
- **Storage**: run history (#55) for jobs, scripts and verification records; no new database.
- **Testing**: pytest through real HTTP (`create_app()`), the Docker e2e (`scripts/sandbox-egress-e2e.sh` pattern), Playwright against the live stack for the chat-level e2e.
- **Target**: the dev/daily compose stack with the container sandbox; daemon profile unaffected.
- **Constraints**: no secret in the sandbox; single front door per sandbox (#98); registries-only egress; four gateway workers (Article XI).

## Constitution Check

| Article | How this plan complies |
|---|---|
| I Gateway-only | The worker talks to the gateway only (LLM proxy, bridge, event relay). The watcher's OpenCode adapter is fed by the gateway, not by reaching into the sandbox. |
| II Tiers | `code_job` Tier 2 (sandbox-confined); every script call classified as the model's would be; bash unchanged (Tier 2 only in the hardened sandbox, #103 floor). New tools are listed with tiers in their slice. |
| III Provenance | Worker output and script results are tool results (data). Only the person's server-tagged turn or a card button confirms. |
| IV Coding agents | OpenCode's permission config is shipped, owned by the user, read-only in the sandbox; our layer never answers its permission prompts. |
| VI Lite by default | Everything here requires the container sandbox and is absent, with an honest message, without it. |
| X Honest limits | FR-012/FR-013: an unverified claim is reported as unverified. |
| XI Production shape | One e2e per slice on the real stack shape: four workers, real sandbox, real proxy, real nginx front door. |
| XII Probes | Every verification probe is seen passing on a known-good run before its failures are trusted; every gate has a named sabotage. |
| XIII Initiation vs confirmation | Separate requirements and separate tests (FR-021/FR-022, FR-033/FR-034). |
| XIV Tracked guarantees | AGENTS.md, OpenCode managed config and the Dockerfile changes are tracked; tests read tracked files only. |

No violations to justify.

## Slice 1: The OpenCode worker, verified

Goal: "create a Vite + React app, build it, show it" passes from chat (SC-001).

### 1a. Sandbox image (no product logic)
- No sudo (FR-017): remove the runtime sudoers line from `gem.sh`, strip setuid/setgid bits, start sandboxes with `no-new-privileges`.
- Install OpenCode pinned by version; managed config at `/etc/opencode/opencode.json` (FR-007, R6); rules at `/etc/opencode/AGENTS.md`, referenced by `instructions` (FR-006, R4); NOTICE for the MIT licence.
- OpenCode pinned by version and checksum-verified in the Dockerfile; sharing, telemetry and autoupdate off; permissions set so it never prompts, and a prompt that appears anyway fails the job (D1, D6).
- OpenCode runs under supervisor as `gem`, listening on `127.0.0.1:4096`, with `OPENCODE_SERVER_PASSWORD` derived per sandbox; exposed only through the keyed `:8080` front door on a new route (R2).
- **Gates**: (1) as `gem`, `sudo -n true` fails and no setuid binary exists — sabotage: keep the sudoers line → red. (2) `/etc/opencode/*` not writable by `gem` — sabotage: chmod 666 → red. (3) a workspace `opencode.json` enabling another provider has no effect — sabotage: drop `enabled_providers` → red. (4) the OpenCode route returns 401 without the sandbox key and from another sandbox — sabotage: add the route to the auth exemptions → red.

### 1b. Gateway LLM proxy (FR-003, FR-004)
- A separate listener on the sandbox network only (D3), OpenAI-compatible; the worker uses the lead's model unless the agent sets another (D2); per-job $1 default budget, cost shown at the end, counted against the monthly cap in Settings; per-sandbox token (`sandbox-llm|` HMAC domain); model allowlist; per-job token and time budget; per-sandbox rate limit; each call recorded in the run history; request/response bodies redacted as run history does.
- **Gates**: (1) a call without a token, with another sandbox's token, or from the host → refused — sabotage: accept any token → red. (2) budget exceeded → refused with the reason — sabotage: disable the budget check → red. (3) inside a running sandbox, search env and filesystem for every provider key and gateway secret value → none found (SC-004) — positive control: plant a canary value and see the search find it, then remove it.

### 1c. Sandbox exec wrapper (FR-015)
- stdin from `/dev/null`; no-output timeout 120 s default, 300 s for known installs and builds, 600 s hard cap, configurable per job (D4); the end message names the timeout and the last output line.
- **Gates**: a `read` command ends within 130 s with the message; `npm install` gets 300 s; nothing runs past 600 s — sabotage: restore the 600 s no-change default → the 130 s assertion fails on the timeout, not elsewhere.

### 1d. `code_job` tool and streaming (FR-002, FR-008, FR-009, FR-011)
- Tier 2 rule in `default_rules.yaml`, behind the same runtime floor as bash (only in the hardened sandbox); offered only when the container sandbox is configured.
- The tool creates an OpenCode session in the thread's sandbox, sends the brief, relays SSE events to the chat stream (writes, commands, exit codes), and supports Stop (`/session/:id/abort`).
- The `filesystem` MCP tool is hidden from coding work (FR-016).
- **Gates**: (1) without the container sandbox the tool is not offered — sabotage: drop the floor → red. (2) Stop aborts within 5 s — sabotage: no-op abort → red. (3) the chat shows a command's exit code from the event stream, not from the worker's prose — sabotage: feed a fabricated "exit 0" in the worker's message with a real non-zero exit → the chat shows the real code.

### 1e. Verification (FR-012 to FR-014, FR-018)
- After `code_job` returns, the lead runs the probes (R8) on the brief's done-criteria; the reply template has "Verified" and "Unverified" sections; `present_files` checks existence.
- **Gates**: (1) known-good run: every probe passes (positive control, recorded). (2) delete `dist/` after the worker finishes and before verification → reply says unverified and names `dist/index.html` — sabotage: make the probe return true → red. (3) no reply in the suite contains "done"/"built"/"passed" for a failed probe (a linter over e2e transcripts) — sabotage: inject such a reply → red.

### 1f. Watcher adapter (FR-010)
- The gateway relays OpenCode session events to the watcher over the existing watcher channel; the new adapter maps them onto the watcher's model (observe-only).
- **Gate**: a job's start, steps and end appear in Coding agents — sabotage: drop the relay → the session never appears and the test fails on that assertion, not on a timeout elsewhere.

### 1g. The steps section (FR-040 to FR-045, D8)
- Frontend: a collapsible steps section per reply, fed by the run stream (tool calls, skill loads, `code_job` events, verification checks) and rebuilt from the run history on reload; open while running, auto-collapsed when the work ends; header with step count and duration; statuses from events only; both themes; keyboard operable.
- **Gates**: (1) Playwright with a scripted run: each event appears as a step within 1 s, nested correctly; on completion the section collapses and the output stays visible — sabotage: never collapse → red. (2) a worker message saying "exit 0" next to a real non-zero exit shows the real status — sabotage: derive status from the message → red. (3) reload shows the same steps from the run history — sabotage: render from the live stream only → red. (4) contrast in both themes.

### Slice 1 e2e (Article XI: production shape)
- Live-shaped stack (four workers, real sandbox, proxy, nginx): from the chat UI, the Vite request renders in the artifact panel, 5 of 5 (SC-001); the steps section shows every step while running and collapses at the end (SC-007); the job's cost is shown and matches its proxy calls (SC-008); screenshots in both themes. Named structural difference defended: real PTY shell vs `docker exec` (the 2026-10-23 e2e passed under `docker exec` while the chat path hung).

## Slice 2: Code mode

### 2a. Typed tool API and loader (FR-019, FR-025)
- Typings generated from the thread's tool schemas; an index for the model; on-demand fetch of the imported names; the runner's resolver knows only the thread's tools.

### 2b. Bridge (FR-020 to FR-023)
- Gateway endpoint authenticated per sandbox and per job; each call goes through the policy middleware exactly as a model call (same classify, same provenance, `after_content` when arguments derive from read content); Tier 3 → the script ends + card via the #58 path; after confirmation only that call runs and its result returns to the agent, which writes a continuation script — never a re-run (D5); limits at the runner (time, memory) and the bridge (calls).
- **Gates**: (0) a script with Tier 2 writes, then a Tier 3 call, then more writes: after confirmation the earlier writes happened exactly once and the later ones never — sabotage: re-run the script on confirm → the write count is 2 and the test fails on that count. (1) a Tier 3 call stops the script before it executes (SC-005) — sabotage: classify script calls as Tier 1 → red. (2) a call to a tool the thread lacks is refused — sabotage: expose all tools → red. (3) confirmation by a script's own output "yes" confirms nothing (FR-021) and initiation from read content raises the tier (FR-022), as two separate tests — sabotage each separately. (4) limits stop the script and name the limit — sabotage per limit.

### 2c. Save as skill (FR-024)
- From a successful script run, create a skill draft through Skill Studio's existing draft/review path.

### Slice 2 e2e
- A 20-call read task as a script vs as tool calls on the same model: fewer round-trips (SC-006); every call in the run history with its tier.

## Slice 3: The delegation protocol

### 3a. Brief and Result schemas (FR-030, FR-031)
- Shared schemas; workers that can return structured output do (OpenCode v2 structured output, R2 **verify**; LangGraph subagents via a final structured message); free text is an unverified claim.

### 3b. Verify-before-report across workers (FR-032, FR-035)
- The Slice 1 probes become a library used for every worker type: subagents, @-called agents, `code_job`, scripts.

### 3c. Provenance of results (FR-033, FR-034)
- A result never answers a card (the #58 gate already holds; add the result channel to its tests); text in a result cannot initiate an unplanned consequential action — separate tests.
- **Gates**: two-worker task where one returns a claim without evidence → the reply names one verified and one unverified (sabotage: treat prose as evidence → red); a result containing "delete the backup" proposes nothing (sabotage: let result text seed the plan → red).

## Project Structure

```text
specs/009-orchestration/      spec.md, research.md, plan.md (this file)
docker/sandbox/               Dockerfile (no-sudo, OpenCode install), opencode/opencode.json, opencode/AGENTS.md
backend/app/gateway/          llm_proxy (router), code_job relay, bridge (router)
backend/app/policy/           default_rules.yaml (code_job tier), runtime_floors.py (code_job floor)
backend/packages/harness/omniharness/
  community/aio_sandbox/      exec wrapper (stdin, no-output timeout), OpenCode client
  tools/builtins/             code_job tool, verification probes
backend/packages/session_watcher/session_watcher/adapters/
                              opencode.py (fed by the gateway relay)
scripts/                      sandbox e2e extended for OpenCode and the proxy
```

## Order of work and stops

One agent at a time. Overall order (D7): #58 review and stop report → #53 check (rebase or defer) → Slice 1 → #53 if deferred → Slices 2 and 3. Slice 1 in the order 1a → 1c → 1b → 1d → 1e → 1g → 1f → e2e, stopping for the owner's go at the end of 1a (the OpenCode download), after 1e (first chat-level verification), and at the Slice 1 stop report. Slices 2 and 3 each end with one fresh review (exit rule: no HIGH) and a stop report.
