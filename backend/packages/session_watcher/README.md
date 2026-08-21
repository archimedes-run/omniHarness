# session-watcher

Read-only visibility into coding-agent sessions running on this machine. Answers
"what are my sessions doing?" from any channel — including your phone — without
walking back to the desk.

**Observe-only — for externally-started sessions.** It reads session records and
never writes to them. For a session you started yourself in an editor or a
terminal, it cannot answer a question or intervene, because a JSONL log is the
only channel available and that channel is read-only.

That limit is **specific to externally-started sessions, not a permanent
ceiling.** Sessions this system spawns itself in a later phase run under
`--output-format stream-json`, where permission requests arrive as structured
events on a live channel. That path gets **observation, not inference** — and an
answer path with it. Treat the inference-based detection described below as the
best available reading of a read-only log, not as the design's final word.

## Starting it

It runs on the **host**, not in Docker — it reads `~/.claude`, which a container
cannot see.

```bash
cd backend
uv run python -m session_watcher.server            # port 18101, ~/.claude/projects
uv run python -m session_watcher.server --port 18101 --root ~/.claude/projects
```

Check it:

```bash
curl -s localhost:18101/health
# {"ok":true,"observability":"live","sessions":9}
```

### ⚠️ The config entry does not start the process

`extensions_config.json` has a `session-watcher` entry with `"enabled": true`
pointing at `http://host.docker.internal:18101/sse`. That entry tells the agent
where to look — **it does not launch anything.** If the watcher is not running,
the endpoint is dead and tool calls fail with a connection error.

That is a bearable failure (the agent reports it cannot reach the watcher, which
is honest) but a confusing one if you have forgotten the process needs starting.
Two options when you are not using it:

- leave it enabled and start the watcher, or
- set `"enabled": false` in `extensions_config.json`.

**Which config file?** The gateway container sets
`OMNI_HARNESS_EXTENSIONS_CONFIG_PATH=/app/extensions/extensions_config.json`, which
maps to **`extensions/extensions_config.json`** on the host — *not* the repo-root
`extensions_config.json`. Editing the root file has no effect on the containerized
gateway. Both are gitignored, so neither appears on a fresh clone; copy the entry
from `specs/001-coding-session-watcher/contracts/mcp-tools.md`.

The server is **pinned** (`PINNED_LOCAL_SERVERS` in
`backend/packages/harness/omniharness/tools/tools.py`), so its two tools are
available in every conversation with no per-thread selection.

### Verifying it from the containerized backend

**Why SSE and not stdio**: a stdio MCP server is spawned and owned by its client
and torn down with each connection. This watcher is stateful across calls — a
background refresh loop, a heartbeat, staleness tracking, sticky membership, a
filesystem observer — and a per-connection subprocess has nothing persistent to
be stale about, which makes the `observability` tri-state unimplementable. That
holds with no container in the picture.

(Secondary: under Docker a stdio server would also depend on `~/.claude` being
mounted into the container. It *is* mounted here — `docker-compose-dev.yaml:153`
— so the often-repeated "the container can't see your sessions" is **not** the
reason. See `specs/001-coding-session-watcher/research.md` R6b.)

```bash
docker exec omni-harness-gateway sh -c 'curl -s http://host.docker.internal:18101/health'
```

## Configuration

| Setting | Default | What it does |
|---|---|---|
| inactivity period | 5 min | Quiet longer than this, with no end-of-turn marker, infers *stalled*. Raise it if long builds get misreported. |
| heartbeat interval | 30 s | How often the registry marks itself current. |
| staleness threshold | 90 s | Two missed heartbeats before data is labelled last-known. |
| recency window | 24 h | How far back sessions are listed. Sessions seen active stay listed regardless. |

## What the states mean

| State | Meaning | How we know |
|---|---|---|
| `working` | Active recently | observed |
| `idle` / `completed` | Recorded an end-of-turn | **observed fact** |
| `idle` / `stalled` | Went quiet with no end-of-turn — may have finished, crashed, or been killed | **inferred** |
| `waiting-on-user` | Appears to be waiting on a question | **inferred** |
| `failed` | Recorded a failure | observed |
| `unknown` | Records present but unreadable | — |

The completed/stalled split is the point of the design, not a detail. `completed`
comes from `message.stop_reason == "end_turn"` in the session record; `stalled` is
an inference from silence. Replies word them differently on purpose, and anything
inferred leads with its hedge.

`waiting-on-user` is inferred from an ended turn whose last words were a question
with no reply since. It deliberately does **not** fire on a pending tool call: a
permission prompt and a ten-minute build produce an identical trace in the log
(see `research.md` R2b), so flagging that shape would announce "waiting on you"
during every long build. A genuinely blocked prompt still surfaces — as `stalled`
once the inactivity period elapses. Sessions spawned under `stream-json` in a
later phase will observe permission requests directly and need none of this.

## Development

```bash
cd backend
uv run pytest tests/session_watcher/ -q
uv run ruff check packages/session_watcher/
```

### The gates

Three lint/test gates encode constitutional guarantees. Each ships with a way to
watch it fail, because **a gate never observed failing is indistinguishable from
one that does nothing**:

| Gate | Guards | Break it with |
|---|---|---|
| 1 | no core imports; no shell-out (paths start with `-`) | add `import omniharness` or `import subprocess` → `ruff check` must exit 1 |
| 2 | model is released, never resident (Article VI) | retain the handle on the summarizer → `test_summarizer_lifecycle.py` must fail |
| 3 | startup scales with the window, not the directory | bypass `RecordSource.select_candidates` → `test_discovery_window.py` must fail on **records_opened**, not elapsed time |

If Gate 3 still passes when sabotaged, the assertion is on the wrong quantity —
most likely elapsed time, which passes on fast hardware regardless.

## Design notes

Full spec, plan and decision record: `specs/001-coding-session-watcher/`.

- `adapters/claude_code.py` is the only file that knows the record format. That
  format is not a public API; unknown entries are skipped and **counted**, so
  drift is visible rather than silent.
- `record_source.py` is the single seam for opening records, which is what makes
  the Gate 3 assertion meaningful.
- `reply.py` is where the wording rules live. Read the composed text aloud before
  changing anything there.
