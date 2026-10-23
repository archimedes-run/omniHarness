# Research: Orchestration (009)

Sources are read on GitHub only (no packages downloaded). Each finding names its source. Claims marked **verify** are not yet seen working and must pass a probe with a positive control before the plan depends on them (Article XII).

## R1. OpenCode: what it is and its licence

- Repository: `github.com/anomalyco/opencode` (the former `sst/opencode` URL redirects there). "The open source coding agent."
- Licence: **MIT**, "Copyright (c) 2025 opencode" (`LICENSE`). Bundling it in our sandbox image is permitted with the notice kept; we add it to the image's notices.
- Decision: OpenCode is the coding worker. Rationale: it has a headless server with an OpenAPI spec and an SDK (R2), a provider abstraction that accepts any OpenAI-compatible endpoint (R3), AGENTS.md rules (R4), fine-grained permissions (R5) and managed config (R6), which together let it run with no secret inside the sandbox.
- Alternatives considered: Claude Code and Codex CLIs (strong, but tied to their vendors' auth; putting their credentials in a sandbox breaks FR-003); our own LangGraph subagent with `bash` (that is what failed three times on 2026-10-23; it has no coding-specific loop).

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

- A custom provider: `provider.<id>.npm = "@ai-sdk/openai-compatible"` for `/v1/chat/completions` endpoints (`@ai-sdk/openai` for `/v1/responses`), `options.baseURL`, `options.apiKey` (supports `{env:NAME}`), `options.headers` per provider, and `models` with `limit.context` / `limit.output`.
- Decision: one provider `omni` with `baseURL` = the gateway LLM proxy on the sandbox network and `apiKey` = `{env:OMNI_LLM_TOKEN}`, a per-sandbox token (HMAC of the gateway secret and the container name, domain `sandbox-llm|`). The token authorises nothing but model calls for that sandbox, within its budget. It is not a provider key (FR-003).
- The gateway is on the sandbox network already; its Host guard (`DEFAULT_ALLOWED_HOSTS` in `app/gateway/config.py`) gets a narrow exception for the proxy route by sandbox-network source, or the proxy is a separate listener. Open question Q3.

## R4. Rules files (`rules.mdx`)

- OpenCode searches upward from the working directory for `AGENTS.md`, then `CLAUDE.md`; then the global `~/.config/opencode/AGENTS.md`; plus files listed in `instructions` in config, combined with the above. First match wins within each category.
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
