# OmniHarness Platform Architecture

This document provides a high-level overview of the OmniHarness platform architecture,
focusing on the backend domain structure and extension points.

## Domain Boundaries

OmniHarness is structured around three primary layers:

1. **Harness** (`packages/harness/omniharness/`) — Core agent framework, persistence, config.
2. **App** (`app/`) — FastAPI gateway, routers, and IM channel integrations.
3. **Frontend** (`frontend/`) — Next.js web interface.

The dependency rule is strict: `app.*` may import `omniharness.*`, but `omniharness.*` must
never import `app.*`. This boundary is enforced by `tests/test_harness_boundary.py`.

## Persistence Domains

Each persistence domain lives in `omniharness/persistence/<domain>/` and contains:

- `model.py` — SQLAlchemy ORM model (inherits from `Base`)
- `sql.py` — Repository class with async session factory
- `__init__.py` — Public re-exports

All models are registered in `omniharness/persistence/models/__init__.py` for Alembic autogenerate.

### Current domains

| Domain | Table | Description |
|--------|-------|-------------|
| `run` | `runs` | Agent run metadata |
| `feedback` | `feedback` | User feedback on runs |
| `thread_meta` | `thread_meta` | Thread metadata |
| `user` | `users` | User accounts |
| `mcp_secrets` | `mcp_secrets` | Encrypted MCP credentials |
| `mcp_server` | `mcp_servers` | MCP server definitions |
| `workflows` | `workflows` | Workflow definitions (Phase 0) |

## Feature Flags

Feature flags live in `omniharness/config/` as Pydantic models and are loaded into `AppConfig`.
They default to `False` (off) and can be enabled in `config.yaml`.

Current flags:

- `mcp_builder.enabled` — MCP Studio build pipeline
- `workflows.enabled` — Workflows domain (Phase 0 skeleton)

## Workflows Domain (Phase 0)

The Workflows domain is a Phase 0 "walking skeleton". It provides:

- `WorkflowRow` ORM model with draft/active/paused/archived lifecycle
- `WorkflowRepository` with full CRUD + archive operations
- `/api/workflows` REST API (feature-flagged, returns 404 when disabled)
- Frontend page at `/workspace/workflows` (hidden when `NEXT_PUBLIC_FEATURE_WORKFLOWS != "true"`)

Phase 1 will add workflow execution support.

---

## IM Channels — no streaming path (deliberate)

`ChannelManager` delivers an assistant reply with a single `runs.wait` call. There is **no
incremental/streaming delivery path**, and `Channel` has no `supports_streaming` capability.

One existed until 2026-08-21 (`_handle_streaming_chat`, ~109 lines, plus its stream-accumulation
helpers and a `CHANNEL_CAPABILITIES` table). It was unreachable: Feishu was the only channel that
set `supports_streaming = True`, and Feishu was never ported here from the DeerFlow heritage —
`app/channels/feishu.py` has no history in this repo. The manager-side code arrived; its only
possible caller did not.

**It was deleted rather than kept for a future streaming consumer, and that was a deliberate
call.** The next thing likely to want streaming is a local spoken channel. Voice needs
audio-chunk semantics — utterance boundaries, barge-in, partial-transcript revision — not the
message-patch semantics this code implemented (edit-a-sent-message-in-place, throttled by a
0.35s minimum interval). Keeping it would have preserved code that was unused now *and* wrong
for its expected consumer later, in a shape convincing enough to be adopted instead of designed.

If you are implementing streaming: design it against the consumer you actually have. Recover the
deleted code with `git log -- backend/app/channels/manager.py` if you want it as reference, not
as a starting point.

## Agent construction — one path, no embedding API (deliberate)

Every agent in this system is constructed through a call site that reaches
`_build_runtime_middlewares`. There are three: the lead agent, the client, and
the subagent executor. A CI gate enumerates every `create_agent` call in the
repository and fails if one does not reach that base, with an **empty**
whitelist.

A fourth existed until 2026-08-24: `omniharness.agents.factory`, exporting
`create_omniharness_agent` as an embedding API. It was **deleted**, not routed
through the base, and the reason is about its contract rather than its wiring.

The factory documented a **middleware-takeover contract**: passing
`middleware=[x]` produced exactly `[x]`, with the caller in full control of the
chain. Feature 003 requires that no dispatch path bypass policy classification.
**Those two guarantees cannot both hold.** You cannot promise "the caller
controls the whole middleware list" and "no path bypasses policy" — the contract
was the thing that was wrong, not the absence of a prepended middleware. Routing
it through the base was attempted and failed six tests that assert the takeover
contract, which is the contract doing its job.

Keeping it would have bought a public API **with no production caller**, at the
cost of a permanently whitelisted bypass of this feature's central guarantee.

**The gate's rule stayed at its stronger form as a direct result**: every
`create_agent` site, not merely every publicly reachable one. Making the module
private would have satisfied a weaker rule while leaving the bypass in the tree,
and a weaker rule would not catch a new INTERNAL bypass added later.

**If an embedding API is wanted later**, the correct version routes through
policy — the caller composes *additional* middleware, never the whole list.
Recover the deleted code with `git log -- backend/packages/harness/omniharness/agents/factory.py`
as reference, not as a starting point.

This is the same call, for the same reason, as the deleted IM streaming path
described above: unused now, and wrong for its eventual consumer later.

## Platform Event Envelope

**Invariant: there is one events table and one event store. Product objects emit through
the envelope, never a parallel system.**

### Storage — `run_events` table

All platform events are stored in the existing `run_events` table (ORM: `RunEventRow`).
No second events table exists or will be created. The existing event store abstraction
(`omniharness.runtime.events.store`) is reused verbatim.

### Source discriminator (`run_events.source`)

Migration `0011` adds a single nullable `source VARCHAR(32)` column.

| Value | Meaning |
|-------|---------|
| `NULL` | Back-compat — all pre-existing run / agent / chat events. Treated as `"run"`. |
| `"run"` | Produced by the lead-agent execution path (explicit). |
| `"workflow"` | Produced by the Workflows domain. |
| `"trigger"` | Produced by a Trigger. |
| `"watcher"` | Produced by a Watcher. |
| `"notification"` | Produced by the Notification subsystem. |
| `"approval"` | Produced by the Approval subsystem. |
| `"capability"` | Produced by a Capability. |
| `"channel"` | Produced by an IM Channel. |

`EventSource` in `omniharness.platform.events` is the **single source of truth** for these values.
Both the column docs above and the envelope import from there.

**Object references go in `event_metadata` JSON — never in new columns.**
For example, a workflow event carries `{"workflow_id": "..."}` in `metadata`.

### `PlatformEvent` envelope (`omniharness.platform.events`)

```
PlatformEvent
  thread_id   str        — real chat thread, or synthetic "plat-{type}-{id}" for no-run-yet
  run_id      str|None   — real run_id, or None (stored as sentinel "platform")
  user_id     str|None
  source      EventSource
  event_type  str        — "workflow.step.started", "trigger.fired", etc.
  category    str        — "lifecycle" | "message" | "trace"  (default: "lifecycle")
  content     str        — human-readable summary
  metadata    dict       — object refs: {"workflow_id": "..."}, {"trigger_id": "..."}
  seq         int|None   — assigned by the store on write
  created_at  datetime|None — assigned by the store on write
```

`PlatformEvent.to_store_kwargs()` returns the kwargs dict for `RunEventStore.put()`.
`PlatformEvent.from_row(row)` and `from_dict(d)` reconstruct from the physical row.
There is exactly **one physical representation**.

### No-run-yet convention

Some product events fire before a run exists (e.g. a Workflow receiving an external trigger
before execution starts). Convention:

- `thread_id = f"plat-{object_type}-{object_id}"` — synthetic, scoped to the object.
  Use only `[A-Za-z0-9_-]` chars (required by the JSONL backend path-safety check).
- `run_id = None` → stored as the sentinel string `"platform"` (satisfies `NOT NULL`).
  `from_row()` / `from_dict()` restore this back to `None`.

The synthetic `thread_id` is completely separate from real chat thread IDs (which are UUIDs),
so the `uq_events_thread_seq` uniqueness constraint is never in conflict.

### Emitting events (`omniharness.platform.writer`)

```python
from omniharness.platform.events import EventSource
from omniharness.platform.writer import emit_platform_event

result = await emit_platform_event(
    store,                                  # existing RunEventStore instance
    thread_id="plat-workflow-wf-123",
    event_type="workflow.step.started",
    source=EventSource.WORKFLOW,
    metadata={"workflow_id": "wf-123"},
)
# result.seq is assigned by the store
```

No product object wires this up yet — that happens in Phase 1.

---

## Idempotency-Key Convention

**Contract (enforced starting Phase 1/2):** Before creating a run for a scheduled or
event-triggered workflow, compute its idempotency key. If a run with that key already exists,
no-op instead of creating a duplicate.

Helper: `omniharness.platform.idempotency.compute_idempotency_key()`

### Canonical forms

**Scheduled runs:**
```python
key = compute_idempotency_key(workflow_id, scheduled_time="2026-07-01T09:00:00Z")
# → "wf:<workflow_id>:sched:<sha256>"
```
Deterministic: same workflow + same scheduled slot → same key.

**Event/trigger runs:**
```python
key = compute_idempotency_key(workflow_id, trigger_payload={"event": "push", "repo": "omniHarness"})
# → "wf:<workflow_id>:trig:<sha256>"
```
Deterministic: payload key order is normalised (sorted) before hashing, so
`{"a": 1, "b": 2}` and `{"b": 2, "a": 1}` produce the same key.

Phase 0 delivers the convention + helper + tests only. No column is added to any table
and no executor is wired up yet. Phase 1/2 will store the key in `RunRow.idempotency_key`
and enforce the no-op behaviour.
