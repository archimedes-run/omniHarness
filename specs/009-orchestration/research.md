# Research: Orchestration (009)

Sources are read on GitHub only (no packages downloaded). Each finding names its source. Claims marked **verify** are not yet seen working and must pass a probe with a positive control before the plan depends on them (Article XII).

## R1. OpenCode: what it is and its licence

- Repository: `github.com/anomalyco/opencode` (the former `sst/opencode` URL redirects there). "The open source coding agent."
- Licence: **MIT**, "Copyright (c) 2025 opencode" (`LICENSE`). Bundling it in our sandbox image is permitted with the notice kept; we add it to the image's notices.
- Decision: OpenCode is the coding worker. Rationale: it has a headless server with an OpenAPI spec and an SDK (R2), a provider abstraction that accepts any endpoint speaking the common chat-completions API (R3), AGENTS.md rules (R4), fine-grained permissions (R5) and managed config (R6), which together let it run with no secret inside the sandbox.
- Alternatives considered: the model vendors' own terminal coding agents (strong, but tied to their vendors' auth; putting their credentials in a sandbox breaks FR-003); our own LangGraph subagent with `bash` (that is what failed three times on 2026-10-23; it has no coding-specific loop).

## R2. Server mode and API (`packages/web/src/content/docs/server.mdx`, `sdk.mdx`)

- `opencode serve [--port <n>] [--hostname <h>] [--cors <origin>]`, default `127.0.0.1:4096`. HTTP basic auth when `OPENCODE_SERVER_PASSWORD` is set (username `opencode`, or `OPENCODE_SERVER_USERNAME`).
- OpenAPI 3.1 spec at `GET /doc`.
- Events: `GET /event` (SSE; first event `server.connected`, then bus events) and `GET /global/event`.
- Sessions: `POST /session` (`{ parentID?, title? }`); `POST /session/:id/message` (waits for the reply); `POST /session/:id/prompt_async` (returns 204); `POST /session/:id/abort`; `GET /session/:id/message`; `POST /session/:id/permissions/:permissionID` (`{ response, remember? }`).
- Health `GET /global/health`; files `GET /find`, `GET /file/content?path=`.
- SDK `@opencode-ai/sdk`: `createOpencodeClient({ baseUrl })`; `session.create`, `session.prompt`, `session.abort`, `event.subscribe()` (async iterator). **Structured output** only on `@opencode-ai/sdk/v2`: `format: { type: "json_schema", schema }`, optional `retryCount` (default 2); result at `result.data.info.structured`, failure as `StructuredOutputError`.
- Decision: the gateway (Python) talks to OpenCode's HTTP API directly from the OpenAPI spec; we do not need the JS SDK in the gateway. Structured output is how the worker returns the Result (FR-031). **verify**: structured output over the plain HTTP API (the docs show it via the v2 SDK).
- Placement: OpenCode listens on `127.0.0.1:4096` inside the sandbox. The gateway reaches it through the sandbox's keyed nginx (the same `:8080` front door, as a new authenticated route) so no new listener is exposed on the sandbox network (keeps #98's single front door). **verify**: SSE through the image's nginx with buffering off.

## R3. Pointing OpenCode at our LLM proxy (`providers.mdx`)

- A custom provider: `provider.<id>.npm` set to the AI SDK's chat-completions-compatible provider package for `/v1/chat/completions` endpoints (a different package for `/v1/responses`; exact package ids in the OpenCode providers docs), `options.baseURL`, `options.apiKey` (supports `{env:NAME}`), `options.headers` per provider, and `models` with `limit.context` / `limit.output`.
- Decision: one provider `omni` with `baseURL` = the gateway LLM proxy on the sandbox network and `apiKey` = `{env:OMNI_LLM_TOKEN}`, a per-sandbox token (HMAC of the gateway secret and the container name, domain `sandbox-llm|`). The token authorises nothing but model calls for that sandbox, within its budget. It is not a provider key (FR-003).
- The gateway is on the sandbox network already; its Host guard (`DEFAULT_ALLOWED_HOSTS` in `app/gateway/config.py`) gets a narrow exception for the proxy route by sandbox-network source, or the proxy is a separate listener. Open question Q3.

## R4. Rules files (`rules.mdx`)

- OpenCode searches upward from the working directory for `AGENTS.md`, then one vendor-specific rules file name; then the global `~/.config/opencode/AGENTS.md`; plus files listed in `instructions` in config, combined with the above. First match wins within each category.
- Decision: our rules ship tracked (`docker/sandbox/opencode/AGENTS.md`) and are referenced from the managed config's `instructions`, so a workspace cannot shadow them by writing its own `AGENTS.md` first (a workspace AGENTS.md is still read, in addition). Article XIV: the guarantee lives in the image, not in a gitignored or workspace file.

## R5. Permissions (`permissions.mdx`)

- Keys: `"*"`, `read`, `edit`, `glob`, `grep`, `bash` (pattern map, last match wins), `task`, `todowrite`, `skill`, `lsp`, `question`, `webfetch`, `websearch`, `external_directory`, `doom_loop`. Values `allow` / `ask` / `deny`. Defaults mostly allow; `doom_loop` and `external_directory` ask; `.env` reads ask.
- Decision: inside the hardened sandbox the boundary is the container, so `edit` and `bash` are `allow`; `external_directory`, `webfetch`, `websearch` are `deny`; `question` is `deny` (a non-interactive worker, FR-015's spirit). Article IV: these are the coding agent's own configuration, shipped by us and owned by the user; our layer never answers a permission prompt (a prompt that does appear is surfaced to the user, never auto-approved). **verify**: the permission event's shape in the SSE stream (the docs page does not name it; read it from `/doc`).

## R6. Config precedence (`config.mdx`)

- Merged, lowest to highest: remote `.well-known/opencode`; global `~/.config/opencode/opencode.json`; `OPENCODE_CONFIG`; project `opencode.json`; `.opencode` dirs; `OPENCODE_CONFIG_CONTENT`; **managed config files (`/etc/opencode/` on Linux)**; macOS MDM.
- `autoupdate: false`; `model`, `small_model`; `disabled_providers`, `enabled_providers` (disabled wins).
- Decision: our config is the managed file in the image (root-owned, read-only to the sandbox user once sudo is gone, FR-017), so a workspace `opencode.json` cannot re-enable a provider or widen permissions. `enabled_providers: ["omni"]`. **verify**: sharing off (the config page does not document a `share` key; find it in `/doc` or the schema) and no telemetry (look for any analytics endpoint in the source).

## R7. Code mode

- Shape: the agent writes TypeScript against generated typings (`import { github } from "omni:tools"`); a runner in the sandbox (Node 22 or Bun, both in the image) executes it with an import resolver that only knows the tools the thread has; each function is a stub that POSTs `{tool, args, job}` to the gateway bridge with the sandbox's key; the gateway runs the call through the same policy middleware chat uses and returns the result or a stop.
- Tier 3: the bridge returns a "stopped: needs confirmation" error; the runner ends the script; the gateway raises the card via the #58 delegated-confirmation path. Scripts are not resumable mid-execution; after confirmation the Continue re-runs the script with the confirmed call's one-shot grant (Q5).
- Limits: wall time and memory via the runner (`--max-old-space-size`, a timer), call count at the bridge.
- Only-needed definitions: the model sees an index (tool names and one-line descriptions); full typings are fetched for the names it imports.

## R8. Verification probes

- File: `stat` in the thread's mounted folders from the gateway (it mounts the same host folders), size > 0.
- Exit code: the command's exit status as recorded by the worker's event stream (OpenCode tool-call events) or by our sandbox exec wrapper; never the worker's prose.
- Renders: the artifact manifest validates (existing manifest validation), its entry exists, and a headless fetch of the preview URL returns 200 with a non-empty body (no browser needed for the gate; a browser screenshot is the Slice 1 e2e).

## R9. Interactive commands (FR-015)

- Observed on 2026-10-23: `create-vite` waits for answers in the AIO shell's PTY; the exec call waits for the 600 s no-change timeout. Decision: our exec wrapper runs commands with stdin from `/dev/null` and a no-output timeout of 60 s; OpenCode's own `bash` runs inside the same sandbox under the rules file and OpenCode's per-command timeout (**verify** its default and override).

## R10. How strong agents structure their loop (Slice 0)

Read on 2026-10-24 from public sources only: engineering posts and docs from model vendors, prompting guides for agentic use, open-source system prompts of terminal coding agents (including OpenCode's), an agent-interface paper and an agent benchmark paper. Products are not named here (D11); the owner has the source list. The practices Slice 0 adopts, and where each lands:

| Practice seen across sources | Where it lands |
|---|---|
| A todo tool used for tasks of 3+ steps, skipped for trivial ones; exactly one item in progress; ticked immediately; the tool is a no-op whose value is keeping the goal in view ("recitation") | FR-050, prompt `<working_loop>` 1, `write_todos` text |
| Give the agent a check it can run, and require evidence rather than assertions; "validation is the only path to finality"; mark an item passing only after testing; under-testing is named as the top failure mode | FR-051, FR-052, FR-053 |
| After repeated failures (about 3) stop patching: restate the task, list assumptions, change approach; never retry a call that needs the person; doom-loop detection on 3 identical calls | FR-054, tool-error and loop texts |
| Keep going until the task is resolved; infer the most useful action and use tools to discover missing details instead of guessing; do not stop early over context budget; ask before hard-to-reverse actions | FR-055, FR-057; "hard-to-reverse" is our policy tiers, not a model question |
| Respect a declined action and do not re-attempt it | FR-058a |
| Resume from where the agent was rather than restart; rebuild state from a written record (progress files, plan saved to memory) | FR-058, FR-059 |
| Compaction is the first context lever; tell the summariser what to keep; keep lightweight references (ids, URLs) instead of raw content | FR-059 plan record |
| Orchestrator-worker: delegate side work that would flood the main context; a brief with objective, output format, tools and limits; the subagent returns a condensed summary; the subagent starts with no memory, so the brief must be complete; do not run parallel workers that mutate the same things | FR-061, `task` text, Slice 3 FR-030 |
| Tool descriptions written for a new colleague: distinct purpose, when to use and when not, examples, errors that say what to change; make mistakes hard by shaping arguments | FR-066; removing three `ask_clarification` types is the "make mistakes hard" move |
| Evals: a task has inputs and success criteria; grade the outcome, not the path; isolate every trial from a clean environment; start with 20 to 50 tasks from real failures; report pass@k and pass^k (all k trials succeed) for reliability; read the transcripts | FR-070 to FR-079 |

One source lets its agent offer a numbered list of options when it stops on unexpected changes. Slice 0 keeps that only for the blocked case (FR-055 states what is needed), never mid-task (FR-056). No source covered mocked-model evals; ours separate the two on purpose: mocked tasks test the harness deterministically in CI, real-model tasks measure behaviour locally.

## R11. The current lead prompt, audited against R10

`SYSTEM_PROMPT_TEMPLATE` (`agents/lead_agent/prompt.py`) and the tool texts, as of main `6c1029a`:

- Clarify-first is the dominant instruction: `<thinking_style>`'s "PRIORITY CHECK … you MUST ask for clarification FIRST", the whole `<clarification_system>` (five mandatory scenarios, including approach choices and suggestions), and the first critical reminder. Nothing in the prompt says "read before asking". The R13 baseline shows the effect: 9 of 18 tasks ended in `ask_clarification`, including all three private-data reads.
- There is no instruction to verify before reporting, no stop rule and no retry rule. The tool-error text says "Continue with available context, or choose an alternative tool"; the loop warning says "produce your final answer now".
- `write_todos` exists only when `is_plan_mode` is set (the pro and ultra modes); even then the baseline never called it (0 of 15 pro-mode runs).
- The subagent section is about parallel decomposition only ("Only use `task` when you can launch 2+ subagents"), offered only in ultra mode, and every `task` call is Tier 3 (a card), so delegation is rare and costly (T08: no delegation).
- The citation and subagent examples name real companies (D11).
- `PreviewVerificationMiddleware` is the one existing deterministic "check before you finish" gate (web apps only); FR-052 generalises its pattern.

## R12. Eval design choices

- **Checks are code, not a judge.** Every pass condition reads the final state and the run trace (FR-074). A judge score may be printed for reading, never counted: judge drift would make "regression blocks merge" (D10) unenforceable.
- **Fixture stubs under real tool names.** Mail and calendar stubs are registered with the real tool names, so `default_rules.yaml`, the private-read walk (#139/#141) and the card flow treat them exactly as the real tools. A stub under a new name would test a different policy.
- **Isolation per trial**, as the baseline runner did by hand: temp data dir, temp `HOME` (run-history keys, watcher and CLI folders empty), config from a template with channels and connectors off, a throwaway owner account. This is also what makes it safe to confirm Tier 3 cards automatically inside the eval.
- **pass^k for the C tasks.** A personal assistant is judged by whether it works every time; pass@k would hide flakiness.
- **Mock mode tests the harness**, not the model: scripted turns, and a task fails if the conversation diverges from the script. That is what lets CI run with no network and no secrets.

## R13. Baseline, 2026-10-24 (current agent, real model, one run)

Main `6c1029a`, the configured default model, "pro" mode except T08 (ultra). Read-only tasks (T01 to T07) ran on the live dev stack as the owner; every task that writes, or that needs a card confirmed, ran on a throwaway isolated gateway (temp data dir and `HOME`, channels and connectors off, local sandbox, throwaway account). No real Tier 3 card was confirmed. The checks were applied by a throwaway runner, so they approximate FR-074. "Core" = the task's outcome checks; "strict" adds the Slice 0 behaviour checks (`checklist_before_action`, `verified_section`).

| Task | Where | Core | Why |
|---|---|---|---|
| T01 Philly 5 with links | live | pass | 8 links, 8 hosts, no card, no question (strict fail: no checklist) |
| T02 React features, 3 sources | live | fail | 5 searches, then `ask_clarification`; no answer |
| T03 calendar this week | live | fail | asked to "authorize" access, with an option menu; no calendar read |
| T04 calendar + mail + tasks | live | fail | same: one multi-part permission question, no reads |
| T05 emails needing a reply | live | fail | same |
| T06 Saturday plan with links | live | pass | 18 links, no menu |
| T07 12 restaurants, 4 areas | live | pass | 12 links, 19 searches, no card (#141 held) |
| T08 parallel research | isolated | fail | no delegation; fetches failed; ended in a question |
| T09 mark done + note | isolated | fail | the routine update raised a card (expected Tier 2); reply asked to confirm |
| T10 add 3 tasks | isolated | fail | same: a card for three new tasks; reply ends with a menu |
| T11 Tier 3 project, then tasks | isolated | fail | card raised and confirmed, but the confirmed call failed (`RuntimeError`); no resume |
| T12 ledger read, then web | isolated | fail | card, Apply all, resume worked and gave 3 links, but a mid-task question and a new card were left open |
| T13 retry after a wrong URL | isolated | fail | the fetch tool returned a provider billing error; the agent asked instead of retrying or searching |
| T14 post to team chat (absent) | isolated | fail | an option menu instead of a stated blocker |
| T15 checklist file, shown | isolated | pass | file in outputs, presented (strict fail: no "checked" line) |
| T16 Vite app | isolated | fail | asked "static build or dev server?"; no build (no container sandbox there) |
| T17 weekday 9am brief | isolated | fail | asked a multi-part question; no automation tool exists |
| T18 how are my projects | isolated | pass | read the ledger, named both projects, no question |

**Score: 5 / 18 core, 3 / 18 strict.** Estimated model cost of the lead's own calls: about $0.76 for all 18 (list prices, excluding title, memory and summarisation calls); wall time 8 s to 240 s per task.

Environment findings that affect scores (not agent behaviour): the web-fetch provider returned an account-balance error on the live stack and in the isolated run (T01, T08, T12, T13); routine ledger updates raised cards in the isolated instance (T09, T10), which needs a check against `ledger_changes_reversible`; the confirmed ledger call in T11 failed with an unlogged `RuntimeError`.

## R14. The coding-session watcher reference (AgentTrail) and Slice 0

The owner's 2026-10-19 brief named an MIT open-source project, AgentTrail, as the reference for **coding-session evidence**: watching external terminal coding agents' session logs. It is not a per-run trace of this assistant's lead. Ported already (see `THIRD-PARTY-NOTICES.md`): the second agent's session discovery, turn state and subagent linking; native todo lists applied only after a confirmed tool result. Not yet built: opt-in hooks that make "waiting on you" observed rather than inferred, and "declared vs observed" (a ledger task marked done while files in its declared scope keep changing; the `declared_files` column exists but nothing fills or reads it). Slice 0's per-run trace (FR-080) is the lead-side counterpart and uses the same rule: a status comes from an event, never from prose.
