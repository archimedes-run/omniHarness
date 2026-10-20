# Feature Specification: Agent Improvement

**Feature Branch**: `007-agent-improvement`

**Created**: 2026-10-20

**Status**: Draft

**Input**: User description: "OmniHarness agents improve themselves using the Harness² method (arXiv:2610.14224, google-research/harness2), adapted for a personal workspace that has real accounts." The user listed eight requirements: a task-level loop, probe safety, signals with no answer key, output as an approved diff, a Lessons store, a v1 scope of scheduled agents, cost budgets, and an Improve tab. All eight are covered below. Method notes, risks of the reference code, licence and dependencies are in [research.md](research.md).

**Roadmap phase (Article IX)**: an extension of 006 Workspace Studio. It sits after 006 Phase 3 (Agent Studio) and Phase 4 (automations run history) for its UI, but its first two slices are backend-only and ship before those phases. See "Order of work" below and research.md R6.

**What this is not**: it is not Harness² as published. It borrows the Propose, Probe, Compose loop and the experience library. It adds two signals the paper does not have (the user's feedback history and honesty checks), replaces the paper's automatic selector with the user's approval, and runs probes that cannot write. research.md R2 and R5 list every difference.

## Order of work

| Slice | What | Needs from 006 |
|---|---|---|
| 1 | Read-only replay harness and the simulated-write wrapper, with its sabotage test | nothing |
| 2 | Agent versions: snapshot, apply, undo, and the locked-surface validator | nothing (agents are already files) |
| 3 | The improvement run: propose, probe, compose, the comparison rule, budgets, Lessons store (API only) | nothing for replay; a scheduled agent needs Phase 3's `schedule` field or Phase 4's rule `agent` field |
| 4 | Feedback signals recorded server-side | 006-A Home dismissals (unmerged branch) for dismissals |
| 5 | Improve and Lessons tabs in Agent Studio | Phase 3 (Agent Studio panel and tabs) and Phase 4 (run history) |
| 6 | Shadow mode and the weekly run | Phase 4 (rule `agent` field and run history) |

Slices 1 and 2 are useful on their own: a "dry run" of any agent that touches no account, and undoable agent edits with a history.

## Terms

- **Agent setup**: everything that decides how an agent behaves. In this feature it is split into **editable surfaces** (FR-004) and **locked surfaces** (FR-005).
- **Version**: a stored snapshot of an agent's setup, with a number, a hash, who made it (user, or an approved proposal) and when.
- **Input**: what one scheduled run starts from: the rule or schedule that fired, the time, the prompt, and the thread context. Stored inputs come from the agent's run history.
- **Probe**: one run of one setup on one input, under the probe wrapper (FR-010). A probe never writes.
- **Baseline**: probes of the agent's current version.
- **Candidate**: a modified setup written by the proposer. Each candidate has a **scope**: "how it works" (procedure, tool use, checking: Harness² "invariant") or "what it knows" (facts and practice for this agent's job: Harness² "domain").
- **Proposal**: the one setup the composer produces from the evidence, or KEEP_CURRENT. It is what the user sees.
- **Improvement run**: one execution of the loop for one agent, from estimate to proposal.
- **Lesson**: an entry in the agent's Lessons store: cue, lesson, evidence, confidence.
- **k**: the number of candidates per scope. The paper writes it as k; its capital K means the number of harness components (research.md R1.1).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Improve a scheduled agent from its own runs (Priority: P1)

The user opens Evening wrap-up in Agent Studio and goes to the Improve tab. It says the agent has 9 stored runs, and that 3 recent ones will be replayed. They press **Improve**. A sheet shows the estimate: 2 candidates (k = 1), 15 probe runs, about 410k tokens, about $1.20, against a per-run budget of $3 and $11.40 left this month. They press Start. The run probes the current setup twice per input, probes one "how it works" and one "what it knows" candidate, composes a proposal, and probes that. Twenty minutes later the tab shows a proposal: two edits to the instructions and one new memory note, each with its evidence. No account was touched.

**Why this priority**: it is the feature. Everything else exists to make this safe, honest and reviewable.

**Independent Test**: through `create_app()` and its lifespan, with a stand-in model and a test agent with stored runs, start an improvement run and check that it produces a proposal or KEEP_CURRENT, with probe records for the baseline, each candidate and the proposal, and that no write tool ran.

**Acceptance Scenarios**:

1. **Given** a scheduled agent with at least one stored input, **When** the user presses Improve, **Then** an estimate is shown (k, the number of inputs, the number of probe runs, tokens and cost) and nothing runs until the user presses Start.
2. **Given** a started run, **When** it finishes, **Then** it has probed the current version at least twice on each input, each candidate once on each input, and the proposal once on each input, all under the probe wrapper.
3. **Given** candidates that edit only editable surfaces, **When** the composer runs, **Then** the proposal contains only edits that pass the comparison rule (FR-020 to FR-029), and each edit lists the probe runs that support it.
4. **Given** no candidate edit has evidence behind it, **When** the run finishes, **Then** the result is "No change proposed" (KEEP_CURRENT), with the reason in words. That is shown as a normal outcome, not a failure.
5. **Given** a candidate that edits a locked surface (a policy tier, an autonomy grant, a confirmation rule, the schedule, the tool list), **When** it is validated, **Then** the edit is dropped before any probe runs, and the run log says which edit was dropped and why.
6. **Given** a candidate whose edit needs a new script or MCP server, **When** the proposal is shown, **Then** the edit is not in the diff. It is listed as a suggestion with a "Start in MCP Suite Build" link, and nothing is built.
7. **Given** a live chat agent with no schedule, **When** its Studio page opens, **Then** the Improve tab says improvement covers scheduled agents only in this version, and the Improve button is absent.

---

### User Story 2 - Probes cannot write (Priority: P1)

The user worries that "running the Morning brief 15 times" means 15 briefs on Telegram, or tasks archived 15 times. It does not. Probes read the user's calendar, mail and repositories for real, because a brief built on fake data proves nothing. Every write a probe tries (a draft, a task update, a message, a calendar change) is recorded and shown in the evidence as "would have done", and never executed. Nothing irreversible is ever executed, and no approval card appears.

**Why this priority**: the workspace has real accounts. Without this, the feature cannot ship at all.

**Independent Test**: the sabotage test (FR-016). A probe of a test agent calls a write tool whose real implementation increments a counter. The counter stays at 0 and a simulated-write record exists. With the wrapper removed, the same test fails.

**Acceptance Scenarios**:

1. **Given** a probe calls a tool classified Tier 1 by an explicit rule, **When** the call is made, **Then** it runs for real and its result is part of the evidence.
2. **Given** a probe calls a Tier 2 tool, **When** the call is made, **Then** the tool does not run, a simulated-write record is stored (tool, arguments, tier, the probe, the time), and the agent receives a result that says the write was recorded and not executed in a test run.
3. **Given** a probe calls a Tier 3 tool, or an unknown tool, **When** the call is made, **Then** it does not run, no pending action is created, no approval card appears anywhere, and a simulated-write record is stored.
4. **Given** a tool classified Tier 1 whose name looks like a write (FR-013), **When** a probe calls it, **Then** it is simulated, not run, and the run report flags the disagreement for the user to fix in the policy rules.
5. **Given** a probe finishes, **When** the user's accounts, ledger, agent memory, pending actions and channels are checked, **Then** nothing in them changed because of the probe.
6. **Given** a probe produces its output, **When** it ends, **Then** the output is not delivered to any channel and does not appear on Home.

---

### User Story 3 - Review, approve, reject and undo (Priority: P2)

On the Improve tab the user sees the proposal as a diff, one card per edit. Each card shows what changed (old and new text side by side), why (the moment in a run that motivated it, in words), and the evidence: which runs, what differed, and a verdict (helped, hurt, no observed effect, confounded). They reject the memory-note edit and approve the rest. The agent's version goes from 4 to 5. A week later the briefs feel worse; on the History list they press **Restore version 4**, and the agent is back.

**Why this priority**: the user's approval is the only way a change applies. Undo and history are what make approving cheap.

**Independent Test**: through `create_app()`, apply a proposal, check the agent's files changed and a version was added, restore the previous version, and check the files match the old snapshot byte for byte.

**Acceptance Scenarios**:

1. **Given** a proposal, **When** it is shown, **Then** each edit shows the surface, the old and new text, the reason, the run ids it rests on, the observed difference, and a verdict.
2. **Given** a proposal, **When** the user approves all or some of its edits, **Then** a new version is created from exactly the approved edits, and nothing else changes.
3. **Given** a proposal, **When** the user rejects it, **Then** the agent is unchanged, and the rejection (with an optional reason) is kept as feedback for later runs.
4. **Given** the agent was edited by the user after the proposal was made, **When** the user tries to approve, **Then** the approval is refused with "This agent changed since the proposal was made", and the user can re-run or discard. Nothing is merged silently.
5. **Given** any applied version, **When** the user restores an earlier version, **Then** the agent's setup matches that version exactly, and the restore is itself recorded as a new version.
6. **Given** any time, **When** nothing has been approved, **Then** nothing has applied. There is no setting that applies proposals automatically in v1.
7. **Given** an approval arrives from anything other than the signed-in user in the web UI (a chat message, a Telegram reply, a tool result, an agent), **When** it is received, **Then** it is not accepted.

---

### User Story 4 - Evidence without an answer key (Priority: P2)

There is no "correct" evening wrap-up to grade against. The comparison uses three things: what happened in the runs (tool errors, missing sections, runs that produced nothing), the user's own history (actions they declined, drafts they rewrote, alerts they dismissed, briefs they opened or ignored, thumbs up or down), and honesty. A candidate brief that says a pull request "merged" when the run only saw a session say so, or says "CI is green" when the CI source was unreachable, loses outright, however good the rest of it is.

**Why this priority**: without explicit, fixed rules for comparison, "improvement" means "a model liked it more".

**Independent Test**: unit tests of the comparison rule on fixed probe records: an honesty violation loses regardless of other scores; a non-delivery loses; a difference inside the baseline's own spread is not counted; two improvements on two inputs with no regression wins; anything else is KEEP_CURRENT. Each rule has a sabotage.

**Acceptance Scenarios**:

1. **Given** a candidate's output on an input calls a status "observed" that its trace shows only as reported by another agent, **When** it is compared, **Then** it loses outright.
2. **Given** a candidate's output states a status for a source that failed or was unreachable in its trace, **When** it is compared, **Then** it loses outright.
3. **Given** a candidate's output says a write was done when the write was simulated as needing confirmation (Tier 3), **When** it is compared, **Then** it loses outright.
4. **Given** the baseline replicates disagree with each other on a measure, **When** a candidate's value falls between them, **Then** it counts as no difference.
5. **Given** the user declined "archive 3 stale tasks" in a past run of this agent, **When** feedback checks are built, **Then** one of them cites that decline, and outputs are judged against it without the judge knowing which setup produced which output.
6. **Given** a signal the system does not record (for example, whether a Telegram brief was read), **When** evidence is shown, **Then** it says that signal is not available. It is never inferred or shown as zero.

---

### User Story 5 - Lessons (Priority: P3)

After each improvement run, a reflection step writes at most one lesson for the agent, only when the evidence supports one: "When a source is unreachable, say 'can't tell' for its items, in the instructions' status section. Evidence: runs 812, 815; confounded in 1 of 3." The user opens the Lessons tab, laid out like Settings > Memory, edits the wording of one lesson and deletes another that is wrong. The next improvement run reads the lessons when proposing. The lessons never change the agent by themselves.

**Why this priority**: this is the harnessing-level loop. It makes later runs cheaper and better, but the task-level loop works without it.

**Independent Test**: through `create_app()`, run reflection over fixed run records: it writes one lesson with cue, lesson, evidence and confidence, or none when evidence is thin. Edit and delete via the API. Start the next run and check the proposer's input contains the edited lesson and not the deleted one, and that the agent's setup did not change.

**Acceptance Scenarios**:

1. **Given** an improvement run whose evidence rows are all "confounded" or "no observed effect", **When** reflection runs, **Then** no lesson is written, and the run log says "No lesson: evidence too thin".
2. **Given** the Lessons tab, **When** the user edits or deletes a lesson, **Then** the change is saved and used by the next run.
3. **Given** any lesson, **When** a proposal is made, **Then** the lesson can only shape what is proposed. It never applies an edit, never skips approval, and never unlocks a locked surface.
4. **Given** a lesson, **When** it is shown, **Then** it says whether it was written by reflection or by the user, when, and which runs it rests on.

---

### User Story 6 - Cost before and after (Priority: P2)

In Settings the user sets $3 per improvement run and $15 per month. An improvement run that would cost $4.10 by estimate cannot start; the sheet offers k = 1 or fewer inputs to fit. A run that reaches $3 mid-way stops, says "Stopped at your $3 run budget after 11 of 15 probes", and shows what it found. The month's total is shown on the Improve tab.

**Why this priority**: each probe is a full agent run. Without a hard stop, a few runs can cost more than the agent saves.

**Independent Test**: with a stand-in model that reports fixed token counts and a known price table, check the estimate, check the run stops at the budget with the right message, and check the actual cost recorded equals the sum of calls made.

**Acceptance Scenarios**:

1. **Given** an estimate above the per-run or the remaining monthly budget, **When** the user tries to start, **Then** the run cannot start, and the sheet says which budget it exceeds and by how much.
2. **Given** a run in progress, **When** the next call would take the actual cost over either budget, **Then** that call is not made, the run stops, and the result says it stopped at the budget and what it completed.
3. **Given** a run that stopped at the budget, **When** the result is shown, **Then** a proposal is shown only if the comparison rule is met on the probes that completed; otherwise the result is KEEP_CURRENT with the reason "stopped before enough evidence".
4. **Given** a finished run, **When** its result is shown, **Then** it shows the estimated and the actual cost, tokens and number of runs side by side.
5. **Given** the model's price is not known, **When** the estimate is made, **Then** it shows tokens only and says the cost cannot be estimated, and the run cannot start until a price is set for that model (in Settings).

---

### User Story 7 - Shadow mode and the weekly run (Priority: P3)

The user turns on "Improve weekly" for the Morning brief, with shadow mode. Each morning that week, the real brief runs and is delivered exactly as before. Alongside it, the candidates run on the same input, with the same wrapper, and are never delivered. On Sunday the Improve tab has a proposal built from five days of live inputs.

**Why this priority**: replay re-runs old inputs against today's data. Shadow mode compares on the input the agent actually got, at the time it got it, which is closer to the paper's "matched conditions".

**Independent Test**: through the trigger engine (`build_production_loop`) with a cron rule naming a test agent and shadow mode on: the firing delivers once, the shadow probes exist, none of them delivers or creates a pending action, and the firing's outcome and timing are unchanged.

**Acceptance Scenarios**:

1. **Given** shadow mode is on, **When** the agent's rule fires, **Then** the real run is delivered exactly as without shadow mode, and the shadow probes start only after it is delivered or held.
2. **Given** shadow probes, **When** they finish, **Then** none is delivered, none appears on Home, and none creates a pending action.
3. **Given** the weekly run is on, **When** it is due and its estimate fits the budgets, **Then** it runs and leaves a proposal or KEEP_CURRENT on the Improve tab. **When** the estimate does not fit, **Then** it does not run, and the Improve tab says so.
4. **Given** quiet hours, **When** a weekly result is ready, **Then** no notification is sent during quiet hours (Article VII); the result waits on the Improve tab.

---

### Edge Cases

- **No stored inputs** (a new agent, or run events kept only in memory): Improve says there is nothing to replay yet and offers shadow mode. It does not invent inputs.
- **Stored input incomplete** (run events truncated at the size limit): that input is skipped and listed as skipped with the reason.
- **Source data changed since the stored run**: replay reads today's data. The baseline is re-run in the same improvement run, so baseline and candidates see the same data. The evidence panel says "replayed on today's data".
- **A read tool fails during a probe**: recorded as a tool error in that probe. If it fails in the baseline and the candidate alike, it is not counted against either.
- **A probe exceeds its turn or time cap**: it ends, counts as "did not deliver", and that setup cannot win on that input.
- **The agent is deleted while a run is in progress**: the run stops; the result says the agent is gone.
- **Two improvement runs for one agent**: refused; one at a time per agent.
- **A proposal whose base version is no longer current** (user edited, or another proposal was approved): cannot be approved (US3 scenario 4).
- **The proposer returns invalid edits twice**: that candidate falls back to the current setup and is recorded as such, as in the reference code (research.md R3, last paragraph).
- **A Tier 1 read with a side effect** (for example a mail read that marks the message as read): see Open Question 6.
- **A lesson that names a locked surface** ("raise the archive grant"): kept as text, but it cannot cause a locked edit; the validator drops any such edit.

## Requirements *(mandatory)*

### Scope and surfaces

- **FR-001**: v1 MUST improve only agents that run on a schedule or a recurring trigger (for example Morning brief, Evening wrap-up). Live chat agents are out of scope; their Improve tab says so (US1 scenario 7).
- **FR-002**: An improvement run MUST start only from the **Improve** button (by the signed-in user in the web UI) or from the agent's optional **weekly run** (FR-071). No agent tool, chat message, tool result or automation other than the weekly run may start one.
- **FR-003**: Inputs MUST come from the agent's own run history, either **replayed** (FR-003a) or the **next live input in shadow mode** (FR-070).
- **FR-003a**: **Replay** re-runs a stored input: the same trigger, prompt and time context, with today's data from real Tier 1 reads. An input whose stored record is incomplete is skipped with its reason.
- **FR-004**: The editable surfaces are an **allow-list**, and only these may be changed by a proposal:
  - **instructions** (the agent's SOUL.md, and the prompt of the rule that runs it, see Open Question 3);
  - **tool guidance** (a per-agent text section on how to use the tools it already has);
  - **skills** (which of the existing skills this agent uses, and new agent-scoped skills; see Open Question 4 on shared skills);
  - **memory notes** (facts in the agent's own memory);
  - **subagent setup** (the instructions of subagents this agent calls, see Open Question 4).
- **FR-005**: Everything not in FR-004 is **locked**, including: policy tiers and rules, autonomy grants, confirmation rules and thresholds, the agent's tool list and integrations, its model, schedule, delivery channel, projects and name. A validator MUST compare each candidate and the proposal against the current version and drop any edit to a locked surface before probing. A candidate whose edits are invalid gets one retry with the validator's message, then falls back to the current setup.
- **FR-006**: A proposal MUST NOT contain new executable code (scripts, plugins, hooks, MCP servers). Where the evidence argues for one, the proposal lists it as a suggestion that links to **MCP Suite → Build**, the existing describe, build, test and approve flow. Nothing is built from the Improve tab.
- **FR-007**: Improver sessions (proposer, composer, feedback judge, honesty judge, reflector) MUST be model calls with **no tools**. Their evidence is passed as data, marked as data (Article III). They cannot run code, read files outside the evidence they are given, or reach the network.

### Probe safety

- **FR-010**: Every probe MUST run through the agent's production runtime with the **same tool registry** the agent gets in a scheduled run (`get_available_tools` and the same middleware chain), wrapped by a **probe wrapper** that is the outermost tool-call wrapper.
- **FR-011**: The probe wrapper MUST classify each call with the policy engine's own classifier and rules (the same function and the same tracked rules file production uses, never a copy).
- **FR-012**: A call MUST run for real only when it is classified **Tier 1 by an explicit rule** in the tracked rules (not by a fallback) AND it passes FR-013. Every other call is **simulated**: it is recorded and not executed. That includes all Tier 2, all Tier 3, and every unknown tool. Tier 3 is never executed in a probe under any setting.
- **FR-013**: A Tier 1 call whose tool name matches the tracked write-verb list (create, update, delete, remove, send, post, archive, move, write, apply, set, add, insert, patch, put, upload, share, invite, and their variants) MUST be simulated and flagged in the run report as a classification disagreement.
- **FR-014**: A simulated call MUST return to the agent a result that says, in words, that the write was recorded and not executed because this is a test run. It MUST NOT create a pending action, show an approval card, write to the disclosure ledger, or count against a standing grant.
- **FR-015**: Probes MUST NOT change the agent's persistent state or the user's data by any other path: memory updates, ledger writes, skill edits, channel delivery, Home items, alerts and notifications are disabled for probe runs. Probe records live only in the improvement run's own store.
- **FR-016**: **Sabotage test (required)**: a probe of a test agent calls a write tool whose real implementation increments a counter. The gate asserts the counter is 0 and a simulated-write record exists. The sabotage removes the probe wrapper (and, separately, makes the classifier return Tier 1 for that tool without an explicit rule); in each case the gate MUST fail. Both sabotages are run once and their failure recorded, following Article XII (confirm the failure is the gate firing, not an upstream error).
- **FR-017**: Each probe MUST have a turn cap and a time cap (defaults in plan.md). A probe that hits a cap ends and counts as "did not deliver".

### Comparison rule (signals with no answer key)

This is the exact rule. It is deterministic given the probe records and the judges' verdicts. The judges are the only model-based parts, and each is blind to which setup produced the output it judges.

- **FR-020**: **Runs per improvement run.** For M inputs (default 3, most recent first): the current version is probed **R = 2** times per input (the **baseline replicates**); each of the **2k** candidates (k per scope, default k = 1) once per input; the **proposal** once per input. Total probes = M × (R + 2k + 1). Default: 3 × 5 = 15.
- **FR-021**: **Step 1, validity.** A setup is discarded if it edits a locked surface (FR-005), contains executable code (FR-006), or fails the initiation check (FR-031).
- **FR-022**: **Step 2, safety.** If any probe in the run executed a call that FR-012 says must be simulated, the whole improvement run is aborted, no proposal is shown, and the user is told this is a defect. (This should be impossible; the check proves it.)
- **FR-023**: **Step 3, honesty: loses outright.** An honesty check runs on every probe's output against that probe's own trace. A violation is any of:
  - **H1** a status stated as observed that the trace shows only as reported (by another agent, a session, a message) or inferred;
  - **H2** a status stated for a source whose read failed, timed out or was unreachable in that probe (a can't-tell collapsed into a value);
  - **H3** a write stated as done when, in that probe, it was simulated as Tier 3 (it would have waited for confirmation) or was never attempted;
  - **H4** a number, date, name or identifier in the output that appears in no tool result of that probe and is not in the instructions.

  A setup **loses outright** if, on any input, it has a violation of a kind (H1 to H4) that **neither** baseline replicate on that input has. No other signal can outweigh this. The checks are deterministic where the output is structured, and otherwise judged per claim by a model that sees the output and the trace and answers violation / no violation / can't tell. "Can't tell" is not a violation; it is shown to the user next to the claim.
- **FR-024**: **Step 4, delivery.** A setup loses if, on any input where at least one baseline replicate delivered an output, it delivered none (empty, cap hit, or error).
- **FR-025**: **Step 5, execution evidence.** Per input, these measures are read from the trace: tool errors, repeated failing calls, required sections missing (sections the current instructions require), turns, and tokens. For each measure and input, the **noise band** is the range between the two baseline replicates. A setup **improves** a measure on an input when its value is outside the band in the better direction, and **regresses** when outside in the worse direction. A token increase of up to 20% over the band's top is not a regression (default; the cost is shown anyway).
- **FR-026**: **Step 6, feedback evidence.** From this agent's feedback history (FR-040), **feedback checks** are built: each is one yes/no question about an output, and each cites the feedback event(s) it comes from (for example: "Does it propose archiving a task that had activity in the last two days? (declined on 14 Oct, run 790)"). For each input, the outputs of both baseline replicates and the setup under test are shuffled and anonymized, and a judge answers each check for each output: pass, fail or can't tell. On an input, a check **improves** when the setup passes and both baseline replicates fail, and **regresses** when the setup fails and both replicates pass. Can't tell counts as neither.
- **FR-027**: **Decision.** A setup that survived steps 1 to 4 is **backed by evidence** when it has **no regression** (FR-025, FR-026) on any input, **and** at least **two improvements** in total, observed on **at least two different inputs**. Otherwise it is not.
- **FR-028**: **Composition.** The composer sees all candidates that survived steps 1 to 4, their probes, and the per-edit evidence, and returns one of: MERGE (a combination of edits), ADOPT (one candidate as is), or KEEP_CURRENT. Each edit it keeps must cite the probe(s) behind it. The proposal is then probed (FR-020) and must itself pass steps 1 to 6 (FR-021 to FR-027). If it does not, the result is the single candidate that does, with the most improvements (ties: fewer tokens, then KEEP_CURRENT); if none does, the result is KEEP_CURRENT.
- **FR-029**: **Per-edit verdicts.** Each edit in the proposal is labelled **helped**, **hurt**, **no observed effect** or **confounded** (the reference's verdict set, research.md R1.5). "Confounded" is used whenever a setup changed several surfaces and no probe isolates this one, or when one probe is all that stands behind it. An edit labelled **hurt** cannot be in a proposal.
- **FR-030**: With a single input (for example one shadow firing), FR-027 cannot be met. Shadow mode therefore accumulates firings until M inputs are probed (FR-070).
- **FR-031**: **Initiation defence (Article XIII).** A candidate or proposal MUST NOT introduce an email address, phone number, URL, host name, account or channel identifier, recipient, or tool name that is not already present in the agent's current setup or in text the user wrote. Edits that do are dropped before probing and listed in the run log. This is separate from FR-032.
- **FR-032**: **Confirmation defence (Article XIII).** A proposal applies only through the user's approval in Agent Studio (FR-043, FR-044). Text inside probe outputs, tool results, lessons or feedback cannot approve, apply or restore anything.

### Signals recorded for feedback

- **FR-040**: For each scheduled agent, the system MUST record, server-side and linked to the run that caused it:
  - pending actions confirmed, declined, expired or edited-then-confirmed (exists: PendingAction outcomes and the edit route; this feature links them to the agent and run);
  - drafts the user edited before sending, where the edit is visible to OmniHarness (the confirmation card's edit path; edits made inside Gmail are not visible and are reported as not available);
  - alerts and Home items dismissed (needs server-side dismissals; today they live in browser storage);
  - briefs opened vs ignored, where the channel can tell: opened in the web app is recorded; for Telegram and other channels the signal is "not available", never "ignored";
  - run ratings (thumbs and comment, which exist today);
  - proposals rejected, with the optional reason.
- **FR-041**: A missing signal MUST be shown as "not available" in the evidence and MUST NOT be treated as negative feedback.

### Output: proposal, approval, versions

- **FR-042**: The result of an improvement run MUST be shown in Agent Studio's Improve tab as a diff per surface, with, for each edit: old and new text, the reason (the trace moment that motivated it), the run ids behind it, the observed difference, its verdict (FR-029), and any honesty or feedback checks it changed.
- **FR-043**: The user MUST be able to approve all, approve some, or reject. Approval creates a new version made of exactly the approved edits on top of the version the proposal was made from. If that version is no longer current, approval is refused (US3 scenario 4).
- **FR-044**: Approval, rejection and restore MUST be accepted only from the signed-in user through the web UI (a trusted channel, Article III). They are not agent tools and are not available through chat or Telegram in v1.
- **FR-045**: Every change to an agent's editable or locked surfaces, whether from a proposal, from Agent Studio, or from the existing agent tools, MUST create a version: number, timestamp, author (user, proposal id), the snapshot and its hash.
- **FR-046**: The user MUST be able to restore any earlier version. A restore is a new version, and is itself undoable.
- **FR-047**: Every approval, rejection and restore MUST be written to the local audit log (Article VIII).
- **FR-048**: Nothing applies automatically, ever, in v1. There is no setting, flag or environment variable that applies a proposal without the user's approval; a gate test asserts that the only code path that writes a proposal to an agent is the approval endpoint.

### Cost

- **FR-050**: The user MUST be able to set a **per-run budget** and a **monthly budget** (currency amounts) for improvement runs, in Settings. Defaults are in Open Question 7.
- **FR-051**: Before a run, the system MUST show an estimate: k, M, the number of probe runs, the number of improver calls, tokens, and cost. Tokens are estimated from the agent's recent runs (the run records' token totals); cost from a tracked price table per model, which the user can override.
- **FR-052**: A run whose estimate exceeds either budget MUST NOT start. The sheet says which budget and by how much, and offers smaller k or M.
- **FR-053**: During a run, before each model call, the system MUST check that the actual cost so far plus that call's maximum cost stays within both budgets. If not, the call is not made and the run stops with "Stopped at your <budget> after <n> of <N> probes".
- **FR-054**: After a run, the system MUST show the actual cost, tokens and runs next to the estimate. Calls served from a cache are counted and shown separately, not as zero-cost probes.
- **FR-055**: The month's spend on improvement runs MUST be visible on the Improve tab and in Settings.
- **FR-056**: Token counting MUST be on for probe and improver calls even when the global token-usage setting is off.

### Lessons (harnessing-level loop)

- **FR-061**: Each agent has a **Lessons** store. After each improvement run (including KEEP_CURRENT), a reflection step writes per-edit evidence rows (FR-029) and **at most one** lesson with **cue**, **lesson**, **evidence** and **confidence**. It writes no lesson ("No lesson: evidence too thin") when the rows rest only on confounded or no-effect verdicts.
- **FR-062**: The Lessons tab MUST let the user view, add, edit and delete lessons, with the layout and interaction of Settings > Memory (cards, Edit, Add, "updated <time>", and "may be out of date" for old entries).
- **FR-063**: Lessons MUST be given to the proposer and composer as data. A lesson cannot apply an edit, cannot skip approval, cannot unlock a locked surface, and cannot override the comparison rule.
- **FR-064**: Each lesson MUST show its author (reflection or user), its time, and the runs it rests on.

### Shadow mode and weekly runs

- **FR-070**: In **shadow mode**, when the agent's rule fires, the real run proceeds and is delivered exactly as without shadow mode. After it is delivered or held, the baseline replicates and the candidates run on the same input under the probe wrapper. Shadow probes are never delivered. Shadow mode collects inputs until M are probed, then composes.
- **FR-071**: The user MAY turn on an optional **weekly** improvement run per agent. It runs only if its estimate fits both budgets; otherwise it is skipped and the Improve tab says why.
- **FR-072**: Shadow and weekly runs MUST respect quiet hours and must not interrupt an exchange in progress (Article VII). A ready proposal is a quiet item on the Improve tab; it is not pushed to a channel in v1.
- **FR-073**: Shadow probes MUST NOT delay, change or reorder the real firing, and MUST NOT run on the trigger engine's event loop (see AUDIT-2026-10 T-6).

### Agent Studio UI

- **FR-080**: Agent Studio's tabs become: Overview · Instructions · Tools and skills · Autonomy · Schedule · **Improve** · **Lessons**, drawn in the Graphite look (006 tokens, one solid primary button per screen).
- **FR-081**: The **Improve** tab shows: the agent's version and its history (with Restore); the Improve button; budgets and the month's spend; the weekly and shadow switches; runs in progress (with Stop); and the latest result (proposal or KEEP_CURRENT) with its evidence.
- **FR-082**: Honesty wording (006 FR-008): observed, reported and inferred are said in words; "not available" and "can't tell" are never shown as zero or empty.
- **FR-083**: Every new string exists in en-US and zh-CN (006 FR-010).

### Policy statement (constitution workflow rule)

- **FR-090**: This feature adds **no agent tools**. Its new actions are gateway endpoints used by the signed-in user: start or stop an improvement run, approve, reject, restore, and edit lessons and budgets. None is reachable from the agent runtime. In probes, every existing tool keeps its tier, and FR-012 decides what runs.

### Key Entities

- **Agent version**: agent, number, snapshot of all surfaces (editable and locked), hash, author (user or proposal), created at, restored-from (optional).
- **Improvement run**: agent, base version, mode (replay or shadow), k, M, R, estimate (runs, tokens, cost), actual (runs, tokens, cost, cached calls), budgets at start, status (estimating, running, stopped-at-budget, done, aborted), result (proposal id or KEEP_CURRENT with reason).
- **Candidate**: run, scope (how it works / what it knows), the edits, validator outcome, fallback flag, proposer notes.
- **Probe**: run, setup (baseline replicate n, candidate id, or proposal), input, trace reference, output, delivered flag, measures, honesty verdicts, caps hit.
- **Simulated write**: probe, tool, arguments, tier, the rule that classified it, the reason it was simulated (tier, unknown, write-verb disagreement), time.
- **Feedback event**: agent, run, kind (confirmed, declined, expired, edited, dismissed, opened, rating, proposal rejected), detail, time, source.
- **Feedback check**: run, question, cited feedback events.
- **Proposal**: run, base version, outcome (MERGE, ADOPT, KEEP_CURRENT), edits (surface, old, new, reason, evidence rows, verdict), MCP Build suggestions, status (open, approved in part, approved, rejected, stale).
- **Lesson**: agent, cue, lesson, evidence (run ids and rows), confidence, author, created and updated times.
- **Improvement budget**: user, per-run amount, monthly amount, price overrides.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In the sabotage suite, 0 real executions of non-Tier-1 calls across all probe tests, and each of the two FR-016 sabotages makes the gate fail (recorded once, with the failing assertion named).
- **SC-002**: After any improvement run in the integration test, the user's ledger, agent memory, pending actions, channel deliveries and Home items are byte-identical to before.
- **SC-003**: Every proposal edit shown has at least one cited probe id; a gate test fails if one does not.
- **SC-004**: Each comparison rule (FR-022 to FR-027) has a unit test and a sabotage that makes it fail.
- **SC-005**: Restoring any version reproduces its snapshot byte for byte (hash match) in 100% of tests.
- **SC-006**: The actual cost of a run never exceeds the per-run budget by more than one call's maximum cost, and a run never starts when its estimate exceeds either budget.
- **SC-007**: On a stand-in model with fixed token counts, the estimate is within 10% of the actual tokens.
- **SC-008**: Shadow mode leaves the real firing's outcome, delivery count and delivery time unchanged (integration test through `build_production_loop`).
- **SC-009**: The only code path that writes a proposal to an agent is the approval endpoint (gate test, with a sabotage that adds a second path).

## Assumptions

- Scheduled agents exist as agents with a schedule (006 Phase 3) or as rules that name an agent (006 Phase 4). Until then, the backend slices are tested with a test agent driven by a cron rule.
- Run events are persisted (`run_events.backend` is `db` or `jsonl`). With the default `memory` backend nothing is stored, so replay has nothing to read; Improve says so.
- A single user per workspace; budgets are per user.
- The configured models are used for probes (the agent's own model) and for the improver (Open Question 2). No Vertex or other new provider is required.
- The paper's numbers are benchmark results with judges; nothing here assumes the same gains for personal agents.

## Out of Scope (v1)

- Live chat agents; the sequential (depth) mode of Harness²; automatic application of any change; new code from the Improve tab; cross-agent lessons; improving the improver's own prompts automatically.

## Clarifications

None yet. The questions below need the user's answers. Each has a default the plan uses until answered.

## Open Questions

1. **"K candidates".** The paper probes k candidates **per scope** (k "how it works" plus k "what it knows", so 2k), and its capital K means the eight components (research.md R5 item 1). **Default:** the user sets k (1 to 3, default 1), and the estimate shows 2k candidates. Is that the meaning you intended, or did you mean K candidates in total?
2. **Improver model.** Which model writes candidates, composes, judges and reflects? **Default:** the strongest model configured in OmniHarness, chosen in Settings, separate from the agent's own model, with its cost in the estimate. The paper's evidence that the same model can improve itself is Figure 8.
3. **The rule's prompt.** A scheduled run's text comes partly from the agent's instructions and partly from the trigger rule's prompt. **Default:** the prompt of a rule that names this agent counts as part of "instructions" and is editable; the rule's schedule, destination and switches stay locked. Agree?
4. **Shared skills and subagents.** Skills and subagent definitions are global today; editing one changes every agent that uses it. **Default:** a proposal may change which skills this agent uses and may add new skills scoped to this agent, but may not edit a shared skill or a shared subagent; it can only suggest that edit. Agree?
5. **Thresholds.** The defaults are M = 3 inputs, R = 2 baseline replicates, "two improvements on two inputs", and a 20% token tolerance. Probes cost real money, so these trade cost for confidence. Accept these defaults?
6. **Reads with side effects.** Some reads change state on the provider (for example marking a message as read, or "seen" receipts). **Default:** a tool is treated as a read only when the rules say Tier 1 and its name is not on the write-verb list; reads known to change state are marked Tier 2 in the tracked rules, so probes simulate them. Do you know of other side-effecting reads in your connectors?
7. **Budget defaults.** **Default:** $2 per run and $10 per month until you change them, with improvement runs disabled when no price is known for a model. What amounts do you want?
8. **Lessons written by reflection.** **Default:** reflection adds lessons directly (marked "written by reflection"), because lessons cannot change the agent on their own. Would you rather approve each new lesson first?
9. **Brief "opened" signal.** Only web-app opens can be observed. **Default:** Telegram reads are "not available". Do you want a "Got it" button on Telegram briefs to make that signal observable?
10. **Version history for non-proposal edits.** FR-045 versions every change to an agent, including edits made in Agent Studio and by the existing setup/update agent tools. This is broader than this feature. **Default:** yes, all changes, because undo must work whatever made the change. Agree?
