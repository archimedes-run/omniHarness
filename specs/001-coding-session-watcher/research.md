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

- *stdio MCP server* — **rejected, and the rejection is structural.** A stdio server is spawned as
  a subprocess of the backend. When the backend runs in a container it cannot read the host's
  `~/.claude`, which is the watcher's entire purpose (FR-021, FR-018a).
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
   path libraries. **Decision**: the adapter resolves paths via `pathlib` with explicit
   `Path` construction and never interpolates a directory name into a shell command. A fixture
   directory reproducing the leading hyphen is mandatory, because this will silently work on the
   developer's machine and break in a shell-out.

3. **No explicit waiting-on-user record type appears in the sample.** There is no
   `type: "question"` or equivalent. **Decision**: waiting-on-user must be *inferred* — an
   `assistant` record is the most recent entry, no `user` record follows it, and the inactivity
   threshold has not yet elapsed. This directly engages Article X and FR-016a: it is an
   inference, and the assistant must word it as one. `mode` / `permission-mode` records are a
   candidate corroborating signal and are flagged for investigation during implementation; if
   they prove to carry a permission-prompt state, they upgrade the inference toward observation.

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

## Resolved deferrals from `/speckit-clarify`

| Deferred item | Resolution |
|---|---|
| Session identifier stability (FR-002) | Adopt the observed agent's own `sessionId`; never mint one (R2, finding 1). |
| Observability specifics | Structured debug logging at the adapter skip path (FR-009) plus `RecordSource.stats` counters (Gate 3). Not expanded further this phase. |
| Accessibility / localization | Out of scope; no user-facing surface of our own — replies are rendered by existing channels. |
