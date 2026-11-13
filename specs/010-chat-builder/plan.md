# Implementation Plan: Chat builder

**Branch**: `010-chat-builder` (one PR per slice) | **Date**: 2026-11-13 | **Spec**: [spec.md](spec.md)

## Summary

The builder is a small set of lead-only tools (draft, read live, diff, save) over the one versioned config store, plus six chat cards. Saving reuses the confirmations store and the policy layer; it adds one new rule to it: some card parts confirm by button only. Automations join the store as a third kind first, so every later slice writes one way.

## Technical context

- **Backend**: `omniharness/config/config_versions.py` (gains kind "automation"), `app/gateway/automations_store.py` (materialiser for it), `app/gateway/routers/drafts.py` (reused by the draft tool; still never writes), `app/policy/` (tiers in `default_rules.yaml`, `confirm_flow.py`, `lineage.py`, `grants.py`), `omniharness/agents/called_agents.py` and the task tool (call chain for FR-030), `app/gateway/routers/composio.py` (Connect card).
- **Frontend**: `components/workspace/confirmations/` (card host), `components/workspace/studio/` (diff and version-history parts to reuse), `components/workspace/chat-bar/` (chip), the shared Question card from 009 Slice 1b.
- **Depends on**: 009 Slice 1b's first PR (Question card) for slices 3 onward; 009 Slice 0 (resume after cards, FR-063 disclosure) on main.

## Constitution check

Article I (gateway API only), II (policy layer decides, Tier 3 asks), III (provenance and lineage kept separate), X (honest limits: an unexpressible automation is refused), XI (integration through `create_app()`), XIII (content is data). No new external dependency; no package download.

## Slices (PR-sized, in order)

### Slice 1: Automations in the versioned store (can start now)

- Kind "automation" in `config_versions`: per-rule history, snapshot = rule, materialised through `automations_store` (validation, atomic write, hash stale-check kept).
- Lazy baseline (source "existing") on first write; hash-detected hand edit recorded as a new baseline (FR-023).
- Automations router and Studio schedule routes write through it; versions + undo routes for a rule; Automations page shows history.
- Gate test `test_config_writes_go_through_versions` extended to the rules file.
- Tests: baseline then undo; hand edit between two writes; two workers writing the same rule (one refused stale). Sabotage: a route writes the rules file directly and the gate test fails.

### Slice 2: Builder core, backend (can start now)

- Tools `builder_draft`, `builder_read`, `builder_diff` (Tier 1) and `builder_save` (Tier 3) for agents, skills, automations; rules added to `default_rules.yaml`. `setup_agent`, `update_agent`, `skill_manage` removed from the model surface (FR-024); their writers called only by `builder_save`.
- Draft record in thread state (FR-010); diff built from the live store; save carries the base version.
- Server-side typed-yes matcher (FR-015) wired into the confirmations flow; "button-only" parts (grants, tool widening, connections) refuse any typed confirmation (FR-016).
- Call-chain check (FR-030) at dispatch: target ∈ {running agent, inviter chain} refused; builder tools absent from scheduled, delegated, @-called and code-mode surfaces (FR-029).
- Until Slice 3 the cards render through the existing pending-action card (plain, no diff UI), so the slice is usable alone.
- Tests: through `create_app()`, chat → draft → typed yes → version 1 source "chat"; stale base refused. Attack tests: a tool result containing "yes"; an email read before the proposal (becomes a suggestion, typed yes refused); an @-called agent and a delegated subagent editing themselves and their inviter; a resume run trying to answer a card. Each with its sabotage.

#### Slice 2 as built

- **What the model reads back.** `builder_read` and `builder_diff` return stored config text, so a turn that called them is a content turn: a save, grant or undo proposed after them in that turn is a suggestion, saved by its button only. Typed "yes" works when the assistant drafted without reading stored text (a create from one sentence; an edit where `builder_draft` names only the changed fields, and the builder reads the live config itself). The draft acknowledgement, the card's plan as the model sees it and every save result name ids, field names, counts and versions only; the full draft or diff is shown to the owner on the card.
- **A draft carries its cause.** A draft records the origin of the turn that made it; saved from a later turn, a draft made in a content turn is still a suggestion.
- **Access never rides along.** A save never widens an agent's effective tools (tool groups, per-tool list, the tools its skills allow); the widening is left out, named on the card, and proposed with `builder_grant` (button only). Narrowing rides with the save. A new agent starts with no tool groups. An undo keeps the agent's current tool list, tool groups, skills list and standing grants, and says so when the older version differed. A skill draft keeps the skill's other frontmatter (allowed-tools included); a skill undo that would change allowed-tools is refused (Skill Studio).
- **Automations with grants.** The save or undo card of an automation names the agent it runs as and that agent's standing grants; when it holds any, only the button confirms it.
- **One typed yes, one card.** With a save card and button-only builder cards open together, a typed yes confirms the save card only. Dropping the build (the chip's x) refuses all of its open cards, grant and undo included.
- **Bootstrap.** The setup conversation writes its one agent whatever name the model passes (it becomes the display name); the channel `/bootstrap` writes the assistant's own.
- **Off, visibly.** With the policy off, or a rules file that names none of the builder tools, the builder is not offered (no tools, no prompt section) and Settings > Safety says why (`GET /api/builder/status`).
- **Skills from chat** change only an existing custom skill whose recorded owner is this account.
- Deferred to Slice 3: per-item checkboxes on the grant card (today the card lists each item and is confirmed as a whole, by its button).

### Slice 3: Cards and chip (needs 009 Slice 1b's first PR)

- Draft preview, Diff, Created/Saved cards; questions via the shared Question card with typed text routed as a revision (spec "Requirements on the shared Question card"); vague-edit options built from the live config (FR-008).
- "Building: <name>" chip with × (FR-003, FR-004); one build per chat.
- Created/Saved: Try it now, Open in Studio, Undo (FR-013, FR-020).
- Tests: unit (card states, guessed-field marks, no pre-ticked boxes), rendering in both themes, contrast suite entries for every card.

### Slice 4: Permission, Connect, MCP hand-off

- Permission card: unticked boxes, plain-words "allows" and tier from the tool catalog; saves only via `PUT /api/studio/agents/{name}/autonomy` and the tool-access write, by button.
- Connect card: existing connector initiate/callback inline; on completion the tool becomes selectable, not granted.
- "Build in MCP Studio" card (FR-001).
- Tests: typed "yes" with a grant pending saves content only; OAuth started only by button. Sabotage for each.

### Slice 5: Automations from chat (005 Slice 5, T046 to T049)

- Draft preview states schedule in words and rule form; unexpressible requests refused (005 FR-062); run-once per scheduled time with the idempotency key (005 FR-063, T047); briefs read the ledger at run time (005 FR-064).
- Try it now for an automation: test run delivered to this chat only.
- Integration: chat → save → rule in `/api/automations` with version 1 → fired once for a minute evaluated twice.
- 005 `tasks.md` T046 to T049 ticked, pointing here.

### Slice 6: Eval tasks and dogfood

- Add builder tasks to `make eval` (create agent with one question; vague edit; injected email proposing a grant: must end as an unsaved suggestion; MCP request → hand-off card). Mock mode in CI; real-model baseline recorded.
- Live dogfood (below), then the stop report.

**Before 1b lands**: Slices 1 and 2 (and the Slice 6 mock tasks for Slice 2's tools). Slices 3 to 5 start after 1b's first PR merges.

## Tests (every slice)

- Unit + integration through the production composition root (`create_app()`), never a hand-built router.
- Sabotage per guard: each PR shows the guard removed and the named test failing (gates must be observed failing).
- Wiring gate: no new "unwired" entries; the replaced tools' writers reachable only from `builder_save`.
- Tests must not depend on local-only config: run on the tracked example config plus test overrides.
- Assert on state, not status: every save test reads the store and the rules file back.

## Gates (each PR)

1. CI job "CI passed" green; `scripts/ci/check_docs.py` clean.
2. Independent review (fresh reviewer, no prior context) for Slices 2, 4 and 5: they touch policy, confirmations and permissions. Exit rule: no HIGH open.
3. UI slices (3, 4, 5): screenshots in both themes, contrast suite AA passing.
4. Dogfood in Chrome on the live stack for Slices 3 to 6: create, edit, undo one agent, one skill and one automation, all named with a `TEST-010-` prefix, and every TEST object deleted (agents, skills, rules, grants, connections) before the PR is marked ready, with the cleanup listed in the PR.
5. Any regression against main blocks the merge, whatever its severity.

## Deploy notes

- Migration is lazy and additive: the new `automation` history files appear on first write; the rules file remains what the engine reads, so rolling the code back leaves rules working (history is ignored).
- Policy rule changes ship in `default_rules.yaml`; a gitignored local rules override must not be required for any guarantee.
- Frontend restart for Slices 3 to 5: announce it first; open tabs need a refresh.
- Multi-worker: saves go through the store's file lock; no per-worker token is used on the save path.

## Risks

- **Mode detection false positives**: ordinary chat drifting into a build. Mitigation: chip is visible, × is one click, nothing saves without a click or exact "yes".
- **Typed-yes ambiguity**: "yes but shorter". Mitigation: whole-message closed list; anything else revises.
- **Rules file hand edits racing chat saves**: hash check plus baseline-on-detect; refused writes say why.
- **Card overload**: cap of 3 questions; permissions and connect only when needed.
- **1b slip**: Slices 1 and 2 ship usable value without it; Slice 3 waits.
- **Suggestion labelling misread**: suggestion cards carry the source and never accept typed confirmation, covered by an eval task.
