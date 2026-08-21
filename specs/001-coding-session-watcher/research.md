# Phase 0 Research: Read-Only Coding-Session Watcher

**Date**: 2026-08-20 | **Plan**: [plan.md](./plan.md)

All Technical Context unknowns are resolved below. No `NEEDS CLARIFICATION` remains.

---

## R1. Integration transport — SSE MCP server

**Decision**: Expose the watcher as an SSE MCP server declared in `extensions_config.json` under
`mcpServers`, reached at `http://host.docker.internal:<port>/sse`.

**Rationale**: Verified against the code rather than assumed. The gateway has no external
tool-registration API; tools reach the agent from exactly two sources, `local:<server>` (MCP) and
`connector:<SLUG>` (Composio). The resolution path is
`extensions_config.json` → `ExtensionsConfig.get_enabled_mcp_servers()`
(`backend/packages/harness/omniharness/config/extensions_config.py:93`) → catalog entry
`local:<name>` (`backend/app/gateway/routers/thread_tools.py:117`) → loaded for the agent
(`backend/packages/harness/omniharness/tools/tools.py:193`).

**Alternatives considered**:

- *stdio MCP server* — **rejected, and the rejection is structural — but not for the reason first
  recorded here.** A stdio server is spawned and owned by its client and torn down with the
  connection, so it cannot hold the registry, heartbeat, or filesystem observer this watcher needs
  across calls; that makes FR-024a and the FR-011a tri-state unimplementable, container or no
  container (FR-018a).

  *Originally recorded as*: "when the backend runs in a container it cannot read the host's
  `~/.claude`". **That is false** — the directory is bind-mounted into the container (R6b below).
  Corrected rather than deleted, because the wrong reason had already propagated into the spec,
  the contract, and the README.
- *Custom gateway registration API* — rejected: does not exist, and building one would add a
  core-coupled surface where a standard protocol already suffices.

**Precedent in-repo**: the `github-issue-connector` entry in `extensions_config.json` is an SSE
server at `http://host.docker.internal:18100/sse`. The watcher copies that shape. Port to be
allocated adjacent to it; `18101` proposed, subject to a free-port check at deploy time.

**Implementation note**: `mcp.server` is already a working in-repo dependency —
`backend/packages/harness/omniharness/tools/composio_mcp_server.py` builds an MCP server today
(stdio transport). The watcher uses the same library with the SSE transport.

---

## R2. Observed record format — empirical findings

**Decision**: Parse Claude Code's JSONL session records behind a single adapter
(`adapters/claude_code.py`), keyed on the `type` field, skipping unrecognized entries at debug
level (FR-009, FR-023).

**Rationale**: Grounded in a live sample rather than assumption — 42 record files present on this
machine; structure below drawn from the 200 most recent lines of the newest file. **This is a
one-machine, one-file sample and the format is explicitly not a public API** (FR-023's whole
premise), so the adapter treats every field as optional and every shape as provisional.

Observed `type` values and their frequency in the sample:

| `type` | Count | Relevance |
|---|---|---|
| `assistant` | 59 | Progress and last-message source |
| `attachment` | 37 | Ignorable for status |
| `user` | 33 | Turn boundary — a user record after an assistant record ends a wait |
| `mode`, `permission-mode` | 11 each | Candidate waiting-on-user signal; needs confirmation |
| `atis-latch`, `bridge-session` | 11 each | Unknown purpose — skipped, not errored |
| `last-prompt`, `ai-title` | 10 each | `ai-title` is a candidate cheap session label |
| `file-history-snapshot` | 4 | Ignorable for status |

Fields useful to the registry, present across most record types: `sessionId`, `timestamp`, `cwd`,
`gitBranch`, `uuid`, `parentUuid`, `type`, `version`, `isSidechain`.

**Three findings that change the design:**

1. **`sessionId` resolves the deferred identifier question.** The spec's FR-002 asserts a "stable
   session identifier" without saying what makes it stable; `/speckit-clarify` deferred this to
   planning. The record carries `sessionId` (and the filename is that id), stable across restarts
   because it is the observed agent's own identifier, not ours. **Decision**: adopt `sessionId`
   verbatim; never mint our own.

2. **Project directories carry a leading hyphen.** They are path-slugs of the form
   `-Users-rishabh-...`. A leading `-` is read as an option flag by most shell tooling and by some
   path libraries.

   **Decision — a module-wide rule, not a fixture note.** No path derived from the observed
   directory may be passed to a shell or subprocess **anywhere in the module**. Path handling uses
   `pathlib` APIs exclusively. This is enforced, not merely documented: `subprocess`, `os.system`,
   `os.popen`, and `shell=True` are added to the module's ruff `banned-api` list alongside the
   core-import ban (plan Gate 1), so a violation fails `ruff check` in the existing hook.

   The hyphen fixture proves the rule holds; the ban prevents it being broken later. Both are
   needed — a fixture only covers the paths a test happens to exercise, and this failure mode is
   invisible on the developer's machine right up until it isn't.

3. **No explicit waiting-on-user record type appears in the sample.** There is no
   `type: "question"` or equivalent. **Decision**: waiting-on-user must be *inferred* — an
   `assistant` record is the most recent entry, no `user` record follows it, and the inactivity
   threshold has not yet elapsed. This directly engages Article X and FR-016a: it is an
   inference, and the assistant must word it as one.

   **Error direction — err toward flagging.** When the inference is uncertain, report
   possible-blocked with honest wording rather than staying silent. The two errors are not
   symmetric: a false "waiting on you" costs one wasted walk to the machine, while a false
   "working" leaves a blocked session sitting untouched all evening — precisely the failure this
   feature exists to prevent. A silent miss is the expensive error; say so in the design and in
   the tests.

   **Wording is an acceptance criterion, not a style note.** The qualifier leads, exactly as it
   does for stale data (FR-011b) and mechanical summaries. Required shape:

   > "Looks like it's waiting on you — last activity was a question 8 minutes ago, nothing since."

   Forbidden shape:

   > "It's waiting for your input."

   The second states an inference as an observation, which FR-016a forbids. Story 2's tasks carry
   this as a testable criterion asserting on the reply's shape — a hedge present, and the
   observable evidence (what was seen, and when) accompanying it.

   **Corroboration investigation is timeboxed.** `mode` / `permission-mode` records are a
   candidate corroborating signal; if they carry a permission-prompt state they upgrade the
   inference toward observation. This is a **bounded** look — one timeboxed task, not an
   open-ended dig through an undocumented format. If it comes back empty, state the limit plainly
   and ship on the inference. A P1 story must not block on reverse-engineering a format that is
   explicitly not a public API.

**Alternatives considered**: parsing the coding agent's process tree or terminal output —
rejected as far more fragile than a documented-shape file, and unavailable when the session runs
in an editor.

**Duplicate-key caution**: the sample carries *both* `sessionId` and `session_id` on most
records. The adapter reads `sessionId` and treats `session_id` as an alias fallback, since one of
the two is likely a compatibility shim that may disappear.

**Sidechains**: `isSidechain` marks subagent activity. **Decision**: sidechain records update the
parent session's activity time but do not create a separate registry entry — a subagent is not a
session the user started.

---

## R2b. Permission-mode corroboration spike (T055) — **NEGATIVE**

**Question**: do `permission-mode` / `mode` records, or any assistant record shape,
distinguish a session paused on a permission prompt from one merely between turns? If so,
waiting-on-user upgrades from inference to observation and FR-016a's hedge could be dropped.

**Verdict: no such signal exists in the observed format.** Waiting-on-user remains an
inference, and the hedge-leads wording stands. Timebox spent; not reopened without new
evidence.

**Method**: whole-corpus scan — 25,696 lines across 42 files, 17 record types — looking inside
the message envelope rather than at top-level types, since that is where `stop_reason` was
missed the first time.

**What was ruled out**

| Candidate | Finding | Why it fails |
|---|---|---|
| `mode.mode` | `normal` in 1494/1494 | Constant. Carries no state at all. |
| `permission-mode.permissionMode` | `default` 366, `acceptEdits` 345, `auto` 97 | The user's configured **policy**, not runtime state. Also **carries no timestamp**, so it cannot be ordered against activity even if it did. |
| Unmatched `tool_use` (tool_use with no matching `tool_result`) | **0 across all 41 sessions** | The most promising hypothesis — a permission prompt should leave a tool call unanswered. It never occurs here. 5210 `tool_use` blocks, 5217 `tool_result` blocks. |
| A permission-request record type | None exists | 17 types enumerated; none represents a pending prompt. |
| `assistant.stop_details` | `<none>` in 10939/10939 | Always absent. |

**Sample limitation, stated rather than buried**: no session in this corpus was left sitting on
a permission prompt, so the positive case was never observable. This is weak evidence of
absence, not proof. If a blocked session is ever captured, the unmatched-`tool_use` hypothesis
is the one to re-test first — it is the only mechanism that would produce a distinguishable
trace.

**Two useful byproducts, both outside the spike's question**

1. **`system` / `subtype: turn_duration` is a second turn-boundary marker**, timestamped, and
   follows an `end_turn` assistant record in **460 of 477 cases (96.4%)**. It corroborates the
   `stop_reason` marker rather than replacing it. Not adopted — `stop_reason` is already
   sufficient for FR-006a and a second source would add ambiguity for no gain.

2. **`system` / `subtype: away_summary` — Claude Code writes its own session summaries.**
   Present in 17 of 42 sessions, 194–278 characters, and the last record in 11 of them. They
   are markedly better than mechanical clipping and often name the next action:

   > "We've been fixing and live-testing this server's providers; all five with keys now pass
   > after 15 bug fixes, documented in run_*.md files. Next action: run git init and commit,
   > since everything is currently untracked."

   *(Paraphrased. The originals are read from private session logs and are not reproduced here
   verbatim — this repository is public.)*

   **Flagged as a candidate FR-008 amendment, not adopted.** It is tempting — better prose,
   lower cost — but three objections stand, and the last two matter more than the first:

   - **Coverage**: present in only 17 of 42 sessions (~40%), so the mechanical path remains the
     default regardless and both would have to coexist.
   - **Semantic mismatch**: `away_summary` summarizes the WHOLE SESSION, while the roll-up line
     reports LAST ACTIVITY. Substituting one for the other makes an incoherent roll-up — some
     lines answering "what has this session been doing overall" and others answering "what did it
     just do", with nothing marking which is which.
   - **Staleness**: a summary written twenty turns ago describes the session as it was then, not
     now. Worse, it *reads* more authoritative than a mechanically clipped line while being less
     current — confident, well-formed, and out of date. That is precisely the fake-precision
     failure Article X names as a defect.

   **If adopted later, the likely right shape is a separate "session gist" field on the
   single-session detail reply — not a replacement for the activity line.** Two fields answering
   two different questions, each labelled, rather than one field quietly answering whichever
   question happened to have data.

3. **`file-history-delta` (166 records)** is a further record type absent from the original
   research sample. Added to `KNOWN_INERT_TYPES`.

---

## R3. Filesystem change notification

**Decision**: `watchdog` (new dependency) for OS-native change notification, with a slow polling
fallback (default 30 s) where the OS or filesystem does not support watching.

**Rationale**: FR-022 requires negligible idle cost; `watchdog` uses FSEvents on macOS and
`ReadDirectoryChangesW` on Windows, both of which are push-based and consume no CPU while idle.
It is the de-facto standard for this in Python and covers both required platforms (FR-020).

**Alternatives considered**: a bare polling loop — rejected against FR-022; `inotify` directly —
Linux-only, and the required platforms are macOS and Windows.

**Known caveats to design around**: FSEvents coalesces and can drop events under load, and
network/virtualised filesystems degrade unpredictably. **Decision**: watchdog is the fast path,
not the source of truth. A low-frequency reconciliation sweep re-reads last-modified times for
sessions already in the registry, so a missed event delays an update rather than losing it. This
also covers the laptop sleep/wake requirement (FR-024, SC-006) — on wake, reconciliation
re-establishes truth without a restart.

---

## R4. Summarizer lifecycle

**Decision**: `SummarizerPort` with `MechanicalSummarizer` as the default and
`OnDemandModelSummarizer` as an opt-in that loads inside a context manager and releases on exit.

**Rationale**: Article VI's < 500 MB idle budget forbids a resident model; FR-008b makes the
mechanical path first-class rather than a degraded fallback. See plan Gate 2 for the ownership
and the two-layer verification.

**Mechanical derivation specifics** (FR-008b): take the most recent `assistant` record's text,
strip fenced code blocks and terminal control sequences, collapse whitespace, clip at a sentence
boundary. Never a raw character truncation.

**Alternatives considered**: a resident small model — rejected against Article VI; cloud
summarization by default — rejected against Article VIII and FR-008a, available only as explicit
opt-in.

---

## R5. Redaction

**Decision**: A single `redaction.py` boundary applied to every outbound reply on every channel,
with channel-aware aggressiveness, failing closed, emitting visible `[redacted]` markers.

**Rationale**: FR-011c–f. Running it on local channels too means the code path is exercised where
failures are visible, rather than debuting in front of the least recoverable audience.

**Pattern set (initial)**: common API-key prefixes, `Bearer` tokens, connection-string URIs with
embedded credentials, PEM blocks, and `.env`-style `KEY=value` where the key name matches a
secret-ish pattern. **This list is deliberately described as *recognized patterns* and never as
"secrets"** — FR-011d makes the weaker claim binding, because pattern matching cannot honour the
stronger one.

**Alternatives considered**: entropy-based detection — rejected for this phase as it produces
false positives on code and base64 payloads, which are abundant in exactly this content; no
redaction — rejected against Article VIII.

---

## R6. Package placement and dependency isolation

**Decision**: `backend/packages/session_watcher/`, a uv workspace member that does **not** depend
on `omniharness-harness`.

**Rationale**: Resolves plan Gate 1 by placement — inside `^backend/`, so the existing
`.pre-commit-config.yaml` hooks apply with no config change — while keeping a hard dependency
boundary from core (Article I). Packaged with the backend, deployed as an independent host
process; those are separable, and separating them is what lets one placement satisfy both.

**Alternatives considered**: a top-level `watcher/` directory — rejected because it lands outside
the hook surface and would require four new hook entries to restore gates that placement gives
for free; living inside `packages/harness/` — rejected outright as it would make an Article I
violation a single import away.

---

## R6b. `~/.claude` IS mounted into the gateway container — discovered fact

**Discovered 2026-08-20 during T071**, the containerized end-to-end validation. Recorded because
it falsifies a rationale that had already propagated into four documents.

```
$ docker inspect omni-harness-gateway --format '{{range .Mounts}}...{{end}}'
bind  /Users/<you>/.claude -> /root/.claude
```

`docker-compose-dev.yaml:153-154` mounts `${HOME}/.claude` to `/root/.claude`. The container sees
the same 42 session files across 12 project directories as the host.

**Consequence**: FR-018a's original claim — that a containerized backend *cannot* read the host's
session directory — is false here. A stdio MCP server inside this container could read those
records. The stdio exclusion still stands, but on process-lifecycle grounds (see the amended
FR-018a), not on reachability.

**How this was missed, and what to change about spikes.** The T006 transport spike proved that
SSE *works*: a host-resident SSE server, reached from the containerized backend, returning a
payload. It never attempted to falsify the alternative. Confirming that the chosen option works
is not the same as establishing that the rejected one fails, and only the second justifies an
exclusion written into a requirement.

The check that would have caught this was one `docker inspect` of the mount table — cheaper than
the spike that was run. **Design future spikes to attack the rejected option, not only to
validate the chosen one.** A spike that can only return "yes, this works" cannot tell you whether
you needed it.

---

## Resolved deferrals from `/speckit-clarify`

| Deferred item | Resolution |
|---|---|
| Session identifier stability (FR-002) | Adopt the observed agent's own `sessionId`; never mint one (R2, finding 1). |
| Observability specifics | Structured debug logging at the adapter skip path (FR-009) plus `RecordSource.stats` counters (Gate 3). Not expanded further this phase. |
| Accessibility / localization | Out of scope; no user-facing surface of our own — replies are rendered by existing channels. |
