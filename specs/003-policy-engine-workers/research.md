# Phase 0 Research: Permission Policy Engine & Real-World Workers

Each entry records a decision, why it was chosen, and what else was considered. Entries marked **MEASURED** were read from or run against real code; entries marked **UNMEASURED** say so explicitly and become Phase 1 spikes rather than assumptions.

---

## R1 — Where the policy layer sits

**Decision**: an `AgentMiddleware` implementing `wrap_tool_call` / `awrap_tool_call`, installed in `_build_runtime_middlewares`.

**MEASURED**: four of five `create_agent` sites reach that base — the lead agent (two sites), `client.py`, and `subagents/executor.py`. `ToolCallRequest` carries `{tool_call, tool, state, runtime}`; `Runtime` carries `{context, store, stream_writer, previous, execution_info, server_info}`. A middleware may decline to call the handler and return a result in its place, which is how refusal is expressed.

**Rationale**: it is the only point every tool call passes through, and it can refuse.

**Alternatives considered**:
- *Wrapping each tool at load time.* Rejected: it puts the guarantee in the assembly code, so a tool added by a path that forgets to wrap is silently unguarded — the same shape as the bypass in R3.
- *An out-of-process policy service.* Rejected in Complexity Tracking: a dispatch path that proceeds when the check is unreachable is not a gate, and one that stops is worse than the risk.

---

## R2 — Reading turn provenance at dispatch (FR-004)

**Decision**: read `request.runtime.context["turn_provenance"]`.

**MEASURED**: this did not work until recently and its failure was silent. Feature 002 writes the marker to `config["configurable"]` and `config["metadata"]`; `runtime.context` is built only from `config["context"]`; and LangGraph ≥1.1.9 removed the fallback between them. Repaired by adding the keys to the gateway's context whitelist and mirroring `configurable` → `context`, guarded by `test_provenance_visible_at_dispatch.py`.

**Rationale**: structural, and a message body cannot reach it.

**Consequence for this plan**: FR-004's task must exercise the marker from inside a middleware, not assert that the gateway wrote it. The two are different claims and only the first is the one FR-004 makes.

---

## R3 — Closing the fifth agent-construction site (FR-003)

**Decision**: route `agents/factory.py` through `_build_runtime_middlewares`, or remove `create_omniharness_agent` from the public surface.

**MEASURED**: it assembles its own chain via `_assemble_from_features` and does not pass through the shared base. It has no production consumer — imported only by `tests/test_create_deerflow_agent.py` — but is exported as public API, so an embedder using it would escape classification entirely.

**Rationale**: FR-002 says exactly one dispatch path. A gate covering only the convergent four has its scope boundary precisely where the bypass lives, which is the shape that let Feature 002 ship inert.

**Alternatives considered**: *leave it, since nothing uses it.* Rejected — "nothing uses it today" is not a property the gate can check, and the module is public.

---

## R4 — Per-tool deny: two integration points (FR-013)

**Decision**: apply the deny list at **both** assembly points, and assert the gate on the **final assembled list**.

**MEASURED**:

| Path | Where | Touches `mcp/tools.py`? |
|---|---|---|
| `local:<server>` (MCP) | `mcp/tools.py:124-127` — `MultiServerMCPClient({server: params}, tool_name_prefix=True)`, then `get_tools()`, then `extend()` | yes |
| `connector:<SLUG>` (Composio) | `tools.py:~261` — `load_connector_tools`, live per user | **no** |

`CONNECTOR_SLUGS` already contains `GMAIL` and `GOOGLECALENDAR` (`connector_tools.py:29-30`). Tools are named `<server>_<tool>` and `_tool_source()` (`tools.py:75`) resolves the server, so a deny keyed on the unprefixed name is expressible.

**Rationale**: a deny at the MCP layer alone leaves `connector:GMAIL` and its send tool fully exposed. Asserting on the final list also means a third assembly path added later fails the gate rather than slipping past it.

**Alternatives considered**:
- *`tool_interceptors`.* The MCP client already accepts them and they are the obvious hook. Rejected: interceptors wrap **execution**, giving "guarded". FR-012 requires **absent**, because a capability that cannot be reached is a stronger guarantee than one that is checked.
- *Pinning Gmail to the MCP route and forbidding the connector.* Rejected: it makes FR-012 depend on the user not selecting the other route, which is a convention where the spec asks for a guarantee.

---

## R5 — Subagent suspend and resume (FR-031, FR-032)

**Decision**: attach a checkpointer to the subagent agent, as the run worker already does for the lead agent. Phase 1, before anything depends on it.

**MEASURED**, with a positive control:

| Shape | Result |
|---|---|
| With a checkpointer (lead agent — attached at run time) | suspends, resumes, tool then runs |
| Without a checkpointer (subagent — never attached) | the run **ends** at the suspension point; the tool never runs and there is nothing to resume from |

It does not raise. A subagent asked to confirm simply stops, having done nothing.

**Why the positive control mattered**: the first probe reported that suspension was unavailable outright. It was failing earlier, on a missing `bind_tools` in the stand-in model, and would have produced a wrong finding of much larger scope. The true finding is narrower and opposite in shape. This is the occasion for Article XII.

**Consequence**: FR-032's task must confirm **after a delay**. An instant confirmation cannot distinguish suspend-and-resume from stop-and-abandon.

---

## R6 — Browser profile isolation (FR-017, SC-007)

**Decision**: Phase 1 spike, positive control first.

**MEASURED**: no browser exists anywhere in the stack today — neither `docker-compose.yaml` nor `backend/Dockerfile` references chromium or a browser. MCP servers are configured in `extensions_config.json` as `stdio` (npx) or `sse`; currently `filesystem`, `github`, `postgres`, `github-issue-connector`, `session-watcher`.

**UNMEASURED**: Playwright MCP's own profile / user-data-dir behaviour. Not assumed.

**The spike's order is the point**: it must first demonstrate the browser **does** persist a cookie into its configured profile. Only then is "carries none of the user's daily cookies" evidence of anything — against an inert profile mechanism, an isolation test passes for the wrong reason and reports the strongest possible result.

**Article VI**: a browser binary is a real disk cost (roughly 150-400 MB depending on channel). It runs on demand and must not be resident. The spike records the measured footprint rather than estimating it, and confirms the lean non-Docker profile.

---

## R7 — Durable Pending Actions (FR-028..FR-030)

**Decision**: `JsonStore`-backed durable records with an atomic claim, reusing the shape Feature 002's pending firings now use.

**MEASURED** (during Feature 002 wiring): the gateway serves from several workers behind one socket; in-memory state belonging to one worker is lost when it dies; and `pg_try_advisory_lock` is unavailable by default because the compose stack has no database service and `DatabaseConfig.backend` defaults to `memory`.

**Rationale**: one persistence story for the project rather than two. A pending action must be findable from any worker, because the worker that stated the plan is unlikely to be the one that receives the answer.

**Note**: the policy layer does **not** run in the elected single runner — election is for the trigger engine. A policy decision happens in whichever worker handles the run, which is exactly why the record must be durable and worker-independent rather than reusing election.

**Alternatives considered**: *pin pending actions to the elected runner.* Rejected: it couples an interactive path to a background-work mechanism, and would make Tier 3 confirmation stop working whenever the trigger engine is disabled.

---

## R8 — Tool-result lineage (FR-005, FR-006)

**Decision**: read message lineage from `request.state`.

**Rationale**: tool results arrive as messages in agent state. The run-config marker used by FR-004 cannot express this — it answers "who is speaking", not "where did this content come from". Two mechanisms, deliberately kept as two requirements.

**UNMEASURED**: the precise shape of tool-result messages in `state["messages"]` for each tool source. A Phase 3 task establishes it before the check is written, with a positive control — construct a state that genuinely contains tool-result-derived content and confirm the check detects it, before trusting a negative.

---

## R9 — Redaction reuse (FR-018, FR-022)

**Decision**: consume Feature 001's redactor as an injected callable, in the shape Feature 002 already uses (`redact: Callable[[str], tuple[str, bool]]`, failing closed).

**MEASURED**: the redactor lives in `packages/session_watcher/session_watcher/redaction.py`; `session-watcher` is a declared workspace member of the backend, so `app/` may import it. The import ban runs the other direction — that package must not import core.

**Consequence for FR-022**: page content and email bodies are wider and less structured than the session records and agent output the patterns were tuned for. Widening happens in the redactor's own suite so a change made for this feature cannot silently weaken Features 001 or 002.

---

## Open items carried into Phase 1

| Item | Why it is a spike, not a decision |
|---|---|
| Playwright MCP profile behaviour (R6) | unmeasured; positive control required before any isolation claim |
| Tool-result message shape (R8) | unmeasured; the check must be seen detecting real lineage first |
| Browser disk/memory footprint (R6) | must be measured and stated, not estimated (Article X) |
