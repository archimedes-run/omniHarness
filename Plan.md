# OmniHarness Integration Plan — Triple-Threat Stack Review

**Scope**: OmniHarness + OpenClaw + OpenClaude + ADK Defenses  
**Reviewed against**: `harness.md`, `backend/CLAUDE.md`, live source code, and official OpenClaw/OpenClaude documentation  
**Date**: 2026-05-08

---

## Overall Assessment

The architectural direction is sound. The integration pattern — app-layer tool wrapper, middleware injection via `@Prev`/`@Next`, channel subclass — maps correctly to how OmniHarness actually works internally. However there are **8 critical bugs** that would prevent any stage from running, **5 factual errors** about the external tools, and **3 redundancies/incomplete pieces** that need resolution before implementation begins.

---

## External Tool Reality Check

Before reviewing the code, these are the verified facts about the two external tools referenced throughout.

### OpenClaude

- **Real tool** — community-built CLI coding agent forked from Claude Code
- Primary forks: `@gitlawb/openclaude` (GitHub: Gitlawb/openclaude) and `@aryanjsx/openclaude`
- Invoked as the `openclaude` shell command after `npm install -g @gitlawb/openclaude`
- `CLAUDE_CODE_USE_OPENAI=1` — documented and supported env var to route to OpenAI backend
- `NO_COLOR=1` and `FORCE_COLOR=0` — documented but **unreliable** (upstream bugs #8561 and #20602 on anthropics/claude-code)
- **No `--no-color` CLI flag** — does not exist in openclaude docs
- Interactive hangs on non-TTY environments are a confirmed bug (issue #228)
- Headless/non-interactive mode is via gRPC server (`GRPC_PORT`) not a `--print` flag

### OpenClaw

- **Real tool** — personal AI assistant gateway written in **Node.js** (requires Node 22.16+, Node 24 recommended)
- Docs: `docs.openclaw.ai` / GitHub: `openclaw/openclaw`
- **Not a "fast-rust daemon"** — that description matches **RustClaw** (`rustclaw.org`), a separate competing project written in Rust; the guide conflates the two
- "oh-my-codex runtime" refers to the oh-my-codex (OMX) project's OpenClaw integration layer
- Webhook auth uses **`Authorization: Bearer <token>` headers** — not HMAC signatures
- Webhook `/hooks/agent` payload schema: `{message, agentId, channel, to, wakeMode, ...}` — `thread_id` and `user_id` are **not** top-level fields in OpenClaw's documented API
- Connects to coding agents via ACP (Agent Client Protocol) over stdio JSON-RPC

---

## Stage 1 — Foundation & Core Setup

### Page 1: `OpenClaudeCodingTool` (`backend/app/tools/openclaude.py`)

#### Issue 1 — `resolve_variable` requires an instance, not a class [CRITICAL]

`tools.py:48` calls `resolve_variable(cfg.use, BaseTool)` which runs `isinstance(variable, BaseTool)`. A Python class is not an instance of `BaseTool`, so pointing config to `app.tools.openclaude:OpenClaudeCodingTool` raises:

```
ValueError: app.tools.openclaude:OpenClaudeCodingTool is not an instance of BaseTool, got type
```

**Fix**: Export a module-level instance and reference it in config:

```python
# bottom of app/tools/openclaude.py
openclaude_coder = OpenClaudeCodingTool()
```

```yaml
# config.yaml
use: app.tools.openclaude:openclaude_coder
```

---

#### Issue 2 — `_run()` is missing [HIGH]

`BaseTool` requires both `_run` (sync) and `_arun` (async). Subagent execution and several LangChain wrappers call the sync variant. Without it, sync calls raise `NotImplementedError`.

**Fix**:

```python
def _run(self, prompt: str, run_manager: Optional[Any] = None) -> str:
    import asyncio
    return asyncio.get_event_loop().run_until_complete(self._arun(prompt))
```

---

#### Issue 3 — Command injection via unquoted `prompt` [CRITICAL — security]

```python
cmd = f'CLAUDE_CODE_USE_OPENAI=1 NO_COLOR=1 FORCE_COLOR=0 openclaude "{prompt}"'
```

If `prompt` contains `"`, backticks, or `$(...)`, this breaks shell quoting and enables command injection.

**Fix**:

```python
import shlex
cmd = f'CLAUDE_CODE_USE_OPENAI=1 NO_COLOR=1 FORCE_COLOR=0 openclaude {shlex.quote(prompt)}'
```

Or use `create_subprocess_exec` with an argument list to avoid the shell entirely.

---

#### Issue 4 — Zombie process on timeout [MEDIUM]

After `process.kill()`, the process is never reaped:

```python
except asyncio.TimeoutError:
    process.kill()
    return f"Error: ..."  # process lingers as zombie
```

**Fix**: await `communicate()` after kill:

```python
except asyncio.TimeoutError:
    process.kill()
    await process.communicate()
    return f"Error: OpenClaude execution timed out after {self.timeout_seconds} seconds."
```

---

#### Issue 5 — `workspace_dir` points to the wrong path context [HIGH]

`workspace_dir: str = Field(default="/mnt/acp-workspace")` is the virtual path that only exists **inside** sandbox containers. `asyncio.create_subprocess_shell` runs in the **gateway container process**, not inside a sandbox. The gateway process would attempt to `cwd` to a non-existent path.

The actual ACP workspace is at:
```
$OMNI_HARNESS_ROOT/backend/.omni-harness/users/{user_id}/threads/{thread_id}/acp-workspace/
```

The tool has no access to `thread_id` or `user_id` in its current design. This requires either passing these as tool arguments or injecting them via LangGraph runtime context.

---

#### Issue 6 — `args_schema` is absent [MEDIUM]

Without an explicit `args_schema`, LangChain auto-generates one from `_arun`'s signature, which may expose `run_manager` as a visible tool parameter to the LLM.

**Fix**:

```python
from pydantic import BaseModel

class _Input(BaseModel):
    prompt: str

args_schema: type[BaseModel] = _Input
```

---

#### Issue 7 — `openclaude` not installed in the gateway container [HIGH]

The gateway Docker image has no `openclaude` npm package. It must be added to the image or installed at init time:

```dockerfile
RUN npm install -g @gitlawb/openclaude
```

The guide does not mention this prerequisite.

---

#### What is correct in Page 1

- `CLAUDE_CODE_USE_OPENAI=1` env var — documented and correct
- `_strip_ansi()` regex — correct and necessary fallback (since `NO_COLOR` is unreliable)
- `asyncio.wait_for` timeout pattern — correct approach
- Placement in `app/tools/` (app layer, not harness layer) — architecturally correct per the harness/app boundary

---

### Page 2: Config (`config.yaml` additions)

#### Issue 8 — `group: sandbox` references a non-existent tool group [MEDIUM]

`config.yaml` defines `tool_groups: [web, file:read, file:write, bash]`. There is no `sandbox` group. The tool will not be filtered correctly.

**Fix**: Either add `- name: acp` to `tool_groups` and use `group: acp`, or use the existing `bash` group.

---

#### Issue 9 — `{thread_id}` in `mounts.host_path` is not substituted [LOW]

`VolumeMountConfig` (`sandbox_config.py`) is a static Pydantic model. The string `./threads/{thread_id}/acp-workspace` has no template substitution — `{thread_id}` would be used literally as a directory name.

This is also unnecessary: per CLAUDE.md, the ACP workspace is already auto-mounted by the sandbox system at `/mnt/acp-workspace` for every thread. If you need **read-write** access (the guide sets `read_only: false` vs the default read-only), that is a real distinction — but the mount itself does not need re-specifying.

---

#### What is correct in Page 2

| Config field | Status |
|---|---|
| `replicas: 3` | Valid `SandboxConfig` field (`sandbox_config.py:26`) |
| `idle_timeout: 600` | Valid `SandboxConfig` field (`sandbox_config.py:34`) |
| `subagents.custom_agents` | Correct field name (`SubagentsAppConfig.custom_agents`, `subagents_config.py:85`) |
| `model: inherit` | Valid (`CustomSubagentConfig.model = Field(default="inherit")`) |
| `disallowed_tools: ["task"]` | Valid — already the default, so redundant but harmless |
| `max_turns: 50` / `timeout_seconds: 900` | Valid `CustomSubagentConfig` fields |

---

## Stage 2 — Defensive Middlewares

### Page 1: `LargeContextTruncatorMiddleware`

#### Issue 10 — Duck-typing fails `extra_middleware` validation [CRITICAL]

`factory.py:66-69` explicitly validates every item in `extra_middleware`:

```python
for mw in extra_middleware:
    if not isinstance(mw, AgentMiddleware):
        raise TypeError(f"extra_middleware items must be AgentMiddleware instances, got {type(mw).__name__}")
```

A duck-typed class that doesn't extend `AgentMiddleware` raises `TypeError` at agent creation time.

**Fix**:

```python
from langchain.agents.middleware import AgentMiddleware

class LargeContextTruncatorMiddleware(AgentMiddleware):
    ...
```

---

#### Issue 11 — `before_model` signature is missing `runtime` parameter [CRITICAL]

Confirmed from `summarization_middleware.py:120` and all other middlewares:

```python
def before_model(self, state: AgentState, runtime: Runtime) -> dict | None:
```

The guide omits `runtime: Runtime`. LangChain's middleware dispatch will raise a signature mismatch error.

**Fix**:

```python
from langgraph.runtime import Runtime
from langchain.agents import AgentState

def before_model(self, state: AgentState, runtime: Runtime) -> dict | None:
    ...
```

---

#### Issue 12 — `@Prev` takes a class reference, not a string [CRITICAL]

`features.py:37-46`:

```python
def Prev(anchor: type[AgentMiddleware]):
    if not (isinstance(anchor, type) and issubclass(anchor, AgentMiddleware)):
        raise TypeError(f"@Prev expects an AgentMiddleware subclass, got {anchor!r}")
```

Passing a string raises `TypeError`.

**Fix**:

```python
from omniharness.agents.middlewares.summarization_middleware import OmniHarnessSummarizationMiddleware

@Prev(OmniHarnessSummarizationMiddleware)
class LargeContextTruncatorMiddleware(AgentMiddleware):
    ...
```

---

#### Issue 13 — In-place mutation of `msg.content` may silently fail [MEDIUM]

LangGraph state messages may be frozen/immutable depending on the reducer. Mutating `.content` directly on list items extracted from state does not guarantee the change is reflected in the next state snapshot.

**Fix**: Create new `ToolMessage` objects and return a full state replacement:

```python
from langchain_core.messages import RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES

new_messages = []
for msg in messages:
    if isinstance(msg, ToolMessage) and isinstance(msg.content, str) and len(msg.content) > self.threshold:
        msg = ToolMessage(
            content=msg.content[:self.keep] + f"\n\n[... TRUNCATED {len(msg.content) - self.keep} chars ...]",
            tool_call_id=msg.tool_call_id,
            name=msg.name,
        )
    new_messages.append(msg)
return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES)] + new_messages}
```

---

### Page 2: `StreamingLoopDetectionCallback`

#### Issue 14 — Duplicates the existing `LoopDetectionMiddleware` [REDUNDANCY]

OmniHarness already ships `LoopDetectionMiddleware` as middleware #17 in the chain. It uses hash-based detection with configurable `warn_threshold=3` and `hard_limit=5`, and was extended to support per-tool frequency overrides (commit `daa3ffc2`). Adding a second loop detector at the streaming layer creates redundant complexity without clear benefit.

If streaming-phase detection is specifically desired (before a full response is returned), this should be documented as an intentional addition with a clear justification for the overlap.

---

#### Issue 15 — Raising exceptions inside `on_llm_new_token` aborts the run destructively [HIGH]

There is no LangGraph mechanism to "sever" a token stream mid-generation via a callback exception. Raising `LoopDetectedException` inside `on_llm_new_token` propagates through LangGraph's streaming engine and kills the entire agent run with no usable output — the LLM generation is left in an invalid, partial state.

The guide acknowledges "this exception must be caught in app.py's stream execution wrapper" but catching it at that level does not restore the run — it simply masks the crash. The existing `LoopDetectionMiddleware` handles this correctly by running in `after_model` on a complete response, then stripping tool calls to force a text answer.

---

## Stage 3 — Advanced Orchestration & Security

### Page 1: Summarization Config

#### Issue 16 — `{event_history}` is the wrong template variable name [CRITICAL]

`langchain/agents/middleware/summarization.py:607` formats the prompt as:

```python
self.summary_prompt.format(messages=formatted_messages)
```

The injected variable is `{messages}`, not `{event_history}`. Using `{event_history}` raises `KeyError: 'event_history'` the first time summarization triggers.

**Fix**: Replace every `{event_history}` in the `summary_prompt` with `{messages}`.

---

#### What is correct in Page 1

| Config field | Status |
|---|---|
| `keep.type: tokens` | Valid — `ContextSizeType = Literal["fraction", "tokens", "messages"]` |
| `trigger` as list of thresholds | Valid — `SummarizationConfig.trigger: ContextSize \| list[ContextSize] \| None` |
| `summary_prompt` as config override | Valid field — overrides LangChain's default prompt |
| Preserving exact file paths in summary | Good practice — correct reasoning |

---

### Page 2: Guardrails

#### What is correct in Page 2

| Item | Status |
|---|---|
| `omniharness.guardrails.builtin:AllowlistProvider` | Confirmed correct path (`guardrails/builtin.py`) |
| `allowed_tools: null` → allow all tools | Correct — `AllowlistProvider` sets `self._allowed = None` when input is `None/null`, which bypasses the allowlist check |
| `fail_closed: false` | Valid field — intentional security tradeoff (fail-open) |

**Note on commented OAP section**: The `deny_commands` and `require_human_approval` fields shown in the commented-out example do not match `GuardrailProviderConfig`'s actual schema. These appear to be fields from a hypothetical third-party package (`aport_guardrails`) not present in this repository.

---

## Stage 4 — OpenClaw Bridge & Frontend

### Page 1: `OpenClawChannel`

#### Issue 17 — Wrong base class name [CRITICAL — ImportError]

The actual class in `app/channels/base.py:17` is `Channel`, not `BaseChannel`.

```python
# Guide has:
from app.channels.base import BaseChannel  # ImportError

# Correct:
from app.channels.base import Channel
class OpenClawChannel(Channel):
    ...
```

---

#### Issue 18 — Wrong constructor signature [CRITICAL — TypeError]

`Channel.__init__(self, name: str, bus: MessageBus, config: dict[str, Any])` requires three arguments. The guide calls `super().__init__(message_bus)` — missing `name` and `config`.

**Fix**:

```python
def __init__(self, bus: MessageBus, config: dict):
    super().__init__("openclaw", bus, config)
    self.webhook_secret = config.get("openclaw_secret", "")
```

---

#### Issue 19 — `message_bus.publish()` does not exist [CRITICAL]

`MessageBus` (confirmed in `message_bus.py`) exposes `publish_inbound(msg: InboundMessage)` and `publish_outbound(msg: OutboundMessage)`. There is no `publish(topic, data)` method.

**Fix**:

```python
from app.channels.message_bus import InboundMessage, InboundMessageType

await self.bus.publish_inbound(InboundMessage(
    channel_name=self.name,
    chat_id=str(payload.get("thread_id", "")),
    user_id=str(payload.get("user_id", "")),
    text=str(payload.get("message", "")),
    msg_type=InboundMessageType.CHAT,
))
```

---

#### Issue 20 — Webhook payload fields don't match OpenClaw's documented API [HIGH]

OpenClaw's `/hooks/agent` endpoint uses:
```json
{
  "message": "...",
  "agentId": "...",
  "channel": "slack",
  "to": "channel:C123",
  "timeoutSeconds": 120
}
```

`thread_id` and `user_id` are **not** top-level fields in OpenClaw's documented webhook payload. OpenClaw authenticates via `Authorization: Bearer <token>` header — not HMAC signatures. The `_verify_signature(payload, signature)` approach doesn't correspond to anything in OpenClaw's auth model.

---

#### Issue 21 — `connect()` is empty and no webhook endpoint is registered [HIGH — incomplete]

The `connect()` method only logs. No FastAPI route is created to receive incoming requests from OpenClaw. For OpenClaw to send messages to OmniHarness, a route must be registered — either in `app/gateway/routers/` (following the pattern of existing routers), or by configuring OpenClaw to use ACP (its native stdio protocol) instead of webhooks.

Additionally, the channel is never registered in `config.yaml` or `service.py`. Looking at how Telegram and Discord are configured, a `channels: openclaw: {...}` section is required in config.

---

### Page 2: `ThreadMessage.tsx`

#### Issue 22 — Emoji usage

`🚨` and `✂️` in badge content violate the project's no-emoji convention.

#### Issue 23 — Wrong color palette

Uses `slate-800`, `slate-900`, `slate-200`, `green-400`. The entire project uses `stone-*` colors (confirmed across landing page, workspace components, and Tailwind config). Consistency requires `stone-800`, `stone-400`, etc.

#### Issue 24 — Wrong component directory

Workspace components live in `frontend/src/components/workspace/`. A file at `frontend/src/components/ThreadMessage.tsx` won't be discovered by the existing import graph.

#### Issue 25 — Not wired into the existing message rendering system

Creating the file has no visible effect. It must be imported and used within the actual message rendering pipeline in the workspace components. The existing LangGraph streaming + workspace message components don't reference this new component.

#### Issue 26 — Unnecessary React import

`import React from 'react'` is not needed in React 19 (this project's version). The new JSX transform handles it automatically.

---

## Consolidated Issue Table

| # | Stage | File | Issue | Severity |
|---|-------|------|-------|----------|
| 1 | S1P1 | `app/tools/openclaude.py` + `config.yaml` | Config must reference instance, not class (`openclaude_coder = OpenClaudeCodingTool()`) | Critical |
| 2 | S1P1 | `app/tools/openclaude.py` | `_run()` sync method missing | High |
| 3 | S1P1 | `app/tools/openclaude.py` | Command injection via unquoted `prompt` in shell string | Critical |
| 4 | S1P1 | `app/tools/openclaude.py` | Zombie process: `process.communicate()` not awaited after `kill()` | Medium |
| 5 | S1P1 | `app/tools/openclaude.py` | `workspace_dir="/mnt/acp-workspace"` is container-internal; gateway process cannot `cwd` to it | High |
| 6 | S1P1 | `app/tools/openclaude.py` | `args_schema` missing; `run_manager` may appear as LLM-visible parameter | Medium |
| 7 | S1P1 | Docker image | `openclaude` npm package not installed in gateway container | High |
| 8 | S1P2 | `config.yaml` | `group: sandbox` — no such tool group defined | Medium |
| 9 | S1P2 | `config.yaml` | `{thread_id}` in static `VolumeMountConfig.host_path` is not substituted | Low |
| 10 | S2P1 | `app/middlewares/truncation.py` | Must extend `AgentMiddleware`; duck-typing fails `extra_middleware` isinstance check | Critical |
| 11 | S2P1 | `app/middlewares/truncation.py` | `before_model` missing `runtime: Runtime` parameter | Critical |
| 12 | S2P1 | `app/middlewares/truncation.py` | `@Prev` takes class reference, not string | Critical |
| 13 | S2P1 | `app/middlewares/truncation.py` | In-place `msg.content` mutation may silently fail in LangGraph state | Medium |
| 14 | S2P2 | `app/callbacks/loop_detection.py` | Duplicates existing `LoopDetectionMiddleware` (#17 in chain) | Redundancy |
| 15 | S2P2 | `app/callbacks/loop_detection.py` | Exception in `on_llm_new_token` aborts run destructively; no graceful stream sever in LangGraph | High |
| 16 | S3P1 | `config.yaml` | `{event_history}` should be `{messages}` — LangChain injects `messages=` | Critical |
| 17 | S4P1 | `app/channels/openclaw.py` | OpenClaw is Node.js, not Rust ("fast-rust daemon" = RustClaw, a different project) | Factual |
| 18 | S4P1 | `app/channels/openclaw.py` | Class is `Channel`, not `BaseChannel` — ImportError | Critical |
| 19 | S4P1 | `app/channels/openclaw.py` | `super().__init__(message_bus)` — wrong signature (missing `name`, `config`) | Critical |
| 20 | S4P1 | `app/channels/openclaw.py` | `message_bus.publish(topic, data)` doesn't exist — use `publish_inbound(InboundMessage)` | Critical |
| 21 | S4P1 | `app/channels/openclaw.py` | Webhook payload `{thread_id, user_id, message}` doesn't match OpenClaw's `{message, agentId, channel, to}` | High |
| 22 | S4P1 | `app/channels/openclaw.py` | OpenClaw uses bearer token auth, not HMAC signatures | High |
| 23 | S4P1 | `app/channels/openclaw.py` | `connect()` empty; no FastAPI route or service.py registration | High |
| 24 | S4P2 | `frontend/src/components/ThreadMessage.tsx` | Emojis, wrong color palette (slate vs stone), wrong directory, not wired into message pipeline | Medium |

---

## Confirmed-Correct Architecture Points

These parts of the guide are accurate and should be preserved as-is:

- Wrapping OpenClaude in `app/tools/` (not the harness layer) — correct per the harness/app boundary enforced by `test_harness_boundary.py`
- `CLAUDE_CODE_USE_OPENAI=1` env var — documented in openclaude's `advanced-setup.md`
- `_strip_ansi()` as the authoritative ANSI remover (since `NO_COLOR` is unreliable)
- `asyncio.wait_for` timeout pattern for subprocess
- `subagents.custom_agents` as the correct config key for user-defined agent types
- `replicas` and `idle_timeout` as valid `SandboxConfig` fields
- `AllowlistProvider` at `omniharness.guardrails.builtin:AllowlistProvider` — confirmed exact path
- `allowed_tools: null` correctly means "allow all tools" in `AllowlistProvider`
- `keep.type: tokens` as a valid summarization retention policy
- `summary_prompt` as a real, overridable config field in `SummarizationConfig`
- `@Prev`/`@Next` decorator mechanism for middleware positioning — real and supported
- `extra_middleware` parameter on `create_omniharness_agent` — real SDK entry point
- `summarization=False | AgentMiddleware` pattern in `RuntimeFeatures` — correct

---

## Recommended Implementation Order

Given the issue severity table, this is the suggested order to tackle implementation:

1. **Fix tool registration** (Issues 1–7): Get `OpenClaudeCodingTool` to a state where it loads and runs safely — instance export, `_run`, `args_schema`, `shlex.quote`, zombie-process fix, container workspace path resolution
2. **Fix config** (Issues 8–9): Define the tool group, remove the static `{thread_id}` mount
3. **Fix truncation middleware** (Issues 10–13): Extend `AgentMiddleware`, fix `before_model` signature, fix `@Prev` import, use proper state replacement
4. **Reconsider streaming loop detection** (Issues 14–15): Evaluate whether it adds value on top of existing `LoopDetectionMiddleware`; if kept, use `after_model` instead of `on_llm_new_token`
5. **Fix summarization prompt** (Issue 16): Replace `{event_history}` with `{messages}`
6. **Fix OpenClaw channel** (Issues 17–23): Correct base class, constructor, `publish_inbound` call, map OpenClaw's actual payload fields, implement bearer token verification, register FastAPI route and service.py entry
7. **Fix frontend component** (Issue 24): Stone colors, no emojis, correct directory, wire into existing workspace message pipeline
