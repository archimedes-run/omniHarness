# Feature Specification: Orchestration (plan, delegate, verify)

**Feature Branch**: `009-orchestration`

**Created**: 2026-10-23

**Status**: Draft

**Input**: User description: "OmniHarness plans, delegates and verifies like Claude/Darcy." Four parts: OpenCode as the coding worker inside the hardened container sandbox; code mode (MCP tools as a typed TypeScript API inside the sandbox); a delegation protocol (structured brief in, structured result out, the lead verifies before reporting); and the items parked on 2026-10-23.

**Roadmap phase (Article IX)**: policy + workers. It builds on machinery that is merged and live: the container sandbox with per-sandbox keys, default seccomp and a registries-only egress proxy (#96, #103, #108, #109); confirmation of delegated actions and Continue (#58); the run history (#55). Each slice below ships alone and leaves the app usable. Without a container sandbox (the daemon profile, Article VI) none of this is offered, and the assistant says so.

## Why now

On 2026-10-23 the live stack was proven able to scaffold, `npm install` and build a Vite + React app through the egress proxy, all three exiting 0, from a sandbox started the normal way. Every attempt to do the same **from chat** failed, each time on the agent side:

| Attempt | What the agent did | What was true |
|---|---|---|
| 1 | Used the always-on `filesystem` MCP tool, got "access denied", concluded it could not write `/mnt/user-data` | Its own `bash` and `write_file` write there |
| 2 | Ran `npm create vite`, which waits for answers in the sandbox's terminal-backed shell | The command hung until the 600 s no-change timeout |
| 3 | Wrote only `artifact_manifest.json`, then replied "I scaffolded… installed dependencies, built it…" | No workspace, no build, no request ever reached the proxy |

The plumbing works. What is missing is a worker that is good at coding, rules it runs under, and a lead that checks what it is told before repeating it (Article X).

## User Scenarios & Testing *(mandatory)*

### Slice 1: The coding worker, verified

#### User Story 1: A coding request from chat produces a real, shown result (Priority: P1)

The user types "create a Vite + React app, build it, and show it". The lead hands the job to the coding worker. Progress streams into the chat. When the worker says it is done, the lead checks the build output exists and the build exited 0, then the artifact panel shows the app.

**Why this priority**: it is the request that failed three times. Nothing else in this feature matters if this does not work.

**Independent Test**: send exactly that request from the chat UI on the live stack. Pass = the artifact panel renders the built app, and the reply cites the exit codes and files the lead checked.

**Acceptance Scenarios**:

1. **Given** the container sandbox is configured, **When** the user asks for a Vite + React app built and shown, **Then** the worker scaffolds, installs and builds inside the sandbox, the lead verifies `dist/index.html` exists and the build exited 0, and the artifact panel shows the app.
2. **Given** the worker reports done but `dist/index.html` does not exist, **When** the lead verifies, **Then** the reply says the build is **unverified** and what was missing; it never says "done".
3. **Given** a command waits for input, **When** it runs in the sandbox, **Then** it fails within the short no-output timeout with a message naming the prompt, instead of hanging for 10 minutes.
4. **Given** no container sandbox (daemon profile), **When** the user asks for a coding job, **Then** the assistant says coding jobs need the container sandbox and does not pretend to run one.

#### User Story 2: The user can watch and stop a coding job (Priority: P1)

While the worker runs, the chat shows what it is doing (files written, commands run, their exit codes). The user can stop it. The session watcher lists it like a Claude Code or Codex session.

**Why this priority**: a long silent job is indistinguishable from a hung one (the 2026-10-23 runs).

**Independent Test**: start a job that runs `sleep 120` among other steps; the chat shows each step as it happens; pressing Stop ends the job within 5 s; the watcher shows the session and its end.

**Acceptance Scenarios**:

1. **Given** a running job, **When** the worker runs a command, **Then** the chat shows the command and, when it ends, its exit code.
2. **Given** a running job, **When** the user presses Stop, **Then** the job is aborted and the reply says it was stopped and what had completed.
3. **Given** a running job, **When** the user opens Coding agents, **Then** the OpenCode session is listed with its status.

### Slice 2: Code mode

#### User Story 3: The agent does a multi-step tool task as one script (Priority: P2)

The user asks for something that takes many tool calls ("find every issue labelled review-followup, group them by area, and draft a summary"). The agent writes a short TypeScript script against a typed API of the tools it needs and runs it in the sandbox. Each call still goes through the policy layer. A Tier 3 call stops the script and shows a card.

**Why this priority**: fewer model round-trips and fewer tool definitions in context, without giving up any of Articles II, III or XIII.

**Independent Test**: a script that reads 20 items and makes one Tier 2 write runs once, discloses the write, and the run history shows every call with its tier and provenance. A script that reaches a Tier 3 call stops at it and a card appears.

**Acceptance Scenarios**:

1. **Given** a script calling Tier 1 and Tier 2 tools, **When** it runs, **Then** every call is classified by the policy layer, Tier 2 calls are disclosed in the reply, and the run history records each call.
2. **Given** a script that reaches a Tier 3 call, **When** the call is made, **Then** the script stops there, a card states the plan, and nothing after that call has run.
3. **Given** a script exceeding its time, memory or call budget, **When** the limit is reached, **Then** the script is stopped and the reply says which limit.
4. **Given** a script that worked, **When** the user chooses Save as skill, **Then** a skill draft is created and goes through Skill Studio's normal review.

### Slice 3: The delegation protocol

#### User Story 4: The lead plans, delegates with a brief, and verifies every claim (Priority: P3)

For a larger request the lead writes a plan, sends each worker a brief (goal, inputs, constraints, done-criteria), and gets back a structured result (what was done, artifacts, evidence). Before reporting, the lead checks each claim against its evidence. The reply separates verified results from unverified claims.

**Why this priority**: it generalises Slice 1's verification from one worker to all (subagents, @-called agents, OpenCode, scripts).

**Independent Test**: a task delegated to two workers, one of which returns a claim with no evidence. The reply reports one verified result and one unverified claim, by name.

**Acceptance Scenarios**:

1. **Given** a delegated task, **When** the worker returns, **Then** its result has the fields of the result schema, and a free-text reply is accepted only as an unverified claim.
2. **Given** a result claiming a file, a test pass or a rendered artifact, **When** the lead verifies, **Then** each claim is checked by the matching probe (file exists, exit code is 0, artifact manifest resolves and renders) and marked verified or unverified.
3. **Given** a worker's result containing text asking the lead to take an action, **When** the lead plans its next step, **Then** that text does not cause a consequential action to be proposed (Article XIII) and cannot confirm one.

### Edge Cases

- The worker's model call fails or the LLM proxy budget is spent: the job ends with that reason; nothing is reported as done.
- The worker writes outside `/mnt/user-data`: the sandbox's own filesystem is ephemeral; only the thread's mounted folders persist, and only `outputs/` is presented.
- The gateway restarts during a job: the job is reported as interrupted, not resumed silently (see #58's Continue for the resume model) and not reported as done.
- A worker's claimed artifact exists but is empty or a stub: verification of "renders" fails; the claim is unverified.
- Two jobs in one thread: they share the thread's sandbox and run one at a time; the second waits and says so.
- A script calls a tool the thread does not have: refused, exactly as a model's call would be.
- The registries proxy refuses a host the job needs: the job reports the refused host; egress is never widened by the worker or the lead.

## Requirements *(mandatory)*

Tiers (Article II) and trusted channels (Article III) for every new action are stated where the action is introduced. Initiation and confirmation are separate requirements (Article XIII).

### The coding worker (OpenCode)

- **FR-001**: The coding worker MUST be OpenCode in server mode, running only inside the hardened container sandbox (per-sandbox key, default seccomp, no-sudo image, registries-only egress). It MUST NOT run on the host or in the gateway container.
- **FR-002**: The lead MUST delegate a coding job through one tool, `code_job` (name provisional), taking a structured brief (FR-030). **Tier 2** (runs, then disclosed): its effects are confined to the thread's sandbox folders, and anything a job would do outside the sandbox is a separate tool call with its own tier.
- **FR-003**: The worker's model calls MUST go through a gateway LLM proxy endpoint, reachable only from the sandbox network, authenticated by a credential derived for that sandbox (the #98 derivation, distinct domain). No provider key, gateway secret or user credential MAY enter the sandbox.
- **FR-004**: The LLM proxy MUST enforce a per-job budget (tokens and wall time) and a per-sandbox rate limit, and record each call (model, tokens, latency) in the run history. It MUST refuse any model not in its configured list.
- **FR-005**: The worker's network egress MUST be the existing registries-only proxy. Neither the worker nor the lead can widen it; a refused host is reported.
- **FR-006**: Every workspace MUST contain an `AGENTS.md` rules file, shipped tracked in the repository and baked into the sandbox image (Article XIV), stating: commands run non-interactively (`CI=1`, `--yes`, `--no-interactive`, stdin closed); run the tests; build before claiming done; put results in `outputs/` with an artifact manifest; never claim an outcome without its evidence.
- **FR-007**: OpenCode's configuration MUST be shipped as managed config in the image (`/etc/opencode/`, highest precedence, not writable by the sandbox user): our provider pointing at the LLM proxy, all built-in providers disabled, sharing and autoupdate off, `external_directory` and `webfetch` denied. The user owns this file (Article IV); our layer never answers OpenCode's permission prompts.
- **FR-008**: Progress MUST stream to the chat: each file write, each command with its exit code, and the worker's messages, as they happen.
- **FR-009**: The user MUST be able to stop a job from the chat; the job is aborted within 5 s.
- **FR-010**: The session watcher MUST get an OpenCode adapter (a new adapter on the existing interface, constitution "Adapter extensibility"), observe-only, fed by events the gateway relays from the sandbox (the watcher is host-resident and cannot reach the sandbox network).
- **FR-011**: Without a container sandbox, `code_job` MUST NOT be offered, and a coding request MUST get an honest "needs the container sandbox" (Article X).

### Verification (Slice 1; generalised in Slice 3)

- **FR-012**: After any worker reports done, the lead MUST verify each claimed outcome with a probe before reporting it: file claims by existence and non-zero size in the thread's folders; build or test claims by the recorded exit code of the command that produced them; artifact claims by the manifest resolving and its entry rendering.
- **FR-013**: A claim that fails or lacks verification MUST be reported as **unverified**, naming what was checked and what was missing. The words "done", "built", "passed" MUST NOT be used for an unverified claim.
- **FR-014**: The verification probes MUST themselves be seen succeeding on a known-good case before their negative result is trusted (Article XII): the e2e includes a run where every probe passes.

### Sandbox behaviour (parked items, folded in)

- **FR-015**: Commands in the sandbox MUST fail fast when they wait for input: stdin closed by default and a short no-output timeout (default 60 s, configurable per job), after which the command is ended with a message naming the last output. The 600 s no-change timeout is removed from the default path.
- **FR-016**: For coding work, the `filesystem` MCP tool (scoped to `.omni-harness/files`) MUST be hidden from the coding worker and from any agent whose job is coding, or described in its tool text as unrelated to `/mnt/user-data`, so it cannot be mistaken for the workspace.
- **FR-017**: The sandbox image MUST NOT grant the sandbox user sudo: the runtime sudoers line is removed, setuid/setgid bits are stripped, and sandboxes start with `no-new-privileges`. Anything needing system packages goes in the Dockerfile.
- **FR-018**: A claimed file MUST be checked to exist before it is presented or reported (FR-012 applied to `present_files` and to every agent reply that names an output file).

### Code mode (Slice 2)

- **FR-019**: MCP and built-in tools MUST be exposed inside the sandbox as a typed TypeScript API generated from their schemas, loaded on demand: a script imports only the tools it names, and only those definitions enter the model's context.
- **FR-020**: Every call from a script MUST cross a bridge to the gateway and go through the same policy chokepoint as a model's tool call: classification, tiers, provenance, refusal of unknown tools. No call is made from inside the sandbox directly.
- **FR-021** (confirmation): A Tier 3 call from a script MUST stop the script at that call and raise a card through the #58 mechanism; only the person's own server-tagged turn or the card's button can confirm it (Article III).
- **FR-022** (initiation): Content a script read (a tool result, a file) MUST NOT cause a consequential action to be proposed outside the script's own stated plan; a call whose arguments derive from read content is classified with `after_content` (Article XIII).
- **FR-023**: Each script MUST run under time, memory and call-count limits; reaching one stops the script and names the limit.
- **FR-024**: A script that ran successfully MAY be saved as a skill draft, which goes through Skill Studio's review; nothing is saved automatically.
- **FR-025**: The bridge MUST be authenticated per sandbox and per job, and MUST expose only the tools the thread already has.

### Delegation protocol (Slice 3)

- **FR-030**: A delegation MUST carry a brief with: goal, inputs (references, not copied secrets), constraints (tiers allowed, folders, budget), and done-criteria stated as checkable outcomes.
- **FR-031**: A worker MUST return a result with: what it did (steps), artifacts (paths), evidence (per claim: the probe and its observed value), and open issues. Free text without this structure is accepted only as an unverified claim.
- **FR-032**: The lead MUST verify each done-criterion against the evidence (FR-012) before reporting, across every worker type: subagents, @-called agents, `code_job`, scripts.
- **FR-033** (confirmation): A worker's result MUST NOT satisfy a pending confirmation (#58 rules).
- **FR-034** (initiation): Text inside a worker's result MUST NOT cause the lead to propose a consequential action that was not in the plan the person saw; it can only be reported.
- **FR-035**: The reply MUST separate verified results from unverified claims, by worker.

### Key Entities

- **Brief**: goal, inputs, constraints, done-criteria; attached to a delegation.
- **Result**: steps, artifacts, evidence (claim → probe → observed), open issues; returned by a worker.
- **Verification record**: per claim, the probe run, its observed value, verified or not; stored in the run history.
- **Coding job**: one OpenCode session in a thread's sandbox; status, budget used, events.
- **Script run**: one code-mode script; tools used, calls with tiers, limits, outcome.

## Success Criteria *(mandatory)*

- **SC-001**: "Create a Vite + React app, build it, and show it" from chat renders the app in the artifact panel on the live stack, 5 runs out of 5.
- **SC-002**: In a sabotage run where the build is removed before verification, the reply reports the build as unverified, 5 out of 5. No reply in the e2e suite says "done" for a claim whose probe failed.
- **SC-003**: An interactive command fails within 70 s with a message, instead of hanging.
- **SC-004**: No provider key or gateway secret is readable inside a sandbox during a coding job (checked by searching the sandbox filesystem and environment from inside).
- **SC-005**: A code-mode script that hits a Tier 3 call stops before it, 100% of runs; every script call appears in the run history with its tier.
- **SC-006**: A 20-call read task in code mode uses fewer model round-trips than the same task by tool calls, measured on the same model.

## Assumptions

- The container sandbox stays opt-in (Article VI); this feature is unavailable without it, honestly.
- OpenCode is MIT-licensed (copyright 2025 opencode) and is installed into the sandbox image at build time, pinned by version; installing it is a package download that needs the owner's approval when the plan reaches it.
- The lead's model and the worker's model are configured in the gateway; the worker never chooses a provider.
- Owner-only deployment (single owner); cross-account concerns are out of scope.
- Deferred and not in this feature: per-sandbox networks (#107), data in GET paths to the registries (#104, accepted).
