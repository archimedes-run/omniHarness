# Feature Specification: Orchestration (plan, delegate, verify)

**Feature Branch**: `009-orchestration`

**Created**: 2026-10-23

**Status**: Draft (owner decisions of 2026-10-23 recorded in "Decisions"; Slice 0 added 2026-10-24)

**Input**: User description: "OmniHarness plans, delegates and verifies like the best terminal coding agents and research agents do." Four parts: OpenCode as the coding worker inside the hardened container sandbox; code mode (MCP tools as a typed TypeScript API inside the sandbox); a delegation protocol (structured brief in, structured result out, the lead verifies before reporting); and the items parked on 2026-10-23. Added 2026-10-24: **Slice 0, agent behaviour**: the lead's own working loop (plan, done-criteria, verify, retry, stop honestly, resume), a rewrite of its system prompt and tool descriptions, an eval suite that scores it (`make eval`), and a per-run trace record that the eval, the steps section (D8) and 007 Harness² all read.

**Roadmap phase (Article IX)**: policy + workers. It builds on machinery that is merged and live: the container sandbox with per-sandbox keys, default seccomp and a registries-only egress proxy (#96, #103, #108, #109); confirmation of delegated actions and Continue (#58); the run history (#55). Each slice below ships alone and leaves the app usable. Without a container sandbox (the daemon profile, Article VI) none of this is offered, and the assistant says so.

## Why now

On 2026-10-23 the live stack was proven able to scaffold, `npm install` and build a Vite + React app through the egress proxy, all three exiting 0, from a sandbox started the normal way. Every attempt to do the same **from chat** failed, each time on the agent side:

| Attempt | What the agent did | What was true |
|---|---|---|
| 1 | Used the always-on `filesystem` MCP tool, got "access denied", concluded it could not write `/mnt/user-data` | Its own `bash` and `write_file` write there |
| 2 | Ran `npm create vite`, which waits for answers in the sandbox's terminal-backed shell | The command hung until the 600 s no-change timeout |
| 3 | Wrote only `artifact_manifest.json`, then replied "I scaffolded… installed dependencies, built it…" | No workspace, no build, no request ever reached the proxy |

The plumbing works. What is missing is a worker that is good at coding, rules it runs under, and a lead that checks what it is told before repeating it (Article X).

Attempt 3 is not only a coding problem. The same lead, on ordinary requests, asks before reading, offers a menu of options in the middle of a task, stops after one failed call, and (until #139) did not pick a task back up after a confirmation. Its system prompt tells it to do most of this: "you MUST ask for clarification FIRST - do NOT proceed with work", and ask "BEFORE starting work" whenever "Several valid approaches exist". A coding worker under that lead would inherit all of it. So the lead's own loop comes first (Slice 0), and it gets a score (the eval suite) before anything else changes it.

## Decisions (owner, 2026-10-23)

| # | Question | Decision |
|---|---|---|
| D1 | Install OpenCode in the sandbox image? | Yes: a pinned release, checksum verified at build; sharing and telemetry off in the baked config. |
| D2 | Worker model and budget | The worker uses the same model as the lead, configurable per agent. Default budget **$1 per job**; the cost is shown at the end of the job and counted against a **monthly cap** set in Settings. |
| D3 | LLM proxy placement | A **separate listener on the sandbox network only** (not an exception in the gateway's Host guard). |
| D4 | No-output timeout | **120 s** default; **300 s** for known installs and builds (npm/pnpm/yarn install, pip install, build commands); **600 s hard cap** per command; configurable per job. |
| D5 | Code mode after a Tier 3 call | **No re-run.** The Tier 3 call ends the script and raises the card. After confirmation only that call runs (#58), and its result returns to the agent, which writes a continuation script. Tier 2 writes earlier in the script happen exactly once. |
| D6 | Watcher and OpenCode permissions | Observe-only. OpenCode is configured so it never prompts (everything inside the sandbox is allowed); if a prompt appears anyway the job fails with a clear reason. |
| D7 | Order of work | (a) #58 fresh review + stop report; (b) #53's three HIGH findings: closed by #89/baseline → rebase + stop report with Studio screenshots, else report and defer; (c) this feature's Slice 1; (d) #53 if deferred; (e) Slices 2 and 3. **Superseded for the slices by D9** ((a), (b) and (d) are done or tracked elsewhere). |
| D8 | Visibility in the UI | The agent's thinking and every step (each tool call, each skill load, each delegated job and its steps) are visible in a small collapsible section while the work runs; when the work is done the whole procedure collapses, leaving only the output. |

### Decisions (owner, 2026-10-24)

| # | Question | Decision |
|---|---|---|
| D9 | Order of work | **Slice 0 (agent behaviour) → Slice 1 (OpenCode worker) → 007 Harness² (uses Slice 0's eval suite and the run store) → Slices 2 and 3.** Slice 1's gate stays "build a Vite + React app from chat and show it", 5 out of 5. |
| D10 | How the lead is judged | By an eval suite of 15 to 20 tasks taken from the owner's own use, each with an automatic pass check. `make eval` runs it against a scripted (mocked) model in CI and against the real model locally, and reports a score. A prompt or tool-description change that lowers the real-model score does not merge. |
| D11 | Proprietary names | Specs, prompts and tool descriptions name no commercial agent, assistant or vendor product. Open-source projects (OpenCode) may be named. |

## User Scenarios & Testing *(mandatory)*

### Slice 0: Agent behaviour

Slice 0 changes how the lead works, not what it can reach. No new tool, tier or channel is introduced except where a requirement says so (FR-058 widens #139's resume; FR-061 proposes one read-only research subagent type). Every story here is measured by an eval task (FR-070 to FR-079), and the task ids are given with each story.

#### User Story 0.1: The lead plans, says what "done" means, and checks it before reporting (Priority: P1)

The user asks for something with several steps ("find 5 date-night restaurants in Philly with links", "add three tasks to my garden project", "write me a moving checklist and show it"). Before its first action the lead writes a short visible checklist, and the first line states what done means in checkable terms ("5 restaurants, each with a link I opened or that came from a search result"; "3 new tasks exist in Eval Garden"; "the file exists in outputs and is presented"). It works the list, ticking items as they finish. Before replying it checks every criterion against what its tools returned in this run, and the reply says what was checked. A criterion it could not check is reported as unverified, never as done.

**Why this priority**: the false "I built it" of 2026-10-23 and the unshown files are the same failure: no stated target and no check. Everything else in Slice 0 hangs off the checklist.

**Independent Test**: eval tasks T01, T09, T10, T15. Pass = each task's automatic check (FR-074) and, from the run trace, a checklist step before the first non-read tool call and a verification step before the final message.

**Acceptance Scenarios**:

1. **Given** a request that needs 3 or more steps, **When** the lead starts, **Then** its first tool call is the checklist (`write_todos`), with a "Done when" item stating checkable criteria, in every chat mode (not only the plan modes, see FR-050).
2. **Given** a one-step request ("what's 15% of 80"), **When** the lead answers, **Then** no checklist is written.
3. **Given** a checklist, **When** a step finishes, **Then** it is ticked in the same model turn; exactly one item is in progress at a time.
4. **Given** the lead is about to reply, **When** a done-criterion has no supporting tool result in this run, **Then** the reply lists it under "Not verified" with what is missing, and does not say done, built, sent, posted or passed for it (FR-013 applied to the lead's own work).

#### User Story 0.2: The lead recovers from an error instead of giving up or looping (Priority: P1)

A call fails: a 404 from a mistyped URL, a missing file, a tool refusing an argument. The lead reads the error, changes something (the argument, the tool, or the approach) and tries again. After three failed attempts at the same step it stops patching and takes a different route, or, if there is none, stops as blocked (US 0.3). It never repeats an identical failing call, and it never reports the step as done.

**Why this priority**: today's tool-error text tells the model to "Continue with available context", which in practice means a reply built on nothing; the loop detector's warning tells it to "produce your final answer now". Neither says "read the error and change something".

**Independent Test**: eval task T13 (a wrong PyPI JSON URL that must be corrected) and the mocked-model task M-RETRY (a scripted tool fails once with an actionable error). Pass = the final answer has the right value and the trace shows a failed call followed by a changed call that succeeded.

**Acceptance Scenarios**:

1. **Given** a tool returns an error, **When** the lead's next turn runs, **Then** its next call to that step differs from the failed one in tool or arguments.
2. **Given** three failed attempts at one step, **When** the lead continues, **Then** it either uses a different approach (recorded as a new checklist item) or stops as blocked.
3. **Given** a step that never succeeded, **When** the lead replies, **Then** that step is reported as not done, with the last error.

#### User Story 0.3: The lead stops only when done or truly blocked, and then says exactly why (Priority: P1)

When the lead cannot finish (an account that is not connected, a capability the setup lacks, a permission it does not have), it stops and says, in one short block: what is done, the exact blocker (the tool or account and the error), and what the person needs to do ("connect your team chat in Settings → Connections", "start the container sandbox profile"). It does not offer a menu of alternatives in the middle of a task, and it does not claim the thing happened.

**Why this priority**: "honest limits" (Article X) is already a rule; this makes it the lead's stopping rule.

**Independent Test**: eval tasks T14 (post to a team-chat channel with no team-chat connection), T16 without a container sandbox, T17 (an automation request with no automation tool). Pass = the reply names the blocker and what is needed, and contains no success claim.

**Acceptance Scenarios**:

1. **Given** a required account or tool is absent, **When** the lead stops, **Then** the reply names it, says what the person must do, and lists what was completed.
2. **Given** the lead is mid-task with a reasonable default available, **When** it would otherwise ask "would you like A, B or C?", **Then** it picks the default, says which assumption it made, and continues.
3. **Given** the task finished, **When** the lead replies, **Then** the reply does not end with an option menu or "would you like me to…"; at most one plain suggestion line is allowed after the result.

#### User Story 0.4: Reads never ask; asking is for what cannot be looked up (Priority: P1)

"How are my projects going?" reads the ledger and answers. "Summarise my calendar for this week" reads the calendar and answers. The lead asks a question only when information that blocks the task is missing and no read can find it, and then asks one question, before work starts. Risk is not the model's question to ask: consequential actions are stopped by the policy layer's cards (Article II), not by a model-written "are you sure?".

**Why this priority**: the current prompt makes asking the first step of every task ("CLARIFY → PLAN → ACT", "Approach Choices … REQUIRED ACTION: Call ask_clarification"). That is the opposite of how strong agents behave and the most common complaint in daily use.

**Independent Test**: eval tasks T03, T04, T05, T18. Pass = no `ask_clarification` in the run, and the read tools named by the check were called.

**Acceptance Scenarios**:

1. **Given** a request answerable by Tier 1 reads, **When** the lead runs, **Then** it reads and answers with no question.
2. **Given** a genuinely missing input ("book a table", no restaurant or date, nothing in memory or the calendar), **When** the lead starts, **Then** it asks one question before any write, and none after work has begun unless a new fact makes the task impossible.
3. **Given** a consequential action, **When** the lead plans it, **Then** it calls the tool and lets the policy layer raise the card; it does not ask a model-written confirmation question first.

#### User Story 0.5: After any confirmation, the original task continues (Priority: P1)

A task reaches a Tier 3 card (a new project, a delegated job, a deletion). The run stops at the card. When the person confirms (or declines) every card raised in that turn, the lead starts again on the same thread, from the server, with the results as tool results, and finishes the remaining steps of its checklist. A declined call is not retried; the lead finishes what it can without it and says what was not done.

**Why this priority**: #139 does this for the outbound group of web tools only. "Create the project and add two tasks" still stops after the project is created, and the two tasks never appear.

**Independent Test**: eval tasks T11 (new project = Tier 3 card, then two Tier 2 tasks after confirm) and T12 (a ledger read, then web searches raised as an outbound group, finished after Apply all). Pass = after the confirm, without any new message from the person, the project has both tasks (T11), and the final reply has 3 links (T12).

**Acceptance Scenarios**:

1. **Given** a turn whose Tier 3 cards are all resolved (confirmed, applied, declined, failed or expired), **When** the last one resolves, **Then** one resume run starts on that thread, with each card's call and outcome as tool results, and no resume starts while any card of the turn is open.
2. **Given** the resume run, **When** it starts, **Then** it sees the checklist and done-criteria of the interrupted turn (they are in thread state and in the summary record), and it continues from the first unticked item.
3. **Given** a declined card, **When** the lead resumes, **Then** it does not call the same tool with the same arguments again in that turn, and the reply names what was not done because of the decline.
4. **Given** the resume run, **When** it encounters a new Tier 3 call, **Then** that call raises its own card (no confirmation carries over), and the cycle repeats.
5. **Given** the resumed run, **When** anything in it is checked as the person's turn, **Then** it is not (`lineage.is_user_turn` unchanged): a resume can never answer a card (#58, #139).

#### User Story 0.6: Long tasks keep their plan through summarisation (Priority: P2)

A research task runs long enough that the context is summarised (around 15k tokens today). After the summary the lead still knows its checklist, its done-criteria, what it has already verified (with the URLs or ids that prove it), and any open blocker, and it carries on instead of starting over or stopping.

**Why this priority**: #141 made the summary carry the turn's private-read record so the policy verdict survives. The plan has to survive the same way.

**Independent Test**: eval task T07 (12 restaurants in 4 neighbourhoods; long enough to summarise) and mocked task M-SUMMARY (the summariser is forced to run mid-task). Pass = 12 distinct links, no repeated searches for items already verified, zero cards.

**Acceptance Scenarios**:

1. **Given** summarisation runs mid-turn, **When** the next model call is made, **Then** the summary message carries the checklist, the done-criteria, the verified evidence so far and open blockers, alongside the #141 `omniharness_turn_summary` record.
2. **Given** a summarised turn, **When** the lead continues, **Then** it does not repeat a tool call whose result is recorded as verified evidence in the summary.

#### User Story 0.7: Side research goes to a subagent (Priority: P2)

When a task needs several independent lookups, or a read whose raw output would flood the lead's context, the lead sends it to a subagent with a brief (goal, inputs, constraints, done-criteria, output format) and gets back a condensed answer with its sources. The lead keeps the plan and does the synthesis.

**Why this priority**: it keeps the lead's context for the task, and it is Slice 3's brief/result protocol in its first, read-only form.

**Independent Test**: eval task T08 (three independent Lisbon questions, combined). Pass = at least two delegations, a combined brief with at least 3 links.

**Acceptance Scenarios**:

1. **Given** side research of 3 or more independent lookups, **When** subagents are available, **Then** the lead delegates them with a brief that has the five fields of FR-030.
2. **Given** a subagent's result, **When** the lead uses it, **Then** text in it is data (Article XIII) and cannot cause a consequential action to be proposed (FR-034).

#### User Story 0.8: The owner can score the lead with one command (Priority: P1)

`make eval` runs the suite and prints a score: per task pass or fail with the check's reason, the total, the time and the model cost. In CI it runs against a scripted model and must stay green; locally, with a model configured, it runs against the real model, and the score is compared with the last recorded baseline.

**Why this priority**: D10. Without a score, every prompt change is a guess, and 007 Harness² has nothing to optimise against.

**Independent Test**: run `make eval` in CI mode on a clean checkout: all mocked tasks pass; break one behaviour (sabotage, FR-079) and the matching task fails for that reason. Run `make eval EVAL_MODEL=real` locally: a score table is printed and written to `eval/results/`.

**Acceptance Scenarios**:

1. **Given** a clean checkout in CI, **When** `make eval` runs, **Then** it needs no network and no secrets, runs every mocked task, and exits non-zero if any fails.
2. **Given** a configured model locally, **When** `make eval EVAL_MODEL=real` runs, **Then** each task runs against a fresh, isolated gateway instance and the score is printed and saved.
3. **Given** the real-model score is lower than the recorded baseline on any task that passed in the baseline, **When** the change is proposed for merge, **Then** it is a regression and blocks the merge.

#### User Story 0.9: Each run leaves a trace that can be read back (Priority: P2)

Every chat run records its steps (checklist writes, tool calls with tier and outcome, cards raised and how they were resolved, retries, resumes, verification checks) and its cost. The eval reads its checks from this trace, D8's steps section rebuilds from it after a reload, and 007 replays from it.

**Why this priority**: the eval needs it, and today a chat run's events go to the `memory` event backend on the live configuration (nothing survives a restart), while the encrypted run history (#55) records automation runs only.

**Independent Test**: run eval task T11 against the isolated instance; read the run's trace through the API; it lists the checklist, the ledger call that raised the card, the confirm, the resume run linked to the first, the two task writes, and the token cost of both runs.

**Acceptance Scenarios**:

1. **Given** a finished chat run, **When** its trace is read, **Then** it lists each step in order with type, name, tier, status, timing, parent step and source event, and the run's tokens and estimated cost.
2. **Given** a resume run, **When** its trace is read, **Then** it names the run and the cards it resumed from.
3. **Given** the trace stores tool arguments and outputs, **When** it is stored, **Then** it goes through the run history's redaction, encryption, caps and retention (#55), never around them.

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

While the worker runs, the chat shows what it is doing (files written, commands run, their exit codes). The user can stop it. The session watcher lists it like the other terminal coding-agent sessions it already watches.

**Why this priority**: a long silent job is indistinguishable from a hung one (the 2026-10-23 runs).

**Independent Test**: start a job that runs `sleep 120` among other steps; the chat shows each step as it happens; pressing Stop ends the job within 5 s; the watcher shows the session and its end.

**Acceptance Scenarios**:

1. **Given** a running job, **When** the worker runs a command, **Then** the chat shows the command and, when it ends, its exit code.
2. **Given** a running job, **When** the user presses Stop, **Then** the job is aborted and the reply says it was stopped and what had completed.
3. **Given** a running job, **When** the user opens Coding agents, **Then** the OpenCode session is listed with its status.

#### User Story 5: The user sees every step while it runs, and only the output when it is done (Priority: P1)

While the agent works, a small collapsible section under its reply shows its thinking and each step as it happens: every tool call (name, short arguments, tier, outcome), every skill load, every delegated job with its own steps (the coding worker's file writes and commands with exit codes), and the verification checks. When the work ends, the section collapses on its own and the reply shows only the output (and, for coding jobs, the verified and unverified results). The user can expand it again at any time.

**Why this priority**: the 2026-10-23 runs were opaque: a hung command, a wrong tool and a false claim all looked the same from the chat. Seeing the steps is how the user (and the lead) catches them.

**Independent Test**: run the Vite request; while it runs the section is open and lists, in order, the skill load, the `code_job` call, the worker's commands with exit codes, and the verification checks; when it ends the section is collapsed and the reply shows the artifact and the verified results; expanding it shows the same steps. Repeat in both themes.

**Acceptance Scenarios**:

1. **Given** the agent is working, **When** it calls a tool or loads a skill, **Then** a step appears in the section within 1 s, with its name and status (running, done, failed, stopped, needs confirmation).
2. **Given** a delegated job, **When** its worker runs a command, **Then** the step appears nested under the job, with the command and, when it ends, its exit code from the event stream.
3. **Given** the work has finished (done, failed or stopped), **When** the final reply arrives, **Then** the section collapses and only the output is shown; the section header states the step count and the time taken.
4. **Given** a collapsed section, **When** the user expands it, **Then** every step is there, including the thinking, in order.
5. **Given** a step that needs confirmation, **When** it is reached, **Then** the section stays open at that step and the card is shown; it collapses only when the work ends.
6. **Given** a reload or another device, **When** the thread is opened, **Then** the same steps are shown (from the run history), collapsed for finished work.

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

### Slice 0: the lead's working loop

Prompt text is guidance, so each rule below names what enforces or measures it: a middleware (deterministic), the eval suite (measured), or both. A rule enforced only by prompt text is never trusted without its eval task.

- **FR-050** (plan): For a request needing 3 or more steps, the lead MUST write a visible checklist with `write_todos` before its first non-read tool call, and keep exactly one item in progress. `write_todos` MUST be available in every chat mode and in scheduled runs, not only when `is_plan_mode` is set (today it is bound only in the two plan modes). Tier 1, `reads_private: false` (unchanged rule). *Measured*: T01, T09, T10, T15; *enforced*: none (a missing checklist is not blocked, it is scored).
- **FR-051** (done-criteria): The checklist's first item MUST be "Done when: …", stating outcomes a tool result can confirm (a count of links, a ledger row, a file in `outputs/`, an exit code, an artifact that renders). The run trace records it as the run's done-criteria.
- **FR-052** (verify): Before the final reply, the lead MUST check each done-criterion against tool results from this run (or, after a resume, the resumed turn). The reply MUST end its result with a short "Checked" line naming the evidence, and a "Not verified" list for anything without evidence. *Enforced*: a `VerificationReminderMiddleware`, generalising `PreviewVerificationMiddleware`, sends the lead back once (capped, like the preview reminder's 3) when it tries to finish with unticked checklist items and no "Not verified" entry for them.
- **FR-053** (no claim without evidence): FR-013 applies to the lead's own work: done, built, sent, posted, created, passed MUST NOT be said of a criterion without evidence. *Measured*: a transcript linter in the eval (FR-076) over every final reply.
- **FR-054** (retry): After a tool error the lead MUST read it and change the tool, the arguments or the approach before calling again; it MUST NOT repeat an identical failing call. After 3 failed attempts at one checklist item it MUST switch approach (as a new item) or stop as blocked (FR-055). *Enforced*: the tool-error text (FR-066) and the loop detector's warning text are rewritten to say this; the loop detector's thresholds (warn at 3, stop at 5 identical calls) are unchanged.
- **FR-055** (stop rule): The lead MUST end a turn only when (a) every done-criterion is verified, (b) it is blocked, or (c) a Tier 3 card is pending (the turn resumes per FR-058). A blocked reply MUST state what was completed, the exact blocker (tool or account, and the error), and what the person needs to do. It MUST NOT claim the blocked outcome.
- **FR-056** (no menus): The lead MUST NOT offer a menu of options in the middle of a task. Where a reasonable default exists it picks it and states the assumption in one line. A final reply MAY end with one plain suggestion; it MUST NOT end with a list of choices. *Measured*: the menu linter (FR-076).
- **FR-057** (reads never ask): The lead MUST NOT ask before a Tier 1 read. `ask_clarification` is for missing information that blocks the task and that no read can supply, asked once, before work starts. The `approach_choice`, `suggestion` and `risk_confirmation` clarification types MUST be removed from the tool (risk is decided by the policy layer's tiers and cards, Article II, not by a model's question). *Enforced*: the tool schema; *measured*: T03, T04, T05, T18 (no `ask_clarification` in the trace).
- **FR-058** (resume after any confirm): #139's resume MUST be widened from a turn's outbound group to **every** Tier 3 card raised by the lead in a chat turn: when the last open card of the turn is resolved (confirmed, applied, declined, failed or expired), one resume run starts on that thread from the server, with each card's call and outcome as tool results. It reuses #139's machinery unchanged in kind: one-shot locks taken up front and spent only when the run succeeds, a server-owned `resume_action` record, the private-read state recorded with each card, and results entering as tool results so `lineage.is_user_turn` stays false (Article III: a resume can never answer a card). *What #139 already does*: outbound groups (web_search, web_fetch, image_search after a private read). *What remains*: single Tier 3 cards from the lead (ledger new project/goal/link, `task`, `filesystem_delete*`, `skill_manage`, `setup_agent`, `update_agent`, connector writes), mixed turns with outbound and non-outbound cards, declined and expired cards (today a decline ends the task silently), and delegate cards, which keep "Continue <agent>" (#58) for the delegate and additionally resume the lead once the delegate's Continue finishes. Tier: unchanged; no confirmation carries over to a call made in the resume run.
- **FR-058a** (decline): In a resume after a decline, the declined call MUST NOT be made again in that turn (the policy middleware refuses an identical call, keyed by tool and arguments hash, for the rest of the turn), and the reply MUST name what was not done because of it.
- **FR-059** (summarisation): When summarisation runs mid-turn, the summary message MUST carry, next to #141's `omniharness_turn_summary`, a server-set plan record: the checklist with statuses, the done-criteria, the verified evidence so far (tool, id or URL), and open blockers. The checklist itself MUST also stay in thread state (`todos`), which summarisation never removes. After a summary the next model call MUST be shown the checklist again (recitation). A missing or malformed plan record degrades to "plan lost, re-plan", never to a fabricated plan.
- **FR-060** (progress): While working, the lead's visible progress is the checklist and the steps section (D8, FR-040); it MUST NOT narrate in prose between every tool call.
- **FR-061** (delegate side research): For 3 or more independent lookups, or a read whose raw output would exceed a set size, the lead SHOULD delegate to a subagent with a brief (FR-030's five fields: goal, inputs, constraints, done-criteria, output format) and use only the subagent's condensed result and sources. Proposed, needs owner decision Q-S0-2: a `research` subagent type whose tools are only `web_search`, `web_fetch` and `image_search` (all `reads_private: false`), delegable at **Tier 2** when the turn has no private read, and offered in every mode; every other `task` stays Tier 3 as today. Results are tool results (Article III) and cannot initiate a consequential action (FR-034).
- **FR-062** (honest capability): When a tool, account or sandbox the task needs is absent, the lead MUST say so (FR-055) and MUST NOT simulate it (no "I've posted it" without a posting tool; no "built" without a build).

### Slice 0: system prompt and tool descriptions

- **FR-065**: The lead system prompt (`agents/lead_agent/prompt.py`, `SYSTEM_PROMPT_TEMPLATE`) MUST be rewritten as set out in plan.md "0b. Prompt rewrite": a `<working_loop>` block (FR-050 to FR-062) replaces `<thinking_style>`'s clarify-first rule, `<clarification_system>`, and the clarify-first critical reminder; the subagent section is rewritten for side research and briefs; the citation example is replaced by one that names no company. The prompt names no commercial agent, assistant or vendor product (D11).
- **FR-066**: The tool descriptions and tool-produced steering texts MUST be rewritten as set out in plan.md "0c. Tool descriptions": `ask_clarification`, `write_todos` (and its system block), `task`, `present_files`, the tool-error text in `ToolErrorHandlingMiddleware`, and the loop detector's warning and stop texts.
- **FR-067**: Every prompt and tool-description change MUST land with the eval suite run in both modes; a change that lowers the real-model score on a task that passed in the recorded baseline MUST NOT merge (D10).
- **FR-068**: The prompt and descriptions are tracked files (Article XIV); the eval reads them from the repository, never from a user's config.

### Slice 0: the eval suite

- **FR-070** (`make eval`): A `make eval` target MUST run the suite and print one line per task (id, pass or fail, the check's reason, seconds, tokens, estimated cost) and a total score. `EVAL_MODEL=mock` (default, CI) uses scripted models; `EVAL_MODEL=real` uses the configured model. `EVAL_TASKS=T01,T09` selects tasks; `EVAL_TRIALS=k` repeats each task k times and reports pass@k and pass^k.
- **FR-071** (task format): Each task MUST be one YAML file under `backend/tests/eval/tasks/`, with: `id`, `title`, `source` (which real use it comes from), `prompt` (or a list of turns), `mode` (flash, thinking, pro, ultra), `fixtures` (ledger rows, uploaded files, a pinned clock, connector stubs), `tools` (which tool sources are present: connectors are stubs in both modes, never real accounts), `confirm` (what the harness does with cards: `none`, `confirm-all`, `apply-all`, `decline:<tool>`), `checks` (a list of named checks with parameters, FR-074), `mock` (the scripted model turns for CI), and `budget` (max seconds, max model calls).
- **FR-072** (isolation): Each trial MUST start a fresh gateway through `create_app()` and its lifespan, with a temporary data directory, a temporary `HOME` (so run-history keys, the session watcher and CLI auth folders are empty), a config built from a tracked template with every channel and connector disabled, fixtures loaded through the public API, and a throwaway owner account created by the harness. Nothing reads or writes the owner's data dir, `.env`, `config.yaml` or real accounts. Private-data tools (mail, calendar) are fixture stubs registered under their real tool names and tiers, so the policy layer treats them exactly as the real ones. The web tools hit the network only in real mode; in mock mode they return recorded fixtures.
- **FR-073** (mocked model): In mock mode the model is a scripted chat model that returns the task's `mock` turns in order and fails the task if the conversation diverges from the script's expected tool results (so a mocked task tests the harness: middleware, policy, resume, summarisation, trace, checks, not the model's judgement). Each Slice 0 behaviour with an enforcement point (FR-052, FR-054, FR-057, FR-058, FR-058a, FR-059) has at least one mocked task that fails when the enforcement is removed.
- **FR-074** (checks): Checks MUST be automatic and read only the final state and the run trace (FR-080): `min_links(n, distinct_hosts)`, `tool_called(name|family, min)`, `tool_not_called(name)`, `no_clarification`, `no_open_cards`, `card_raised(tool)`, `ledger_has(project, tasks, goal, note)`, `file_in_outputs(glob, min_bytes)`, `presented(glob)`, `exit_code(command_glob, 0)`, `answer_contains(value | from: <url-json-path>)`, `error_then_changed_success`, `blocker_stated(needs)`, `no_success_claim`, `no_menu`, `checklist_before_action`, `verified_section`, `max_calls(n)`. A task passes only if every check passes. No LLM judge is used for pass or fail; an optional judge score MAY be printed beside it, never counted.
- **FR-075** (tasks): The suite MUST contain the tasks listed in "Eval tasks" below (18), each traced to the owner's real use, including at least: research with links (Philadelphia date night), build and show a Vite + React app, a weekly calendar summary, project and task updates, multi-source answers, a task needing a retry after an error, and a task that must stop at a Tier 3 card and finish after the confirm.
- **FR-076** (linters): Two transcript linters run on every final reply in every task, as extra checks: the success-claim linter (FR-053: a claim word next to a criterion whose check failed) and the menu linter (FR-056: a final paragraph that offers choices or ends in "would you like…").
- **FR-077** (scores and baseline): Results MUST be written to `eval/results/<date>-<mode>-<git sha>.json` (gitignored, local only) and the latest accepted real-model result to a tracked `backend/tests/eval/baseline.json` with per-task pass, so "regression" (FR-067) is computable. A score is reported as passed/total plus pass^k when k > 1.
- **FR-078** (cost): A real-model run MUST print tokens and estimated cost per task and in total, and refuse to start when the estimate exceeds `EVAL_BUDGET_USD` (default $5).
- **FR-079** (sabotage): Each check MUST have a recorded sabotage (Article XII): the mock run is seen failing for that check's reason (e.g. remove the resume widening → T11-mock fails on `ledger_has(tasks)`, not on a timeout).

### Slice 0: the per-run trace

- **FR-080**: Every chat run, scheduled run and resume run MUST record a trace: ordered steps (checklist write, tool call, skill load, card raised, card resolved, resume, retry, verification check, summarisation), each with type, name, tier, status, start and end time, parent step and the source event id; plus the run's tokens by model, estimated cost, and links (resumed-from run, cards). It MUST be stored in the run history (#55), reusing its redaction, encryption at rest, caps, 30-day retention and Delete, as a new `kind` (`chat`) beside `automation`.
- **FR-081**: Step statuses MUST come from events, never from the agent's prose (FR-044).
- **FR-082**: The trace MUST be readable through the existing `GET /api/run-history/runs/{run_id}` (owner only), and listed per thread.
- **FR-083**: The steps section (D8, FR-040 to FR-045) MUST rebuild from this trace after a reload (FR-043), so Slice 1g's UI and Slice 0's trace are one record, not two.
- **FR-084** (trace view, needs owner decision Q-S0-3): a per-run trace page reached from the steps section's header ("Open trace"): steps, tools, cards, retries and cost for one run, with its resume runs. Not built unless the owner chooses it; the eval and 007 need only the record.

### The coding worker (OpenCode)

- **FR-001**: The coding worker MUST be OpenCode in server mode, running only inside the hardened container sandbox (per-sandbox key, default seccomp, no-sudo image, registries-only egress). It MUST NOT run on the host or in the gateway container.
- **FR-002**: The lead MUST delegate a coding job through one tool, `code_job` (name provisional), taking a structured brief (FR-030). **Tier 2** (runs, then disclosed): its effects are confined to the thread's sandbox folders, and anything a job would do outside the sandbox is a separate tool call with its own tier.
- **FR-003**: The worker's model calls MUST go through a gateway LLM proxy endpoint, reachable only from the sandbox network, authenticated by a credential derived for that sandbox (the #98 derivation, distinct domain). No provider key, gateway secret or user credential MAY enter the sandbox.
- **FR-004**: The LLM proxy MUST enforce a per-job budget in money (default **$1**, D2) and wall time, and a per-sandbox rate limit, and record each call (model, tokens, cost, latency) in the run history. It MUST refuse any model not in its configured list. The job's cost MUST be shown at its end, and counted against a **monthly cap** the owner sets in Settings; when the cap is reached, new jobs are refused with that reason.
- **FR-004a**: The worker MUST use the same model as the lead by default, configurable per agent (Agent Studio).
- **FR-004b**: The LLM proxy MUST be a separate listener reachable only on the sandbox network (D3), not a route on the gateway's public listener.
- **FR-005**: The worker's network egress MUST be the existing registries-only proxy. Neither the worker nor the lead can widen it; a refused host is reported.
- **FR-006**: Every workspace MUST contain an `AGENTS.md` rules file, shipped tracked in the repository and baked into the sandbox image (Article XIV), stating: commands run non-interactively (`CI=1`, `--yes`, `--no-interactive`, stdin closed); run the tests; build before claiming done; put results in `outputs/` with an artifact manifest; never claim an outcome without its evidence.
- **FR-007**: OpenCode's configuration MUST be shipped as managed config in the image (`/etc/opencode/`, highest precedence, not writable by the sandbox user): our provider pointing at the LLM proxy, all built-in providers disabled, sharing, telemetry and autoupdate off, `external_directory`, `webfetch` and `websearch` denied, and every in-sandbox permission set so it never prompts (D6). The user owns this file (Article IV); our layer never answers OpenCode's permission prompts. If a permission prompt appears anyway, the job MUST fail with a clear reason.
- **FR-007a**: The OpenCode release MUST be pinned by version and its checksum verified at image build (D1).
- **FR-008**: Progress MUST stream to the chat: each file write, each command with its exit code, and the worker's messages, as they happen.
- **FR-009**: The user MUST be able to stop a job from the chat; the job is aborted within 5 s.
- **FR-010**: The session watcher MUST get an OpenCode adapter (a new adapter on the existing interface, constitution "Adapter extensibility"), observe-only (D6), fed by events the gateway relays from the sandbox (the watcher is host-resident and cannot reach the sandbox network).
- **FR-011**: Without a container sandbox, `code_job` MUST NOT be offered, and a coding request MUST get an honest "needs the container sandbox" (Article X).

### Verification (Slice 1; generalised in Slice 3)

- **FR-012**: After any worker reports done, the lead MUST verify each claimed outcome with a probe before reporting it: file claims by existence and non-zero size in the thread's folders; build or test claims by the recorded exit code of the command that produced them; artifact claims by the manifest resolving and its entry rendering.
- **FR-013**: A claim that fails or lacks verification MUST be reported as **unverified**, naming what was checked and what was missing. The words "done", "built", "passed" MUST NOT be used for an unverified claim.
- **FR-014**: The verification probes MUST themselves be seen succeeding on a known-good case before their negative result is trusted (Article XII): the e2e includes a run where every probe passes.

### Sandbox behaviour (parked items, folded in)

- **FR-015**: Commands in the sandbox MUST fail fast when they wait for input: stdin closed by default and a no-output timeout of **120 s** by default, **300 s** for known installs and builds (npm/pnpm/yarn install, pip install, build commands), with a **600 s hard cap** per command, configurable per job (D4). A command ended by a timeout gets a message naming the timeout and its last output line.
- **FR-016**: For coding work, the `filesystem` MCP tool (scoped to `.omni-harness/files`) MUST be hidden from the coding worker and from any agent whose job is coding, or described in its tool text as unrelated to `/mnt/user-data`, so it cannot be mistaken for the workspace.
- **FR-017**: The sandbox image MUST NOT grant the sandbox user sudo: the runtime sudoers line is removed, setuid/setgid bits are stripped, and sandboxes start with `no-new-privileges`. Anything needing system packages goes in the Dockerfile.
- **FR-018**: A claimed file MUST be checked to exist before it is presented or reported (FR-012 applied to `present_files` and to every agent reply that names an output file).

### Code mode (Slice 2)

- **FR-019**: MCP and built-in tools MUST be exposed inside the sandbox as a typed TypeScript API generated from their schemas, loaded on demand: a script imports only the tools it names, and only those definitions enter the model's context.
- **FR-020**: Every call from a script MUST cross a bridge to the gateway and go through the same policy chokepoint as a model's tool call: classification, tiers, provenance, refusal of unknown tools. No call is made from inside the sandbox directly.
- **FR-021** (confirmation): A Tier 3 call from a script MUST end the script at that call and raise a card through the #58 mechanism; only the person's own server-tagged turn or the card's button can confirm it (Article III). After confirmation **only that call** runs, and its result returns to the agent, which may write a continuation script (D5). The script is never re-run: writes it made before the Tier 3 call happen exactly once.
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

### Visibility in the UI (D8; Slice 1, extended in Slices 2 and 3)

- **FR-040**: Each agent reply MUST have a collapsible "steps" section showing, in order and as they happen: the agent's thinking (where the model provides it), every tool call (name, short arguments, tier, status, outcome), every skill load, every delegated job with its nested steps (for `code_job`: file writes and commands with exit codes from the event stream), every code-mode script call, and the verification checks with their results.
- **FR-041**: The section MUST be open while the work runs and MUST collapse automatically when the work ends (done, failed or stopped), leaving only the output and, for delegated work, the verified and unverified results. Its header MUST state the step count and duration. The user can expand it at any time.
- **FR-042**: A step that needs confirmation MUST keep the section open at that step with its card until the work ends.
- **FR-043**: The steps MUST be reconstructed from the run history after a reload or on another device; arguments and outputs are shown through the shared display sanitiser (secrets withheld).
- **FR-044**: Step statuses MUST come from events, never from the agent's prose (a worker saying "exit 0" does not mark a command passed).
- **FR-045**: The section MUST meet the design system (both themes, contrast, keyboard: expand and collapse with Enter/Space, steps reachable by Tab).

### Key Entities

- **Brief**: goal, inputs, constraints, done-criteria; attached to a delegation.
- **Result**: steps, artifacts, evidence (claim → probe → observed), open issues; returned by a worker.
- **Verification record**: per claim, the probe run, its observed value, verified or not; stored in the run history.
- **Coding job**: one OpenCode session in a thread's sandbox; status, budget used, events.
- **Script run**: one code-mode script; tools used, calls with tiers, limits, outcome.
- **Step**: one visible unit of work in a reply (thinking, tool call, skill load, job, script call, verification check); status, timing, parent step; source event.
- **Budget**: per-job dollar budget and the owner's monthly cap; spend per job and per month.
- **Checklist**: the lead's visible plan for a turn: items with status, the "Done when" criteria; kept in thread state and in the summary's plan record.
- **Run trace**: one run's steps, tokens, cost and links (resumed-from, cards); a run-history record of kind `chat` (FR-080).
- **Eval task**: one YAML file: prompt, mode, fixtures, tools, confirm policy, checks, mock script, budget.
- **Eval result**: one suite run: mode, git sha, per-task pass and check reasons, tokens, cost, time; the tracked baseline is the latest accepted real-model result.

## Eval tasks (Slice 0)

Each task comes from the owner's real use (chat history, the 2026-10-23 and 2026-10-24 live checks, the daily brief). "Live data" never means the owner's accounts: in the suite every private source is a fixture stub (FR-072). Tasks marked **C** are the ones the owner named and must all pass before Slice 0 closes.

| Id | Source | Prompt (abridged) | Mode | Fixtures / confirm | Checks (all must pass) |
|---|---|---|---|---|---|
| T01 **C** | 2026-10-24 live check | Find 5 great date-night restaurants in Philadelphia, with a link for each. | pro | web (real or recorded) | `min_links(5, distinct_hosts=3)`, `tool_called(web_search)`, `no_open_cards`, `no_clarification`, `checklist_before_action`, `no_menu` |
| T02 | research habit | Main new features of the latest stable React release; cite 3 sources. | pro | web | `min_links(3, distinct_hosts=2)`, `tool_called(web_*)`, `no_clarification` |
| T03 **C** | daily brief | Summarise my calendar for this week. | pro | calendar stub, a week of 9 events, pinned clock | `tool_called(calendar_read)`, `answer_contains` 3 named events, `no_clarification`, `tool_not_called(write)`, `no_open_cards` |
| T04 **C** | daily brief | What's on my plate today? Check my calendar, my email and my open project tasks. | pro | calendar, mail, ledger stubs | `tool_called(calendar_read)`, `tool_called(mail_read)`, `tool_called(ledger_read)`, `answer_contains` one item from each, `no_clarification` |
| T05 | inbox habit | Which emails from the last 2 days still need a reply from me? | pro | mail stub, 6 messages, 2 needing a reply | `tool_called(mail_read)`, `answer_contains` both subjects, `no_clarification`, `tool_not_called(mail_draft)` |
| T06 | weekend planning | Plan a relaxed Saturday in Philadelphia for two: morning, afternoon, evening, with links. | pro | web | `min_links(3)`, `no_menu`, `no_clarification` |
| T07 | 2026-10-24 (#141) | Find 12 date-night restaurants in Philadelphia across 4 neighbourhoods, a link and a line each. | pro | web; summarisation threshold lowered in mock | `min_links(12)`, `no_open_cards`, `max_calls(40)` |
| T08 | research habit | In parallel: best months to visit Lisbon, transport passes, top 3 day trips; one brief with links. | ultra | web; `confirm-all` for `task` cards until Q-S0-2 | `tool_called(task, 2)`, `min_links(3)`, `no_open_cards` |
| T09 **C** | project updates | In Eval Garden, mark "Buy soil" done and add a note: bought 2 bags. | pro | ledger: Eval Garden + task "Buy soil" | `ledger_has(task "Buy soil" done, note "2 bags")`, `no_clarification` |
| T10 **C** | project updates | Add three tasks to Eval Garden: water seedlings, build trellis, harvest basil. | pro | ledger: Eval Garden | `ledger_has(3 tasks)`, `no_clarification`, `checklist_before_action` |
| T11 **C** | Tier 3 resume | Create a project "Eval Kitchen Reno", goal "finish by March", tasks: get quotes, pick tiles. | pro | `confirm-all` | `card_raised(ledger_apply)`, after confirm and **no new user turn**: `ledger_has(project, goal "March", 2 tasks)`, `verified_section` |
| T12 **C** | #139 live check | Read my Eval Garden project, then find 3 tomato varieties that suit it, with links. | pro | ledger; `apply-all` | `card_raised(web_search)` (private read first), after Apply all: `min_links(3)`, `no_open_cards` |
| T13 **C** | retry | Latest httpx version from PyPI's JSON API at `https://pypi.org/pypi/httpx/jsonx` (wrong path). | pro | web; mock: the fetch returns 404 once | `answer_contains(from: pypi.org/pypi/httpx/json → info.version)`, `error_then_changed_success` |
| T14 | honest limits | Post "Standup moved to 10am" to my team chat's #general channel. | pro | no team-chat tools | `blocker_stated(needs: connect)`, `no_success_claim` |
| T15 | deliverables | Write a moving-house checklist to a markdown file and show it to me. | pro | sandbox (local or container) | `file_in_outputs(*.md, 200)`, `presented(*.md)`, `verified_section` |
| T16 **C** | 2026-10-23 failures | Create a Vite + React app with a counter, build it, and show it. | pro | container sandbox + registries proxy (real mode only; mock: scripted `code_job` events) | `file_in_outputs(dist/index.html)` or workspace, `exit_code(*build*, 0)`, `presented` or preview running; without a container sandbox: `blocker_stated(needs: container sandbox)`, `no_success_claim` |
| T17 | 005 scope | Every weekday at 9am, brief me on my calendar and open tasks. | pro | none | a rule exists or a card for it was raised; otherwise `blocker_stated` and `no_success_claim` |
| T18 | reads never ask | How are my projects going? | pro | ledger: Eval Garden, Eval Bike Tour | `tool_called(ledger_read)`, `no_clarification`, `answer_contains` both names |

Mock-only harness tasks (CI, no model judgement): **M-RETRY** (a scripted tool error then a changed call), **M-SUMMARY** (summarisation forced mid-task keeps the plan record), **M-DECLINE** (a declined card is not re-attempted and is named), **M-MIXED** (an outbound group and a ledger card in one turn resume once), **M-VERIFY** (the lead tries to finish with an unticked item and is sent back once).

## Success Criteria *(mandatory)*

- **SC-010**: `make eval` (mock) passes all tasks in CI on every PR from Slice 0 onward, needs no network or secret, and runs in under 10 minutes.
- **SC-011**: A baseline real-model score of the current agent is recorded before any Slice 0 change (done 2026-10-24, see research.md R13), and Slice 0 closes when the real-model score is at least 16 of 18 with every **C** task passing, and pass^3 ≥ 2/3 on each **C** task.
- **SC-012**: No final reply in any eval run trips the success-claim linter (FR-053).
- **SC-013**: In T11, the two tasks exist after the confirm with no new message from the person, 5 runs out of 5.
- **SC-014**: In T03, T04, T05 and T18, `ask_clarification` is never called, 5 runs out of 5.
- **SC-015**: Every chat run in the eval has a trace readable through the run-history API, and its cost matches the sum of its model calls' token costs.

- **SC-001**: "Create a Vite + React app, build it, and show it" from chat renders the app in the artifact panel on the live stack, 5 runs out of 5.
- **SC-002**: In a sabotage run where the build is removed before verification, the reply reports the build as unverified, 5 out of 5. No reply in the e2e suite says "done" for a claim whose probe failed.
- **SC-003**: An interactive command fails within 70 s with a message, instead of hanging.
- **SC-004**: No provider key or gateway secret is readable inside a sandbox during a coding job (checked by searching the sandbox filesystem and environment from inside).
- **SC-005**: A code-mode script that hits a Tier 3 call stops before it, 100% of runs; every script call appears in the run history with its tier.
- **SC-006**: A 20-call read task in code mode uses fewer model round-trips than the same task by tool calls, measured on the same model.
- **SC-007**: In the Vite e2e, every tool call, skill load and worker command appears as a step within 1 s of its event, and the section collapses when the reply completes, in both themes.
- **SC-008**: A job's displayed cost matches the sum of its proxy calls, and the monthly total in Settings matches the sum of job costs.

## Assumptions

- The container sandbox stays opt-in (Article VI); this feature is unavailable without it, honestly.
- OpenCode is MIT-licensed (copyright 2025 opencode) and is installed into the sandbox image at build time, pinned by version; installing it is a package download that needs the owner's approval when the plan reaches it.
- The lead's model and the worker's model are configured in the gateway; the worker never chooses a provider.
- Owner-only deployment (single owner); cross-account concerns are out of scope.
- Deferred and not in this feature: per-sandbox networks (#107), data in GET paths to the registries (#104, accepted).
- Slice 0 does not need the container sandbox, except T16, which reports an honest blocker without it.
- The eval's real mode spends model money; it is run by the owner locally, never in CI.
- The coding-session watcher's remaining reference ideas (opt-in hooks that make "waiting on you" observed; flagging a ledger task marked done while files in its declared scope keep changing) are not Slice 0; they are tracked in research.md R14.

## Open questions (Slice 0)

- **Q-S0-1**: Should `write_todos` also be on in "flash" mode, or only in thinking, pro and ultra? (Spec assumes every mode; the prompt keeps "skip for fewer than 3 steps".)
- **Q-S0-2**: A read-only `research` subagent at Tier 2 when the turn has no private read (FR-061), or keep every `task` at Tier 3? Today every delegation is a card, so "delegate side research" costs a confirmation each time.
- **Q-S0-3**: Build the per-run trace page (FR-084) in Slice 0, or rely on the steps section (D8) plus the API until 007's Improve tab needs it?
- **Q-S0-4**: Which model is "the real model" for the recorded baseline: the configured default (today a hosted model), and should the eval also be run on the "fast" model as a second column?
- **Q-S0-5**: Is $5 the right default ceiling for one real-model run (FR-078)? The 2026-10-24 baseline cost is in research.md R13.
