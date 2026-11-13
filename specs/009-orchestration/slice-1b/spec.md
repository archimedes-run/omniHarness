# Feature Specification: 009 Slice 1b, OpenCode upgrades

**Feature Branch**: `spec-009-slice-1b` (docs); build branches per `plan.md`

**Created**: 2026-11-13

**Status**: Draft. The owner is away; every open question below has a recommended default, recorded as decided. Reversing one is a one-line change in this file plus the matching config default.

**Input**: owner requirements of 2026-11-13: (A) per-job model routing through the gateway proxy, Claude models included, no keys in the sandbox; (B) question cards: the worker's questions pause the job and surface in chat, answered only by the owner; (C) real repos: a copy in the sandbox, a branch, tests, a diff for review, nothing touches the owner's checkout without approval; (D) bigger budgets and time limits, a plan step, iterate until tests pass; (E) real coding evals replacing the toy gate.

**Builds on**: Slice 1 as built (`../plan.md`, "Slice 1: as built"): OpenCode 1.19.3 per job as `opencode run --format json`, the sandbox-only LLM proxy with per-job tokens and reserved money, gateway-side verification, the code-job card. Slice 0 (PR #174): the resume after cards, the Tier 2 disclosure line (FR-063), the eval harness (`backend/tests/eval`, `make eval`). Slice 1b does not start building until #174 is merged.

**Shared contract**: the question card is specified once, in [`../question-card.md`](../question-card.md), and used here and by spec 010.

## Decisions (defaults taken, 2026-11-13)

| # | Question | Decision |
|---|---|---|
| D1b-1 | How does OpenCode ask? | In 1.19.3 the `question` tool exists, but `opencode run` without a terminal adds a session rule denying it, and answers come back only through the OpenCode server's `/question/:id/reply` route. Running that server in the sandbox would give the worker's own processes a local route to answer their own question. **Decided**: keep `opencode run`; ship a root-owned helper `omni-ask` in the image. The worker runs it (question, 2 to 4 options, a suggested one), it writes the question to the job folder and tells the worker to end its turn; the gateway sees it when the run exits, pauses the job and opens a card. The answer resumes the same OpenCode session (`opencode run --session <id>`). OpenCode's own `question` stays denied. |
| D1b-2 | Claude models: OpenAI-compatible endpoint or native Messages API? | **Native Messages API** adapter in the proxy (the worker still speaks chat-completions to the proxy). Reason: correct usage accounting (cache read/write tokens), prompt caching, and the provider's full error and stop semantics. The compatible endpoint stays as a fallback per model (`api: openai_compatible`). |
| D1b-3 | Timeout for a job's question | **30 min**, then the job **stops** (status `blocked: question unanswered`), work and branch kept, no model spend while paused. |
| D1b-4 | How a repo gets in | From a folder under an owner-configured root (`code_jobs.repo_roots`), as `git archive` of one commit (default `HEAD`): tracked files only, **no history**, uncommitted changes not included (said on the card). |
| D1b-5 | Where "Apply" lands | A **new branch** `omni/<job-id>` in the owner's repository, one commit, built with git plumbing; the owner's current branch, index and working tree are not touched. A patch file is always downloadable as well. |
| D1b-6 | Budget and time | Quick job (no repo): **$1 / 30 min**, unchanged. Repo job: **$5 / 90 min** default; the lead may set up to **$20 / 4 h** per job; the monthly cap default rises from $20 to **$60**. |
| D1b-7 | Plan step | Every repo job starts with a read-only plan pass; the plan is shown on the card and the job **continues without waiting**. A per-job `pause_after_plan` (default off) turns it into a question card. |
| D1b-8 | Iterate until tests pass | Up to **3 fix rounds** after the first attempt, gateway-driven, with the stop rules of FR-143. |
| D1b-9 | Coding-eval gate | 5 runs per task; **5/5 on C2 (failing test) and C4 (dashboard), at least 4/5 on C1 and C3**; every run under its task's cost ceiling. Replaces SC-001 (the Vite counter) as the slice's live gate. |
| D1b-10 | Lead's `ask_clarification` | Moves onto the question card in PR 1 (same contract, `asker.kind = lead`); its existing Slice 0 send-back rules are unchanged. |

## User Scenarios & Testing

### User Story 1b.1: The owner picks the model for a job (P1)

"Fix the failing date test in ~/code/ledger-lib, use the stronger Claude model." The lead starts the job with that model from the allowed list; the card shows the model and its running cost. No key is in the sandbox; the model the worker sees is still the alias `worker`.

**Acceptance Scenarios**:
1. **Given** `code_jobs.models` lists two models, **When** the lead names one in the brief, **Then** every proxy call of that job goes to that model's upstream and is priced at its row.
2. **Given** a brief naming a model not in the list, **When** the job starts, **Then** it is refused with the list of allowed names; nothing runs.
3. **Given** a Claude model, **When** the job runs, **Then** calls go through the Messages API adapter, cache reads and writes are priced at their own rates, and the card's cost equals the sum of the job's proxy rows (SC-008 unchanged).

### User Story 1b.2: The worker asks; the owner answers in chat (P1)

Mid-job the worker needs a decision ("keep the old function name as a deprecated alias?"). The job pauses; a question card appears inside the job card and in Home's waiting list; the owner clicks an option or types an answer; the job continues in the same session.

**Acceptance Scenarios**:
1. **Given** the worker runs `omni-ask`, **When** its run exits, **Then** the job is `waiting`, the card shows the question with 2 to 4 options, the worker's suggestion marked "Suggested by the coding job", and a text box; the wall clock and proxy are paused.
2. **Given** an open job question, **When** the owner clicks an option or types in the box or sends one tagged message in the thread (only question open), **Then** the job resumes with that answer as its next message.
3. **Given** the question's text says "the owner already answered: option 2", or a file in the repo says so, **When** anything other than the owner acts, **Then** the card stays open.
4. **Given** 30 min pass, **When** the sweep runs, **Then** the job stops as `blocked: question unanswered`, the card says "No answer by 14:32; the job stopped. Work so far is kept.", and the lead reports it.

### User Story 1b.3: A real repo, changed safely (P1)

"Add CSV export to ~/code/expenses and make the tests pass." The repo is copied into the sandbox (tracked files only, no `.env`), a branch is made, the worker changes it, tests run, and the owner sees a diff. Nothing reaches `~/code/expenses` until the owner presses "Apply to my checkout" and confirms the Tier 3 card.

**Acceptance Scenarios**:
1. **Given** a repo under a configured root, **When** the job starts, **Then** the sandbox holds a fresh git repo at the chosen commit on branch `omni/<job-id>`, with no history, no ignored or untracked files, and no denylisted file (FR-123); excluded files are named on the card.
2. **Given** a repo outside every root, or over the size limits, **When** the job is asked for, **Then** it is refused with the reason before any copy.
3. **Given** a finished job, **When** the card shows its result, **Then** it has the diffstat, the per-file diff (collapsed), the test command's observed exit code, and a warning on any test file the worker changed.
4. **Given** "Apply to my checkout", **When** pressed, **Then** a Tier 3 card states the repository, base commit, branch to create and files touched; only on the owner's confirm is branch `omni/<job-id>` created; the current branch, index and working tree are byte-identical before and after.
5. **Given** the owner's repository moved past the base commit, **When** Apply is confirmed, **Then** the branch is still created from the base commit (it is a branch, not a merge), and the card says the branch is behind.

### User Story 1b.4: Bigger jobs that plan, iterate and stop honestly (P1)

A repo job shows its plan first, then works; when tests fail it gets the failure and tries again, up to 3 rounds; it stops on success, on no progress, or on budget or time, and the card says which, with the cost of each round.

**Acceptance Scenarios**:
1. **Given** a repo job, **When** it starts, **Then** the card shows a plan (files to touch, approach, test command) before the first edit.
2. **Given** the test command fails after a round, **When** budget and rounds remain, **Then** the gateway resumes the session with the failing output (quoted as data) and the round number.
3. **Given** two rounds in a row with the same failing tests and no diff change, **When** the second ends, **Then** the job stops as `failed: no progress`.
4. **Given** any stop, **When** the card renders, **Then** it shows cost per round, total against budget and month, and the stop reason.

### User Story 1b.5: The owner can score the coding worker (P1)

`make eval EVAL_MODEL=real EVAL_SUITE=coding` runs four repo tasks five times each and prints pass counts, cost per run and the gate result.

**Acceptance Scenarios**:
1. **Given** a clean checkout, **When** the coding suite runs in mock mode in CI, **Then** each task's checks pass on its known-good patch and fail on each known-bad patch (checks seen failing).
2. **Given** real mode, **When** it finishes, **Then** per-task pass^5, cost per run, and the gate (D1b-9) are printed and saved under `eval/results/`.

## Requirements

### A. Per-job model routing

- **FR-100**: `code_jobs.models` (config) lists the models a job may use, each a name under `models:`; default: the lead's model only. `code_job`'s brief gains `model` (optional; default the lead's model).
- **FR-101**: The job's model name MUST be fixed at job start and carried in the signed job token; the proxy resolves the upstream from the token, never from the request. The worker still asks for `worker`; any other model id is refused (unchanged).
- **FR-102**: Upstream base URLs and keys come only from gateway config. A brief, the worker's request, headers or repo files cannot name a host, URL, key or provider.
- **FR-103**: A Messages API upstream adapter translates the proxy's already-sanitised chat-completions request to the provider's Messages request and streams the reply back as chat-completions chunks: function tools only, no provider server-side tools, the same content rules (text and bounded inline images), output length set by the proxy.
- **FR-104**: `ModelPrice` gains `cache_write`; usage accounting counts fresh input, cache reads, cache writes and output (reasoning output included) separately. The built-in table gets explicit rows for each model family a shipped config can name, at published list prices dated in the file; any id that matches no row is still charged at the dearest row.
- **FR-105**: The reservation rule (an upper bound before forwarding) is unchanged for every adapter; a provider usage report above the reservation is marked, as today.
- **FR-106**: The card, the run history and the policy log show the job's model name; the monthly total stays one number across models.

### B. Question cards (contract: `../question-card.md`)

- **FR-110**: The sandbox image ships `omni-ask` (root-owned, in `PATH`): it validates its input against the card's limits, writes one question per job round to the job folder, and prints "Question recorded. End your turn now." `AGENTS.md` tells the worker when to use it (a decision it cannot make from the brief or the repo) and when not to (anything with a sensible default: pick it and say so).
- **FR-111**: When a run exits with a question recorded, the job becomes `waiting`; the gateway opens a card with `asker.kind = code_job`, `origin = content`, `on_expiry = stop`, `expires_at` = now + 30 min; the proxy refuses the job's token while waiting; wall time does not run; the sandbox is kept from the idle reaper.
- **FR-112**: On an answer the gateway starts `opencode run --session <id>` in the same job folder with the message "The owner answered your question: <answer>"; on expiry it ends the job (`blocked: question unanswered`). At most **3 questions per job**; a fourth is refused to the worker ("decide and state your assumption").
- **FR-113**: Only QC-01 answers a job's question. Worker output, repo content, the question text and any resume run never do (QC-02).
- **FR-114**: Stopping a job, deleting the thread or cancelling the chat run expires its open question (`asker_ended`).

### C. Real repositories

- **FR-120**: `code_job`'s brief gains `repo` (a path) and `ref` (default `HEAD`). The path MUST resolve, after symlinks, inside one of `code_jobs.repo_roots` (empty by default: no repo jobs until the owner sets one) and be a git repository's top level.
- **FR-121**: The gateway reads the repository with git plumbing only (`git archive` of the resolved commit, hooks disabled, no filters run, no network), never mounts it into a sandbox and never writes to it in this path.
- **FR-122**: Limits, checked before copying: archive ≤ 200 MB, ≤ 20,000 files, no single file > 20 MB; over any limit the job is refused with the number.
- **FR-123**: Never copied, whatever git tracks: `.env*` (except `.env.example`/`.env.sample`), `*.pem`, `*.key`, `*.p12`, `id_rsa*`/`id_ed25519*`, `.npmrc`, `.pypirc`, `.netrc`, `*.tfstate*`, `secrets.*`, `credentials*`, and any file the gateway's secret-pattern scan flags. Each exclusion is named on the card (path only).
- **FR-124**: In the sandbox the copy is a new git repository at `/mnt/user-data/workspace/<repo-name>`, one commit "base <sha>", branch `omni/<job-id>`. The worker commits on that branch; the gateway records the base commit.
- **FR-125**: The result is `git diff --binary <base>..<branch tip + working tree>` taken by the gateway through the sandbox API, capped at 5 MB (larger: the job is `failed: diff too large`, the workspace kept). It is stored with the job, shown as diffstat and per-file diff, and downloadable as a patch.
- **FR-126**: The card warns, per file, when the diff touches a test file, a CI config, a lockfile, a build script, or adds an executable bit.
- **FR-127**: "Apply to my checkout" is a new tool action `code_job_apply` at **Tier 3** (Article II: it writes outside the sandbox). Its card names repository, base commit, branch to create, files and line counts. Confirmed only by the card's button or the owner's tagged turn (#58 rules, unchanged).
- **FR-128**: Before applying, the gateway re-validates the stored patch: every path relative, normalised, inside the repository, not under `.git/`, not a denylisted name (FR-123), no symlink created or followed out of the tree, no submodule change, no setuid/setgid mode; `git apply --check` against the base commit in a temporary index. Any failure refuses the whole apply and names the path.
- **FR-129**: Apply creates `refs/heads/omni/<job-id>` (refusing if it exists) with one commit on the base commit, through a temporary index; it never checks out, never touches `HEAD`, the index or the working tree, and runs no hooks.
- **FR-130**: The patch and the apply record (who confirmed, when, branch, commit id) go to the run history; the Tier 3 audit already records the confirmation.

### D. Budgets, plan, iteration

- **FR-140**: Per-job budget and wall time per D1b-6; the brief may ask up to the config ceilings (`budget_max_usd` 20, `wall_max_seconds` 14,400); the monthly cap default is $60. A job whose budget exceeds what is left of the month is refused with both numbers.
- **FR-141**: A repo job's first round runs OpenCode's read-only plan agent; its final message is stored as the plan (shown on the card, quoted as the worker's words). With `pause_after_plan` the plan becomes a question card ("Go ahead / Change approach" + free text), `on_expiry = stop`.
- **FR-142**: After each round the gateway runs the test command (brief `verify_command`, or detected: `npm test`, `pytest`, `go test ./...`, `cargo test`) under the existing hard cap, its exit code observed through the sandbox API.
- **FR-143**: Stop rules, first match wins: tests exit 0 → `verified`; 3 fix rounds done → `failed: tests still failing`; same failing test names and identical diff as the previous round → `failed: no progress`; budget, wall time, month cap → `blocked`; question unanswered → `blocked`; Stop → `stopped`.
- **FR-144**: A fix round resumes the same session with the last 200 lines of the test output, quoted as data between markers the output cannot reproduce, and the round number.
- **FR-145**: The card shows the plan, each round (cost, duration, tests passed/failed), the total against budget and month, and the stop reason; the lead reports the stop reason verbatim.
- **FR-146**: If the brief names protected files (for example, a test the job must make pass), a diff touching them makes the result `failed: protected file changed`, whatever the tests say.

### E. Coding evals

- **FR-150**: A coding suite under `backend/tests/eval/coding/`: fixture repos in-repo (small, plain files, no binaries over 100 KB), one YAML per task (brief, fixture, model, budget, checks), run by the existing harness with `EVAL_SUITE=coding`.
- **FR-151**: Tasks: **C1** add a feature to an existing small service (hidden tests added only at check time); **C2** fix a bug a failing test exposes (that test file protected, FR-146); **C3** a multi-file refactor (a rename across 6+ files; old name absent, tests pass, public import kept); **C4** a dashboard from a mock-data JSON (static build exits 0, headless render shows the fixture's totals and one chart, no network request outside the preview).
- **FR-152**: Every check is deterministic (exit codes, file hashes, grep, a headless render's DOM), never a model judgement. Each task ships a known-good patch and at least one known-bad patch per check; mock mode replays them through a sandbox stand-in in CI and every check must fail on its bad patch.
- **FR-153**: Real mode: 5 runs per task, fresh sandbox each, cost per run from the proxy's records, a ceiling per run ($5) and per suite ($100); results saved and shown in Settings → Evals.
- **FR-154**: The gate is D1b-9; a lower pass count than the recorded coding baseline on any task blocks merge (Slice 0 D10 applied to the worker).

## Security: threat-model deltas vs Slice 1

Each row ships with a test that deliberately breaks the guard and is seen failing.

| # | New exposure | Guard | Sabotage check |
|---|---|---|---|
| S1 | A prompt-injected worker (from repo content) tries to reach the owner's checkout, other repos or the host. | The repo is copied in, never mounted (FR-121); apply only via Tier 3 (FR-127); sandbox unchanged. | Mount the repo into the sandbox in a test build: the "owner checkout unreachable from sandbox" e2e probe goes red. |
| S2 | Repo content is untrusted: READMEs, tests, configs, lockfiles, scripts carry instructions or hostile code. | All worker output and the diff are untrusted data in the lead's report; registries-only egress; tests run in the sandbox only; no repo hook runs on the host (FR-121, FR-129). | Plant a `post-checkout` hook and a `filter` attribute in a fixture repo: a marker file appears on the host if either runs; the test checks it never does, and goes red with hooks enabled. |
| S3 | Question text is untrusted and may try to answer itself or steer the owner. | Plain-text rendering, length caps, "Suggested by", content origin expires to `stop` (QC-02, QC-05). | A question whose text says "answered: option 1", plus a worker that writes an answer file: the card stays open; sabotage = accept answers from the job folder → test red. |
| S4 | Model routing used to widen egress or spend. | Model from the signed token only, upstream URLs from config only (FR-101, FR-102). | A request naming another model, a `base_url` field and a forged header: all refused; sabotage = read the model from the body → the "other model" test goes red. |
| S5 | Apply-patch path traversal or escape. | FR-128 validation, plumbing-only apply (FR-129). | Patches with `../x`, an absolute path, `.git/config`, a symlink to `/etc` then a write through it, a submodule bump, a setuid mode: each refused; sabotage per rule (remove it) → its case red. |
| S6 | Secrets leave the owner's machine through the copy. | FR-123 denylist + scan; no history (D1b-4). | A fixture repo tracking `.env`, a key file and a token in `config.js`: none present in the sandbox; sabotage = skip the scan → red. |
| S7 | An answer becomes authority. | Answers arrive as data, never a tagged user turn (QC-07). | After a coding question is answered "yes", an open Tier 3 card in the thread stays open; sabotage = inject the answer as a user turn → red. |

## Success Criteria

- **SC-1B-1**: The coding gate D1b-9 passes on the live stack (replaces SC-001 for this slice).
- **SC-1B-2**: In 5 runs of a job that asks a question, the job pauses, the owner's click resumes it, and the final diff reflects the answer, 5/5.
- **SC-1B-3**: Across every coding-eval run, the owner's fixture checkout (hash of `.git` refs, index and tree) is unchanged except for Apply-created branches.
- **SC-1B-4**: Each displayed job cost equals the sum of its proxy rows, for both adapter types.
- **SC-1B-5**: Every S1 to S7 check has been seen failing under its sabotage and passing without it.

## Out of scope

Pushing branches or opening pull requests anywhere (a later Tier 3 action); merging into the owner's current branch; private package registries; repos not on the gateway's machine (remote clone); several concurrent jobs per thread; the OpenCode server mode; per-agent default model in Agent Studio (still config); the steps section for every tool call (D8, tracked in `../plan.md`).

## Open questions (defaults taken)

- **Q-1B-1**: Include uncommitted changes in the copy? **Default: no** (tracked, committed only; the card says so). A later opt-in may add a `git stash create` snapshot.
- **Q-1B-2**: Keep repo history in the copy for `git log`/`blame`? **Default: no** (removed secrets live in history). Revisit with a history secret scan.
- **Q-1B-3**: Gateway in Docker: mount repo roots read-write (needed only for Apply)? **Default: mount read-only**; Apply writes through a separate, narrower mount of `.git` only, documented in deploy notes. If that proves unworkable, Apply falls back to "download patch" and the card says so.
- **Q-1B-4**: Auto-apply the worker's suggested option on timeout? **Default: never** for content-originated questions (QC-05).
- **Q-1B-5**: Allow more than 3 fix rounds? **Default: no**; the brief cannot raise it, config can (max 6).
- **Q-1B-6**: Question timeout 30 min vs longer? **Default: 30 min** (sandbox held, no spend); configurable `code_jobs.question_timeout_seconds` up to 4 h.
