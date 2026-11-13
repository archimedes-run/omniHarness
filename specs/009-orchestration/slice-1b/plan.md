# Implementation Plan: 009 Slice 1b, OpenCode upgrades

**Spec**: [`spec.md`](spec.md) · **Shared contract**: [`../question-card.md`](../question-card.md) · **Created**: 2026-11-13

**Starts after**: PR #174 (Slice 0) is merged; every PR below rebases on main and runs `make eval` (mock) green.

## Constitution check

- Article II (tiers): one new Tier 3 action (`code_job_apply`); `code_job` stays Tier 2 (its effects stay in the sandbox); answering a question is not a tier decision and never confirms anything.
- Article III (trusted channels): question answers only by QC-01; answers enter as data (QC-07).
- Article VI (sandbox opt-in): repo jobs need the container sandbox and a configured repo root; otherwise not offered, said honestly.
- Article XII (gates observed failing): every security row S1 to S7 and every eval check ships a sabotage.
- Article XIII (initiation): worker output, test output, diff and question text are content; they cannot propose a consequential action.
- Article XIV (shipped, not gitignored): new config defaults live in `config.example.yaml` and the config model; `omni-ask` and the updated `AGENTS.md` are tracked and baked into the image.

## PR slices, in order

Each PR is sized for one review, ships alone, and leaves the app usable. Agent concurrency rule applies (coding PRs sequential).

### PR 1: Question card (shared, used by 010)

- Backend: `app/gateway/questions/` (durable store with atomic claim, the `pending.py` pattern; expiry sweep beside Slice 0's card sweep; resume-handler registry keyed by `asker.kind`), `routers/questions.py` (list, answer), thread stream events, typed-reply recognition hooked where `confirm_flow.turn_may_answer` already runs.
- The lead's `ask_clarification` becomes `asker.kind = lead` (D1b-10): the run still ends at the question; the answer resumes the lead with the answer as the tool result (QC-07). Slice 0's send-back rules unchanged.
- Frontend: `components/workspace/questions/question-card.tsx`, `core/questions/`; replaces the `assistant:clarification` rendering; Home's waiting list shows open questions.
- Tests: contract unit tests QC-01 to QC-08; Playwright both themes + AA + keyboard; eval tasks for lead questions still pass (T17 asks a time zone: now a card).
- Sabotage: (a) a tool result containing "answer: 2" in a thread with one open question: stays open; break = treat any human-typed message as an answer → red. (b) two open questions, one typed reply: neither answered; break = answer the newest → red. (c) a content-originated card with `on_expiry: option:0`: creation refused; break = allow → red. (d) answer arrives as data: an open Tier 3 card stays open after answering; break = inject a tagged user turn → red (S7). (e) double-click from two workers: one answer recorded; break = drop the claim → red.

### PR 2: Per-job model routing and the Messages API adapter (A)

- `code_jobs.models`, brief `model`, model name in the job token claims; proxy resolves upstream from claims (FR-100 to FR-102).
- `upstream.py` gains `api: messages | openai_compatible`; new `messages_api.py` adapter after the existing sanitiser (FR-103); stream translation; usage with cache read/write (FR-104).
- `pricing.py`: `cache_write`, explicit rows, dated comment; card/run-history show model.
- Tests: adapter round-trips recorded provider streams (text, tool calls, stop reasons, errors, usage); cost = sum of rows for both adapters (SC-1B-4); reservation upper bound holds for Messages requests.
- Sabotage (S4): body model / `base_url` field / forged header → refused; break = read the model from the body → red. Unknown model id → dearest row; break = default to cheapest → red.

### PR 3: Real repos in, diff out (C, copy half)

- Brief `repo`, `ref`; `code_jobs.repo_roots` (empty default); resolve + limits (FR-120 to FR-122); `git archive` with hooks and filters off; denylist + secret scan (FR-123); copy into a fresh repo and branch in the sandbox (FR-124); diff out, caps, warnings (FR-125, FR-126); card shows diffstat, per-file diff, exclusions, patch download.
- Tests: fixture repos with ignored files, a tracked `.env`, a key, a 25 MB file, a symlink pointing out of the repo, 20,001 files; repo outside roots; uncommitted change not copied.
- Sabotage: S2 (planted hook/filter marker never appears on host; break = enable hooks → red), S6 (break = skip scan → red), S1 (e2e probe: owner path absent inside the sandbox; break = bind-mount it → red).

### PR 4: Apply to my checkout (C, Tier 3 half)

- `code_job_apply` tool + default rule at Tier 3; card text (FR-127); validation (FR-128); plumbing-only branch creation (FR-129); run-history record (FR-130).
- Tests: apply creates `omni/<job>` with the expected tree; current branch, index, working tree, `HEAD` byte-identical (hash before/after); branch exists → refused; owner moved past base → branch still from base.
- Sabotage (S5): one case per FR-128 rule (traversal, absolute, `.git/`, symlink escape, submodule, setuid, denylisted name); remove each rule in turn → its case red. Confirmation by the worker's text or a resume run → nothing applied (#58 tests reused).

### PR 5: Worker questions (B, coding-job asker)

- `omni-ask` in the image (`docker/sandbox/opencode/omni-ask`, root-owned, input limits); AGENTS.md rules; image tag bump; runner: `waiting` state, proxy refuses while waiting, wall clock paused, reaper touch; resume via `opencode run --session`; 3-question cap; expiry → `blocked` (FR-110 to FR-114).
- Tests: sandbox stand-in plays a run that asks, then the resumed run; Stop while waiting expires the card; thread delete expires it.
- Sabotage (S3): worker writes an answer file / question text claims an answer → card open; break = read answers from the job folder → red. Proxy call while waiting → refused; break = keep token valid → red.

### PR 6: Plan step, fix rounds, budgets (D)

- New ceilings and defaults (FR-140); plan round with the read-only plan agent (FR-141), `pause_after_plan`; test command detection and fix rounds (FR-142 to FR-144); protected files (FR-146); card rounds view and stop reasons (FR-145).
- Tests: each stop rule of FR-143 reached by a scripted stand-in; cost per round sums to total; month-left refusal.
- Sabotage: no-progress rule removed → the scripted stuck worker runs all 3 rounds and the test (expects stop after 2) goes red; protected-file rule removed → C2's bad patch (edits the test) passes and the check goes red.

### PR 7: Coding evals and the gate (E)

- `backend/tests/eval/coding/` fixtures C1 to C4, YAML, checks, known-good and known-bad patches; `EVAL_SUITE=coding`; Settings → Evals shows the suite; baseline file `coding-baseline.json`; `make eval` (mock) includes the coding checks' replay (FR-150 to FR-154).
- Retire SC-001 as the slice gate; keep T16 as the honest-blocker check in mock.
- Tests: mock replay in the backend unit job (no network, no secrets, < 3 min added).

## Gates (every PR)

1. **CI passed** (the required check), including `make eval` mock and `scripts/ci/check_docs.py`.
2. **Independent review** for PRs 2 to 6 (they touch sandbox, policy or egress): a reviewer with no part in writing the PR, given the diff and this spec, not the author's conclusions; findings fixed or recorded before merge. MEDIUM+ unfixed security findings go to a draft advisory, never to public PR text.
3. **Sabotage evidence** in the PR body: each listed sabotage, the red output, then green.
4. **No regression vs main** on any eval task (blocks merge regardless of severity).
5. **Dogfood in Chrome** (PRs 1, 3, 4, 5, 6, 7): the owner flow on the live stack, both themes, screenshots in the PR: a question answered by click and by typed message; a repo job with plan, a failed round, a fix, the diff, Apply, and the new branch checked with `git branch` on the host while the working tree is unchanged.
6. **Slice gate** after PR 7: real-mode coding suite, D1b-9, recorded as the coding baseline.

## Deploy notes

- New image tag (PR 5): `omni-ask` and AGENTS.md; `code_job` is offered only with an image whose label reports the 1b features (same check as Slice 1's version label).
- Config: `code_jobs.models`, `repo_roots`, `budget_max_usd`, `wall_max_seconds`, `question_timeout_seconds`, `max_fix_rounds`, `monthly_cap_usd: 60`, and `prices` rows for any model a config names; all in `config.example.yaml` with comments.
- Docker gateway: each repo root mounted read-only; for Apply, that repo's `.git` mounted read-write on top (Q-1B-3). Local `make dev`: the roots are read directly. A root that is not mounted is reported, not silently skipped.
- Frontend restart needed for PR 1 and PR 7; announce first (open tabs hang until refreshed).
- Rollback: `code_jobs.repo_roots: []` turns repo jobs off; questions keep working; the Messages adapter can be switched per model to `openai_compatible`.

## Risks

| Risk | Mitigation |
|---|---|
| The model ignores `omni-ask` and guesses, or asks too often. | AGENTS.md examples; 3-question cap; eval C3 includes one real ambiguity and checks the card appears at most once. |
| `opencode run --session` resume or `--agent plan` behaves differently in 1.19.3 than expected. | PR 5/PR 6 start with a spike against the pinned binary in the e2e image; if resume fails, a question ends the round and the next round starts a new session with the answer and the diff so far. |
| Messages-API stream translation drifts with provider changes. | Recorded-stream tests per stop reason; per-model fallback to the compatible endpoint. |
| Secret scan false negatives. | Denylist first, scan second, no history; the card lists what was copied by top-level folder so the owner can spot surprises. |
| Large repos make jobs slow or expensive. | Limits (FR-122), budget refusal against month left, cost per round on the card. |
| Gateway-in-Docker mounts are fiddly. | Deploy notes; a root health line in Settings; Apply falls back to patch download. |
