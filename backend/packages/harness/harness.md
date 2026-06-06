# OmniHarness Package Reference

`omniharness` is a LangGraph-based AI super-agent framework. It provides a
complete pipeline from raw HTTP requests to tool-executing agents, with
sandboxed code execution, persistent per-user memory, dynamic skill loading,
MCP server integration, subagent delegation, and an extensible middleware
system. The package is a publishable library (`omniharness-harness`) that
must never import from the application layer (`app.*`).

---

## Table of Contents

1. [Package Overview & Module Map](#1-package-overview--module-map)
2. [Module Reference by Subsystem](#2-module-reference-by-subsystem)
   - [2.1 Config](#21-config)
   - [2.2 Models](#22-models)
   - [2.3 Agents — Lead Agent](#23-agents--lead-agent)
   - [2.4 Agents — Middlewares](#24-agents--middlewares)
   - [2.5 Memory](#25-memory)
   - [2.6 Sandbox](#26-sandbox)
   - [2.7 AIO Sandbox (Community)](#27-aio-sandbox-community)
   - [2.8 Tools](#28-tools)
   - [2.9 Community Tools](#29-community-tools)
   - [2.10 Subagents](#210-subagents)
   - [2.11 Skills](#211-skills)
   - [2.12 MCP](#212-mcp)
   - [2.13 Runtime](#213-runtime)
   - [2.14 Persistence](#214-persistence)
   - [2.15 Guardrails](#215-guardrails)
   - [2.16 Tracing](#216-tracing)
   - [2.17 Reflection](#217-reflection)
   - [2.18 Client](#218-client)
3. [Call Graph / Dependency Map](#3-call-graph--dependency-map)
4. [Data Flow Diagrams](#4-data-flow-diagrams)
5. [Configuration Schema](#5-configuration-schema)
6. [Public API Entry Points](#6-public-api-entry-points)

---

## 1. Package Overview & Module Map

```
omniharness/
├── config/                  # All Pydantic config classes + singletons
│   ├── app_config.py        # AppConfig root, get_app_config(), push/pop stack
│   ├── model_config.py      # ModelConfig — per-LLM settings
│   ├── sandbox_config.py    # SandboxConfig, VolumeMountConfig
│   ├── agents_config.py     # AgentConfig, load_agent_config(), list_custom_agents()
│   ├── subagents_config.py  # SubagentsAppConfig, CustomSubagentConfig
│   ├── memory_config.py     # MemoryConfig
│   ├── skills_config.py     # SkillsConfig, get_skills_path()
│   ├── tool_config.py       # ToolConfig, ToolGroupConfig
│   ├── tool_search_config.py# ToolSearchConfig
│   ├── summarization_config.py # SummarizationConfig, ContextSize
│   ├── title_config.py      # TitleConfig
│   ├── token_usage_config.py# TokenUsageConfig
│   ├── tracing_config.py    # TracingConfig, LangSmithTracingConfig, LangfuseTracingConfig
│   ├── guardrails_config.py # GuardrailsConfig, GuardrailProviderConfig
│   ├── loop_detection_config.py # LoopDetectionConfig, ToolFreqOverride
│   ├── acp_config.py        # ACPAgentConfig, get_acp_agents()
│   ├── agents_api_config.py # AgentsApiConfig
│   ├── checkpointer_config.py   # CheckpointerConfig
│   ├── database_config.py   # DatabaseConfig
│   ├── extensions_config.py # ExtensionsConfig (MCP + skills state), singletons
│   ├── paths.py             # Paths — all filesystem paths + virtual→host translation
│   ├── runtime_paths.py     # project_root(), runtime_home(), resolve_path()
│   ├── run_events_config.py # RunEventsConfig
│   ├── skill_evolution_config.py # SkillEvolutionConfig
│   └── stream_bridge_config.py # StreamBridgeConfig
│
├── models/                  # LLM providers + factory
│   ├── factory.py           # create_chat_model()
│   ├── claude_provider.py   # ClaudeChatModel (OAuth, prompt caching, thinking budget)
│   ├── vllm_provider.py     # VllmChatModel (reasoning field preservation)
│   ├── openai_codex_provider.py # CodexChatModel (Responses API)
│   ├── patched_deepseek.py  # PatchedChatDeepSeek
│   ├── patched_minimax.py   # PatchedChatMiniMax
│   ├── patched_openai.py    # PatchedChatOpenAI (Gemini thought_signature)
│   └── credential_loader.py # load_claude_code_credential(), load_codex_cli_credential()
│
├── agents/
│   ├── lead_agent/
│   │   ├── agent.py         # make_lead_agent(), _build_middlewares()
│   │   └── prompt.py        # apply_prompt_template(), get_skills_prompt_section()
│   ├── factory.py           # create_omniharness_agent() SDK factory
│   ├── features.py          # RuntimeFeatures flags, Next/Prev decorators
│   ├── thread_state.py      # ThreadState, SandboxState, ThreadDataState
│   ├── middlewares/
│   │   ├── tool_error_handling_middleware.py  # + build_*_runtime_middlewares()
│   │   ├── thread_data_middleware.py
│   │   ├── uploads_middleware.py
│   │   ├── sandbox_audit_middleware.py
│   │   ├── dangling_tool_call_middleware.py
│   │   ├── llm_error_handling_middleware.py
│   │   ├── deferred_tool_filter_middleware.py
│   │   ├── subagent_limit_middleware.py
│   │   ├── loop_detection_middleware.py
│   │   ├── clarification_middleware.py
│   │   ├── memory_middleware.py
│   │   ├── summarization_middleware.py
│   │   ├── title_middleware.py
│   │   ├── todo_middleware.py
│   │   ├── token_usage_middleware.py
│   │   └── view_image_middleware.py
│   └── memory/
│       ├── updater.py       # MemoryUpdater, CRUD helpers
│       ├── queue.py         # MemoryUpdateQueue, ConversationContext
│       ├── storage.py       # MemoryStorage ABC, FileMemoryStorage
│       ├── prompt.py        # memory update prompt templates
│       ├── message_processing.py
│       └── summarization_hook.py
│
├── sandbox/
│   ├── sandbox.py           # Sandbox ABC
│   ├── sandbox_provider.py  # SandboxProvider ABC + get/set/reset singletons
│   ├── middleware.py        # SandboxMiddleware (before/after_agent lifecycle)
│   ├── tools.py             # bash, ls, read_file, write_file, str_replace, glob, grep
│   ├── search.py            # find_glob_matches(), find_grep_matches(), GrepMatch
│   ├── security.py          # is_host_bash_allowed(), uses_local_sandbox_provider()
│   ├── file_operation_lock.py # get_file_operation_lock() — per-path WeakValueDict
│   ├── exceptions.py        # SandboxError hierarchy
│   └── local/
│       ├── local_sandbox.py          # LocalSandbox — subprocess execution
│       ├── local_sandbox_provider.py # LocalSandboxProvider — singleton
│       └── list_dir.py               # list_dir() tree helper
│
├── community/
│   └── aio_sandbox/
│       ├── aio_sandbox.py          # AioSandbox — agent-sandbox HTTP client
│       ├── aio_sandbox_provider.py # AioSandboxProvider — Docker orchestration
│       ├── backend.py              # SandboxBackend ABC, wait_for_sandbox_ready()
│       ├── local_backend.py        # LocalContainerBackend
│       ├── remote_backend.py       # RemoteSandboxBackend
│       └── sandbox_info.py         # SandboxInfo dataclass
│
├── tools/
│   ├── tools.py             # get_available_tools()
│   └── builtins/
│       ├── present_file_tool.py       # present_files tool
│       ├── clarification_tool.py      # ask_clarification tool
│       ├── task_tool.py               # task tool (async subagent delegation)
│       ├── view_image_tool.py         # view_image tool
│       ├── tool_search.py             # tool_search + DeferredToolRegistry
│       ├── setup_agent_tool.py        # setup_agent (bootstrap-only)
│       ├── update_agent_tool.py       # update_agent (custom agent self-update)
│       └── invoke_acp_agent_tool.py   # invoke_acp_agent tool
│
├── community/
│   ├── tavily/tools.py         # web_search, web_fetch
│   ├── jina_ai/tools.py        # jina_reader fetch
│   ├── firecrawl/tools.py      # firecrawl scrape
│   ├── serper/tools.py         # serper web search
│   ├── ddg_search/tools.py     # DuckDuckGo search
│   ├── image_search/tools.py   # image search
│   └── exa/tools.py            # Exa search
│
├── subagents/
│   ├── executor.py          # SubagentExecutor, SubagentResult, SubagentStatus
│   ├── registry.py          # get_subagent_config(), list_subagents()
│   ├── config.py            # SubagentConfig, resolve_subagent_model_name()
│   └── builtins/            # general-purpose, bash built-in subagent configs
│
├── skills/
│   ├── types.py             # Skill dataclass, SkillCategory enum
│   ├── parser.py            # parse_skill_file(), parse_allowed_tools()
│   ├── installer.py         # safe_extract_skill_archive(), SkillAlreadyExistsError
│   ├── tool_policy.py       # filter_tools_by_skill_allowed_tools()
│   ├── validation.py        # skill validation helpers
│   ├── security_scanner.py  # scan_skill_content()
│   └── storage/
│       ├── skill_storage.py         # SkillStorage ABC
│       └── local_skill_storage.py   # LocalSkillStorage
│
├── mcp/
│   ├── client.py            # build_server_params(), build_servers_config()
│   ├── tools.py             # get_mcp_tools() — async MultiServerMCPClient
│   ├── cache.py             # get_cached_mcp_tools(), initialize_mcp_tools(), mtime cache
│   └── oauth.py             # OAuthTokenManager, build_oauth_tool_interceptor()
│
├── runtime/
│   ├── user_context.py      # get_effective_user_id(), set/reset_current_user(), AUTO sentinel
│   ├── converters.py        # message/state serialization helpers
│   ├── serialization.py     # serialize() for LangGraph stream chunks
│   ├── journal.py           # RunJournal — LangChain callback handler for events
│   ├── checkpointer/
│   │   ├── provider.py      # get_checkpointer() — memory/sqlite/postgres
│   │   └── async_provider.py
│   ├── store/               # LangGraph store provider (memory/sqlite/postgres)
│   ├── stream_bridge/
│   │   ├── base.py          # StreamBridge ABC, StreamEvent, END_SENTINEL
│   │   └── memory.py        # InMemoryStreamBridge
│   ├── events/store/        # RunEvent persistence (memory/db/jsonl)
│   └── runs/
│       ├── schemas.py       # RunStatus, DisconnectMode enums
│       ├── manager.py       # RunManager — in-memory run registry + RunStore backing
│       └── worker.py        # run_agent() — core async execution coroutine
│
├── persistence/
│   ├── base.py              # SQLAlchemy declarative Base
│   ├── engine.py            # get_engine(), migrations
│   ├── feedback/
│   │   ├── model.py         # FeedbackRow ORM model
│   │   └── sql.py           # FeedbackRepository SQL implementation
│   ├── run/
│   │   ├── model.py         # RunRow ORM model
│   │   └── sql.py           # RunRepository SQL implementation
│   ├── thread_meta/         # ThreadMetaRepository (title, status)
│   └── user/
│       └── model.py         # UserRow ORM model
│
├── guardrails/
│   ├── provider.py          # GuardrailProvider protocol, GuardrailRequest/Decision/Reason
│   ├── builtin.py           # AllowlistProvider
│   └── middleware.py        # GuardrailMiddleware
│
├── tracing/
│   └── factory.py           # build_tracing_callbacks() — LangSmith + Langfuse
│
├── reflection/
│   └── resolvers.py         # resolve_variable(), resolve_class()
│
├── uploads/
│   └── manager.py           # upload helpers, enrich_file_listing()
│
├── utils/
│   ├── time.py              # now_iso()
│   └── (network, readability helpers)
│
└── client.py                # OmniHarnessClient — embedded Python client
```

---

## 2. Module Reference by Subsystem

---

### 2.1 Config

All configuration classes use **Pydantic v2** (`BaseModel`). The central
singleton `AppConfig` is loaded once from `config.yaml`, then cached with
mtime-based auto-reload so process restarts are not required after edits.
A ContextVar stack allows per-request overrides without globals.

---

#### `omniharness/config/app_config.py`

**Purpose**: Root configuration class and singleton management.

##### `class AppConfig(BaseModel)`

Top-level schema that aggregates all sub-configs.

| Field | Type | Default | Description |
|---|---|---|---|
| `models` | `list[ModelConfig]` | `[]` | Ordered list of LLM configurations |
| `tools` | `list[ToolConfig]` | `[]` | Config-defined tools with class paths |
| `tool_groups` | `list[ToolGroupConfig]` | `[]` | Logical tool groupings |
| `sandbox` | `SandboxConfig \| None` | `None` | Sandbox provider config |
| `skills` | `SkillsConfig` | default | Skills directory config |
| `title` | `TitleConfig` | default | Auto-title generation config |
| `summarization` | `SummarizationConfig` | default | Context summarization config |
| `memory` | `MemoryConfig` | default | Memory system config |
| `subagents` | `SubagentsAppConfig` | default | Subagent config |
| `tool_search` | `ToolSearchConfig` | default | Tool search / deferred tools config |
| `tracing` | `TracingConfig \| None` | `None` | Distributed tracing config |
| `guardrails` | `GuardrailsConfig` | default | Guardrail config |
| `loop_detection` | `LoopDetectionConfig` | default | Loop detection config |
| `token_usage` | `TokenUsageConfig` | default | Token usage logging config |
| `checkpointer` | `CheckpointerConfig` | default | LangGraph checkpointer backend |
| `database` | `DatabaseConfig` | default | SQL persistence backend |
| `run_events` | `RunEventsConfig` | default | Run event store config |
| `stream_bridge` | `StreamBridgeConfig` | default | SSE stream bridge config |
| `skill_evolution` | `SkillEvolutionConfig` | default | Skill evolution (LLM-based moderation) |
| `agents_api` | `AgentsApiConfig` | default | Agents API compatibility |
| `acp_agents` | `dict[str, ACPAgentConfig]` | `{}` | External ACP agent definitions |
| `config_version` | `int \| None` | `None` | Config schema version |

Key methods:
- `get_model_config(name: str) -> ModelConfig | None` — look up a model by name
- `get_tool_config(name: str) -> ToolConfig | None` — look up a tool by name
- `classmethod from_file(config_path: Path | None = None) -> AppConfig` — load YAML,
  apply env-var substitution (`$VAR`), call `_apply_singleton_configs()`

##### Functions

```python
def get_app_config(config_path: str | None = None) -> AppConfig
```
Returns the cached singleton. Auto-reloads if the file's mtime has increased
since last load. Thread-safe via a module-level lock.

```python
def reload_app_config(config_path: str | None = None) -> AppConfig
```
Force-invalidates cache and reloads from disk.

```python
def push_current_app_config(config: AppConfig) -> None
def pop_current_app_config() -> None
```
ContextVar stack for per-request config overrides. Used by the gateway to
inject per-tenant configs without touching the global singleton.

---

#### `omniharness/config/model_config.py`

##### `class ModelConfig(BaseModel)`

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | required | Unique identifier used in `model_name` config key |
| `use` | `str` | required | Class path e.g. `"langchain_openai:ChatOpenAI"` |
| `display_name` | `str \| None` | `None` | Human-readable name |
| `description` | `str \| None` | `None` | Model description |
| `supports_thinking` | `bool` | `False` | Whether extended thinking is supported |
| `supports_vision` | `bool` | `False` | Whether image input is supported |
| `supports_reasoning_effort` | `bool` | `False` | Whether `reasoning_effort` param is supported |
| `when_thinking_enabled` | `dict \| None` | `None` | Extra kwargs merged when thinking=True |
| `when_thinking_disabled` | `dict \| None` | `None` | Extra kwargs merged when thinking=False |
| `thinking` | `dict \| None` | `None` | Shortcut: merged into `when_thinking_enabled.thinking` |
| `use_responses_api` | `bool \| None` | `None` | Force OpenAI Responses API endpoint |
| `output_version` | `str \| None` | `None` | Output version for OpenAI Responses API |

All extra fields are forwarded to the LLM constructor via `model_dump(extra="allow")`.

---

#### `omniharness/config/sandbox_config.py`

##### `class SandboxConfig(BaseModel)`

| Field | Type | Default | Description |
|---|---|---|---|
| `use` | `str` | required | Provider class path |
| `allow_host_bash` | `bool` | `False` | Allow bash on host (local provider only) |
| `image` | `str \| None` | `None` | Docker image (AioSandboxProvider) |
| `port` | `int \| None` | `None` | Base port for containers |
| `replicas` | `int \| None` | `None` | Max concurrent containers (default 3) |
| `container_prefix` | `str \| None` | `None` | Container name prefix |
| `idle_timeout` | `int \| None` | `None` | Seconds before idle sandbox eviction (default 600) |
| `mounts` | `list[VolumeMountConfig]` | `[]` | Extra volume mounts |
| `environment` | `dict[str, str]` | `{}` | Env vars injected into containers |
| `bash_output_max_chars` | `int` | `20000` | Max chars from bash output (middle-truncated) |
| `read_file_output_max_chars` | `int` | `50000` | Max chars from read_file output (head-truncated) |
| `ls_output_max_chars` | `int` | `20000` | Max chars from ls output (head-truncated) |

`model_config = ConfigDict(extra="allow")` — unknown fields pass through to provider.

##### `class VolumeMountConfig(BaseModel)`

| Field | Type | Default | Description |
|---|---|---|---|
| `host_path` | `str` | required | Absolute path on the host machine |
| `container_path` | `str` | required | Absolute path inside the container |
| `read_only` | `bool` | `False` | Whether the mount is read-only |

---

#### `omniharness/config/agents_config.py`

##### `class AgentConfig(BaseModel)`

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | required | Agent identifier (`AGENT_NAME_PATTERN = r"^[A-Za-z0-9-]+$"`) |
| `description` | `str \| None` | `None` | Agent description shown to users |
| `model` | `str \| None` | `None` | Override model name |
| `tool_groups` | `list[str] \| None` | `None` | Restrict to specific tool groups |
| `skills` | `list[str] \| None` | `None` | Override skill allowlist |

##### Functions

```python
def resolve_agent_dir(agent_name: str, *, user_id: str | None = None) -> Path | None
```
Returns per-user path `{base_dir}/users/{user_id}/agents/{agent_name}/` with
read-only fallback to legacy `{base_dir}/agents/{agent_name}/`.

```python
def load_agent_config(agent_name: str, *, user_id: str | None = None) -> AgentConfig | None
def load_agent_soul(agent_name: str, *, user_id: str | None = None) -> str | None
def list_custom_agents(*, user_id: str | None = None) -> list[str]
```

---

#### `omniharness/config/subagents_config.py`

##### `class SubagentsAppConfig(BaseModel)`

| Field | Type | Default | Description |
|---|---|---|---|
| `timeout_seconds` | `int` | `900` | Default timeout for built-in subagents |
| `max_turns` | `int \| None` | `None` | Global max turns override for built-ins |
| `agents` | `dict[str, SubagentOverrideConfig]` | `{}` | Per-agent timeout/max_turns/model overrides |
| `custom_agents` | `dict[str, CustomSubagentConfig]` | `{}` | User-defined subagent types |

##### `class CustomSubagentConfig(BaseModel)`

| Field | Type | Default | Description |
|---|---|---|---|
| `description` | `str` | required | When the parent agent should delegate |
| `system_prompt` | `str` | `""` | System prompt |
| `tools` | `list[str] \| None` | `None` | Tool allowlist |
| `disallowed_tools` | `list[str] \| None` | `None` | Tool denylist |
| `skills` | `list[str] \| None` | `None` | Skill allowlist |
| `model` | `str` | `"inherit"` | Model name or `"inherit"` |
| `max_turns` | `int` | `50` | Max turns |
| `timeout_seconds` | `int` | `900` | Timeout |

---

#### `omniharness/config/memory_config.py`

##### `class MemoryConfig(BaseModel)`

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | `bool` | `True` | Enable memory extraction |
| `storage_path` | `str \| None` | `None` | Absolute path overrides per-user isolation |
| `storage_class` | `str` | `"...FileMemoryStorage"` | Class path for storage backend |
| `debounce_seconds` | `int` | `30` | Wait before processing conversation |
| `model_name` | `str \| None` | `None` | LLM for extraction (null = default) |
| `max_facts` | `int` | `100` | Maximum facts to store |
| `fact_confidence_threshold` | `float` | `0.7` | Minimum confidence to store a fact |
| `injection_enabled` | `bool` | `True` | Include memory in system prompt |
| `max_injection_tokens` | `int` | `2000` | Token budget for memory injection |

---

#### `omniharness/config/skills_config.py`

##### `class SkillsConfig(BaseModel)`

| Field | Type | Default | Description |
|---|---|---|---|
| `use` | `str \| None` | `None` | Storage class path (future extensibility) |
| `path` | `str \| None` | `None` | Host path to skills directory |
| `container_path` | `str` | `"/mnt/skills"` | Path inside sandbox containers |

```python
def get_skills_path() -> Path
```
Resolution order: `OMNI_HARNESS_SKILLS_PATH` env var → `config.skills.path` →
`{project_root}/skills` → `{project_root}/../skills`.

```python
def get_skill_container_path() -> str
```

---

#### `omniharness/config/summarization_config.py`

##### `class SummarizationConfig(BaseModel)`

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | `bool` | `False` | Enable context summarization |
| `model_name` | `str \| None` | `None` | LLM for summaries (null = default) |
| `trigger` | `ContextSize \| None` | `None` | When to trigger summarization |
| `keep` | `ContextSize \| None` | `None` | How much to keep after summarization |
| `trim_tokens_to_summarize` | `int` | `4000` | Don't summarize sections under this size |
| `summary_prompt` | `str \| None` | `None` | Custom prompt template |
| `preserve_recent_skill_count` | `int` | `5` | Recent skill bundles to preserve |
| `preserve_recent_skill_tokens` | `int` | `25000` | Token budget for skill preservation |
| `preserve_recent_skill_tokens_per_skill` | `int` | `5000` | Per-skill token budget |
| `skill_file_read_tool_names` | `list[str]` | `["read_file"]` | Tools that read skill content |

##### `class ContextSize(BaseModel)`

| Field | Type | Description |
|---|---|---|
| `type` | `"tokens" \| "messages" \| "fraction"` | Unit type |
| `value` | `int \| float` | Threshold value |

---

#### `omniharness/config/loop_detection_config.py`

##### `class LoopDetectionConfig(BaseModel)`

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | `bool` | `True` | Enable loop detection |
| `warn_threshold` | `int` | `3` | Identical call sets before warning |
| `hard_limit` | `int` | `5` | Identical call sets before hard stop |
| `window_size` | `int` | `20` | Message history window |
| `max_tracked_threads` | `int` | `100` | LRU cache size for per-thread state |
| `tool_freq_warn` | `int` | `30` | Per-tool call frequency warn threshold |
| `tool_freq_hard_limit` | `int` | `50` | Per-tool call frequency hard stop |
| `tool_freq_overrides` | `dict[str, ToolFreqOverride]` | `{}` | Per-tool overrides |

##### `class ToolFreqOverride(BaseModel)`

| Field | Type | Description |
|---|---|---|
| `warn` | `int \| None` | Per-tool warn threshold override |
| `hard_limit` | `int \| None` | Per-tool hard stop threshold override |

---

#### `omniharness/config/extensions_config.py`

Manages `extensions_config.json` (MCP servers + skill enabled state).
Separate from `config.yaml` so runtime changes via Gateway API are
detected by all processes through mtime invalidation.

##### `class ExtensionsConfig(BaseModel)`

| Field | Type | Default | Description |
|---|---|---|---|
| `mcp_servers` | `dict[str, McpServerConfig]` | `{}` | MCP server definitions |
| `skills` | `dict[str, SkillStateConfig]` | `{}` | Skill enabled states |

```python
def get_enabled_mcp_servers() -> dict[str, McpServerConfig]
classmethod from_file(config_path: Path | None = None) -> ExtensionsConfig
classmethod resolve_config_path() -> Path | None
```

##### `class McpServerConfig(BaseModel)`

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | `bool` | `True` | Whether this server is active |
| `type` | `"stdio" \| "sse" \| "http" \| None` | `None` | Transport type |
| `command` | `str \| None` | `None` | Executable for stdio transport |
| `args` | `list[str]` | `[]` | Command arguments |
| `env` | `dict[str, str]` | `{}` | Environment variables |
| `url` | `str \| None` | `None` | Server URL for SSE/HTTP transport |
| `headers` | `dict[str, str]` | `{}` | HTTP headers |
| `oauth` | `McpOAuthConfig \| None` | `None` | OAuth token config |
| `description` | `str \| None` | `None` | Human-readable description |

##### `class McpOAuthConfig(BaseModel)`

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | `bool` | `True` | Enable OAuth for this server |
| `token_url` | `str` | required | Token endpoint URL |
| `grant_type` | `"client_credentials" \| "refresh_token"` | required | OAuth grant type |
| `client_id` | `str \| None` | `None` | OAuth client ID |
| `client_secret` | `str \| None` | `None` | OAuth client secret |
| `refresh_token` | `str \| None` | `None` | Refresh token (refresh_token grant) |
| `scope` | `str \| None` | `None` | OAuth scope |
| `audience` | `str \| None` | `None` | Token audience |
| `token_field` | `str` | `"access_token"` | JSON field name for token |
| `expires_in_field` | `str` | `"expires_in"` | JSON field name for expiry seconds |
| `refresh_skew_seconds` | `int` | `60` | Refresh this many seconds before expiry |
| `extra_token_params` | `dict` | `{}` | Additional POST body params |

```python
def get_extensions_config() -> ExtensionsConfig  # singleton
def reload_extensions_config() -> ExtensionsConfig  # force reload
```

---

#### `omniharness/config/paths.py`

##### `class Paths`

Central filesystem path resolution. Per-user layout:
`{base_dir}/users/{user_id}/...`; legacy fallback: `{base_dir}/...`.

```python
VIRTUAL_PATH_PREFIX = "/mnt/user-data"
```

Key methods:
```python
def user_dir(user_id: str) -> Path
def user_memory_file(user_id: str) -> Path
def user_agent_memory_file(user_id: str, agent_name: str) -> Path
def user_agents_dir(user_id: str) -> Path
def user_agent_dir(user_id: str, agent_name: str) -> Path
def thread_dir(thread_id: str, *, user_id: str | None = None) -> Path
def sandbox_work_dir(thread_id: str, *, user_id: str | None = None) -> Path
def sandbox_uploads_dir(thread_id: str, *, user_id: str | None = None) -> Path
def sandbox_outputs_dir(thread_id: str, *, user_id: str | None = None) -> Path
def acp_workspace_dir(thread_id: str, *, user_id: str | None = None) -> Path
def ensure_thread_dirs(thread_id: str, *, user_id: str | None = None) -> None
def delete_thread_dir(thread_id: str, *, user_id: str | None = None) -> None
def resolve_virtual_path(thread_id: str, virtual_path: str, *, user_id: str | None = None) -> Path
```

`host_sandbox_work_dir`, `host_sandbox_uploads_dir`, `host_sandbox_outputs_dir`,
`host_acp_workspace_dir` return the same paths prefixed with
`OMNI_HARNESS_HOST_BASE_DIR` for Docker-in-Docker (DooD) scenarios.

```python
def get_paths() -> Paths  # cached singleton
```

---

#### `omniharness/config/runtime_paths.py`

```python
def project_root() -> Path  # OMNI_HARNESS_PROJECT_ROOT env var or cwd
def runtime_home() -> Path  # OMNI_HARNESS_HOME env var or project_root/.omni-harness
def resolve_path(value, *, base=None) -> Path  # resolve relative paths against project_root
def existing_project_file(names: tuple[str, ...]) -> Path | None
```

---

### 2.2 Models

---

#### `omniharness/models/factory.py`

##### `create_chat_model(name, thinking_enabled, *, app_config, **kwargs) -> BaseChatModel`

Central factory for instantiating any configured LLM. Uses `resolve_class()` on
`model_config.use` to dynamically load the provider class.

Key behaviors:
- Merges `when_thinking_enabled` / `when_thinking_disabled` dicts into
  constructor kwargs based on `thinking_enabled` flag
- `thinking` shortcut field merged into `when_thinking_enabled["thinking"]`
- vLLM disable path: injects `{"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}`
- Native Anthropic disable path: injects `{"thinking": {"type": "disabled"}}`
- OpenAI Responses API disable: injects `{"extra_body": {"thinking": {"type": "disabled"}}}`
  plus `"reasoning_effort": "minimal"`
- `CodexChatModel` special-casing: maps `thinking_enabled=True` to `reasoning_effort="medium"`
  (or explicit effort if provided), strips `max_tokens`
- Auto-enables `stream_usage=True` on `ChatOpenAI` subclasses with custom `base_url`
- Attaches tracing callbacks from `build_tracing_callbacks()`

---

#### `omniharness/models/claude_provider.py`

##### `class ClaudeChatModel(ChatAnthropic)`

Extends `langchain_anthropic.ChatAnthropic` with:
- **OAuth detection**: if API key starts with `sk-ant-oat`, switches to Bearer
  authentication via `_patch_client_oauth()`
- **Prompt caching**: inserts up to 4 `"cache_control": {"type": "ephemeral"}`
  breakpoints in the system message via `_apply_prompt_caching()`
- **Thinking budget**: auto-sets `budget_tokens` to 80% of `max_tokens` via
  `_apply_thinking_budget()`
- **Retry**: exponential backoff (1s → 8s cap) on transient API errors

---

#### `omniharness/models/vllm_provider.py`

##### `class VllmChatModel(ChatOpenAI)`

Wraps vLLM 0.19.0 OpenAI-compatible endpoints. Preserves the non-standard
`reasoning` field (content) in:
- Streaming responses (aggregates delta chunks)
- Non-streaming full responses
- Multi-turn payloads (re-injects into prior assistant messages)

Helper: `_normalize_vllm_chat_template_kwargs(kwargs)` — maps legacy
`thinking` → `enable_thinking` in `extra_body.chat_template_kwargs`.

---

#### `omniharness/models/openai_codex_provider.py`

##### `class CodexChatModel(BaseChatModel)`

Direct integration with chatgpt.com Responses API via SSE streaming.
Auto-loads credentials from `~/.codex/auth.json` or env vars.

Methods:
- `_stream_response(messages, config, **kwargs)` — async SSE generator
- `_convert_messages(messages) -> (instructions, input_items)` — converts
  LangChain messages to Responses API format
- `_parse_response(raw) -> AIMessage` — extracts text and tool calls

---

#### `omniharness/models/credential_loader.py`

```python
@dataclass
class ClaudeCodeCredential:
    access_token: str
    refresh_token: str | None
    expiry: datetime | None

@dataclass
class CodexCliCredential:
    access_token: str
    token_type: str

def load_claude_code_credential() -> ClaudeCodeCredential | None
    # Resolution: ANTHROPIC_ACCESS_TOKEN env var → FD (file descriptor) → ~/.claude/credentials

def load_codex_cli_credential() -> CodexCliCredential | None
    # From ~/.codex/auth.json

def is_oauth_token(token: str) -> bool
    # Returns True if token starts with "sk-ant-oat"
```

---

### 2.3 Agents — Lead Agent

---

#### `omniharness/agents/thread_state.py`

##### `class ThreadState(AgentState)` (TypedDict)

Extends LangGraph's `AgentState` with:

| Key | Type | Reducer | Description |
|---|---|---|---|
| `sandbox` | `SandboxState \| None` | replace | `{"sandbox_id": str}` |
| `thread_data` | `ThreadDataState \| None` | replace | `{"workspace_path", "uploads_path", "outputs_path"}` |
| `title` | `str \| None` | replace | Auto-generated thread title |
| `artifacts` | `list[str]` | `merge_artifacts()` | Presented file paths (deduplicated) |
| `todos` | `list \| None` | replace | Active todo list |
| `uploaded_files` | `list[dict] \| None` | replace | Uploaded file metadata |
| `viewed_images` | `dict[str, ViewedImageData]` | `merge_viewed_images()` | Base64 images cache; empty dict = clear all |

`merge_artifacts(a, b)` — deduplicates while preserving order.
`merge_viewed_images(a, b)` — merges dicts; empty `b` clears existing.

---

#### `omniharness/agents/lead_agent/agent.py`

##### `make_lead_agent(config: RunnableConfig) -> CompiledGraph`

LangGraph graph factory registered in `langgraph.json`. Called once per
request; returns a compiled agent graph.

Internal flow:
1. Extracts `model_name`, `thinking_enabled`, `is_plan_mode`, `subagent_enabled`,
   `is_bootstrap`, `agent_name` from `config.configurable`
2. Resolves `AppConfig` (from `push_current_app_config` stack or singleton)
3. Calls `_make_lead_agent()` which:
   - Creates the LLM via `create_chat_model()`
   - Loads tools via `get_available_tools()`
   - Applies system prompt via `apply_prompt_template()`
   - Assembles middleware chain via `_build_middlewares()`
   - Returns `create_agent(model, tools, middleware, system_prompt, state_schema=ThreadState)`

##### `_build_middlewares(config, *, model_name, agent_name, custom_middlewares) -> list[AgentMiddleware]`

Assembles the 18-middleware ordered chain (see §2.4 for details).

---

#### `omniharness/agents/lead_agent/prompt.py`

##### `apply_prompt_template(...) -> str`

Builds the full system prompt string. Sections injected:
- Current date/time
- `<memory>` — top 15 facts + context summaries (if injection enabled)
- `<skills>` — enabled skill paths with descriptions
- `<subagents>` — available subagent types (if subagent enabled)
- `<deferred-tools>` — names of tools hidden behind tool_search (if enabled)
- `<acp-agents>` — ACP agent descriptions

```python
@lru_cache(maxsize=1)
def get_skills_prompt_section(
    available_skills: frozenset[str] | None = None,
) -> str
```
Cached with background refresh thread for stale-while-revalidate behavior.

---

#### `omniharness/agents/factory.py`

##### `create_omniharness_agent(...) -> CompiledGraph`

Pure-Python SDK factory that does not require LangGraph config plumbing.
Accepts a `RuntimeFeatures` dataclass and assembles a middleware chain
in 14 canonical steps.

```python
@dataclass
class RuntimeFeatures:
    sandbox: bool = True
    memory: bool = False
    summarization: bool = False
    subagent: bool = False
    vision: bool = False
    auto_title: bool = False
    guardrail: bool = False
    loop_detection: bool = True
```

`_insert_extra(chain, extras)` — injects custom middlewares at `@Next(anchor)` or
`@Prev(anchor)` positions relative to named anchor middleware classes.

---

### 2.4 Agents — Middlewares

All middlewares extend `AgentMiddleware[StateT]` from LangGraph. They hook
into `before_agent`, `after_agent`, `before_model`, `after_model`,
`wrap_model_call`, and `wrap_tool_call` lifecycle points.

The canonical assembly order is (lowest to highest in the call stack):

| # | Middleware | Hook points | Description |
|---|---|---|---|
| 1 | `ThreadDataMiddleware` | `before_agent` | Creates per-thread dirs; stamps `run_id` + `timestamp` on last HumanMessage |
| 2 | `UploadsMiddleware` | `before_agent` | Injects `<uploaded_files>` block into last HumanMessage |
| 3 | `SandboxMiddleware` | `before_agent`, `after_agent` | Acquires sandbox on first call; releases on `after_agent` |
| 4 | `DanglingToolCallMiddleware` | `wrap_model_call` | Inserts synthetic `ToolMessage("[Tool call was interrupted]")` for abandoned tool_calls |
| 5 | `LLMErrorHandlingMiddleware` | `wrap_model_call` | 3-attempt retry with 1→8s backoff; circuit breaker (closed→open→half-open) |
| 6 | `GuardrailMiddleware` | `wrap_tool_call` | Calls `GuardrailProvider.aevaluate()`; returns error ToolMessage on deny (optional) |
| 7 | `SandboxAuditMiddleware` | `wrap_tool_call` | Classifies bash commands as block/warn/pass; security patterns |
| 8 | `ToolErrorHandlingMiddleware` | `wrap_tool_call` | Converts tool exceptions to error ToolMessages |
| 9 | `OmniHarnessSummarizationMiddleware` | `before_model` | Compresses context; skill rescue logic (optional) |
| 10 | `TodoMiddleware` | `before_model`, `after_model` | Injects reminder if todos scrolled out; prevents premature EXIT (optional) |
| 11 | `TokenUsageMiddleware` | `after_model` | Logs + annotates token usage with step kind (optional) |
| 12 | `TitleMiddleware` | `after_agent` | Generates title after first exchange (optional) |
| 13 | `MemoryMiddleware` | `after_agent` | Enqueues conversation for async memory update |
| 14 | `ViewImageMiddleware` | `before_model` | Injects base64 image blocks for `view_image` results (optional) |
| 15 | `DeferredToolFilterMiddleware` | `before_model` | Strips deferred tool schemas from `bind_tools`; blocks premature calls |
| 16 | `SubagentLimitMiddleware` | `after_model` | Truncates excess `task` tool calls beyond `max_concurrent_subagents` (optional) |
| 17 | `LoopDetectionMiddleware` | `after_model` | Two-layer loop detection; hard-stop clears tool_calls + fixes metadata |
| 18 | `ClarificationMiddleware` | `wrap_tool_call` | Intercepts `ask_clarification`; returns `Command(goto=END)` — must be last |

#### Factory functions

```python
def build_lead_runtime_middlewares(
    app_config: AppConfig | None = None,
    model_name: str | None = None,
    lazy_init: bool = True,
) -> list[AgentMiddleware]
# Returns middlewares 1–8 in order

def build_subagent_runtime_middlewares(
    app_config: AppConfig | None = None,
    model_name: str | None = None,
    lazy_init: bool = True,
) -> list[AgentMiddleware]
# Returns subset appropriate for subagents (no title, memory, vision, etc.)
```

---

#### `SandboxAuditMiddleware` detail

Pattern classification:
- **Block** (10,000 char limit, null bytes, `rm -rf /`, `curl | bash`, fork bombs)
- **Warn** (`pip install`, `chmod 777`, mass deletions)
- **Pass** — all other commands

The middleware only audits; it does NOT block commands itself (that is
`ToolErrorHandlingMiddleware`'s role). It emits structured log events for SIEM.

---

#### `LoopDetectionMiddleware` detail

```python
@classmethod
def from_config(cls, config: LoopDetectionConfig) -> LoopDetectionMiddleware
def reset(self, thread_id: str) -> None
```

Two detection layers:
1. **Hash-based**: hashes the set of tool_call `(name, args)` tuples in each
   AI message; counts identical consecutive sets per thread
2. **Frequency-based**: counts total calls per tool name within the window;
   compares against `tool_freq_warn`/`tool_freq_hard_limit`

Hard stop: strips `tool_calls` from AIMessage, fixes `additional_kwargs["tool_calls"]`
and `response_metadata`, forces a plain text response.

---

### 2.5 Memory

---

#### `omniharness/agents/memory/updater.py`

##### `class MemoryUpdater`

LLM-based fact extraction and memory update engine.

```python
def update_memory(
    messages: list[BaseMessage],
    *,
    user_id: str | None = None,
    agent_name: str | None = None,
    app_config: AppConfig | None = None,
) -> None
# Sync; offloads to asyncio.to_thread when called from async context

async def aupdate_memory(...) -> None
# Async wrapper; delegates to sync via asyncio.to_thread

def _apply_updates(current: dict, updates: dict, agent_name, user_id) -> bool
# Merges LLM-returned updates into memory structure;
# deduplicates facts by whitespace-normalized content;
# returns True if anything changed

def _strip_upload_mentions_from_memory(memory_data: dict) -> None
```

CRUD helpers (module-level functions):
```python
def get_memory_data(agent_name=None, *, user_id=None) -> dict
def reload_memory_data(agent_name=None, *, user_id=None) -> dict
def import_memory_data(new_data: dict, agent_name=None, *, user_id=None) -> bool
def clear_memory_data(agent_name=None, *, user_id=None) -> bool
def create_memory_fact(content, category, confidence=0.8, agent_name=None, *, user_id=None) -> dict | None
def delete_memory_fact(fact_id, agent_name=None, *, user_id=None) -> bool
def update_memory_fact(fact_id, updates, agent_name=None, *, user_id=None) -> dict | None
```

---

#### `omniharness/agents/memory/queue.py`

##### `class MemoryUpdateQueue`

Debounced queue for async memory updates. Per-thread deduplication.

```python
@dataclass
class ConversationContext:
    messages: list[BaseMessage]
    user_id: str | None        # Captured at enqueue time (ContextVar unavailable on timer threads)
    agent_name: str | None
    correction: str | None     # User correction signal
    reinforcement: str | None  # User approval signal

class MemoryUpdateQueue:
    def add(self, thread_id, context: ConversationContext) -> None
    # Debounced: resets timer on each call; flushes after debounce_seconds

    def add_nowait(self, thread_id, context: ConversationContext) -> None
    # Immediate (no debounce)

    def flush(self, thread_id: str | None = None) -> None  # async-safe
    def flush_nowait(self, thread_id: str | None = None) -> None
    def clear(self, thread_id: str | None = None) -> None

def get_memory_queue() -> MemoryUpdateQueue  # global singleton
```

---

#### `omniharness/agents/memory/storage.py`

##### `class MemoryStorage(ABC)`

```python
@abstractmethod
def load(self, agent_name=None, *, user_id=None) -> dict
@abstractmethod
def reload(self, agent_name=None, *, user_id=None) -> dict
@abstractmethod
def save(self, memory_data, agent_name=None, *, user_id=None) -> bool
```

##### `class FileMemoryStorage(MemoryStorage)`

File-backed storage with mtime-based caching. Cache key: `(user_id, agent_name)` tuple.

Path resolution:
- Explicit absolute `storage_path` in config → opt-out of per-user isolation
- `user_id` provided → `{base_dir}/users/{user_id}/[agents/{agent_name}/]memory.json`
- No `user_id` → legacy `{base_dir}/[agents/{agent_name}/]memory.json`

Atomic saves via temp file + rename.

Memory JSON structure:
```json
{
  "version": "1.0",
  "lastUpdated": "ISO-8601Z",
  "user": {
    "workContext": {"summary": "", "updatedAt": ""},
    "personalContext": {"summary": "", "updatedAt": ""},
    "topOfMind": {"summary": "", "updatedAt": ""}
  },
  "history": {
    "recentMonths": {"summary": "", "updatedAt": ""},
    "earlierContext": {"summary": "", "updatedAt": ""},
    "longTermBackground": {"summary": "", "updatedAt": ""}
  },
  "facts": [
    {"id": "uuid", "content": "...", "category": "preference|knowledge|context|behavior|goal",
     "confidence": 0.8, "createdAt": "...", "source": "..."}
  ]
}
```

```python
def get_memory_storage() -> MemoryStorage  # singleton
```

---

### 2.6 Sandbox

---

#### `omniharness/sandbox/sandbox.py`

##### `class Sandbox(ABC)`

```python
def __init__(self, id: str)

@abstractmethod
def execute_command(self, command: str) -> str

@abstractmethod
def read_file(self, path: str) -> str

@abstractmethod
def write_file(self, path: str, content: str, append: bool = False) -> None

@abstractmethod
def list_dir(self, path: str, max_depth: int = 2) -> list[str]

@abstractmethod
def glob(self, path: str, pattern: str, *, include_dirs: bool = False, max_results: int = 200) -> tuple[list[str], bool]
# Returns (matches, truncated)

@abstractmethod
def grep(self, path: str, pattern: str, *, glob: str | None = None,
         literal: bool = False, case_sensitive: bool = False,
         max_results: int = 100) -> tuple[list[GrepMatch], bool]

@abstractmethod
def update_file(self, path: str, content: bytes) -> None
```

---

#### `omniharness/sandbox/sandbox_provider.py`

##### `class SandboxProvider(ABC)`

```python
uses_thread_data_mounts: bool = False  # True if thread dirs are bind-mounted

@abstractmethod
def acquire(self, thread_id: str | None = None) -> str
# Returns sandbox_id

@abstractmethod
def get(self, sandbox_id: str) -> Sandbox | None

@abstractmethod
def release(self, sandbox_id: str) -> None
```

Module-level singleton management:
```python
def get_sandbox_provider(**kwargs) -> SandboxProvider
def reset_sandbox_provider() -> None
def shutdown_sandbox_provider() -> None
def set_sandbox_provider(provider: SandboxProvider) -> None  # for testing
```

---

#### `omniharness/sandbox/local/local_sandbox.py`

##### `class PathMapping(dataclass, frozen=True)`

```python
container_path: str
local_path: str
read_only: bool = False
```

##### `class LocalSandbox(Sandbox)`

Host-side sandbox. Maps container paths to local paths via `PathMapping` list.

Key behaviors:
- `execute_command(command)`: detects shell (zsh → bash → sh; PowerShell/cmd on Windows),
  runs via `subprocess.run([shell, "-c", command], timeout=600)`,
  reverse-resolves host paths in output back to virtual paths
- `_resolve_paths_in_command(command)`: replaces container paths in command string
- `_resolve_paths_in_content(content)`: resolves paths in file content (forward-slash normalized)
- `_reverse_resolve_paths_in_output(output)`: masks host paths with container equivalents
- `_agent_written_paths`: tracks files written via `write_file()` so `read_file()`
  only reverse-resolves agent-authored content, not user uploads
- `_is_read_only_path(resolved_path)`: longest-prefix match against mappings

---

#### `omniharness/sandbox/local/local_sandbox_provider.py`

##### `class LocalSandboxProvider(SandboxProvider)`

Singleton provider — one `LocalSandbox` instance shared across all threads.
`uses_thread_data_mounts = True`.

```python
def __init__(self)
def acquire(self, thread_id=None) -> str  # Always returns "local"
def get(self, sandbox_id: str) -> Sandbox | None
def release(self, sandbox_id: str) -> None  # No-op; singleton never released
```

Path mappings built in `_setup_path_mappings()`:
1. Skills directory → container_path (read-only)
2. Custom mounts from `config.sandbox.mounts` (respects `read_only` flag)

Reserved prefixes are rejected: `container_path`, `/mnt/acp-workspace`, `/mnt/user-data`.

---

#### `omniharness/sandbox/tools.py`

LangChain `@tool`-decorated functions bound to the agent:

```python
@tool("bash")
def bash_tool(runtime, description: str, command: str) -> str
# For local sandbox: validates paths, replaces virtual paths, prefixes cd <workspace> &&
# For AIO sandbox: passes command directly

@tool("ls")
def ls_tool(runtime, description: str, path: str) -> str
# tree-format listing up to 2 levels

@tool("glob")
def glob_tool(runtime, description: str, pattern: str, path: str,
              include_dirs: bool = False, max_results: int = 200) -> str

@tool("grep")
def grep_tool(runtime, description: str, pattern: str, path: str,
              glob: str | None = None, literal: bool = False,
              case_sensitive: bool = False, max_results: int = 100) -> str

@tool("read_file")
def read_file_tool(runtime, description: str, path: str,
                   start_line: int | None = None, end_line: int | None = None) -> str

@tool("write_file")
def write_file_tool(runtime, description: str, path: str, content: str, append: bool = False) -> str

@tool("str_replace")
def str_replace_tool(runtime, description: str, path: str,
                     old_str: str, new_str: str, replace_all: bool = False) -> str
```

Helper functions:
```python
def replace_virtual_path(path: str, thread_data: ThreadDataState | None) -> str
def replace_virtual_paths_in_command(command: str, thread_data: ThreadDataState | None) -> str
def mask_local_paths_in_output(output: str, thread_data: ThreadDataState | None) -> str
def validate_local_bash_command_paths(command: str, thread_data: ThreadDataState | None) -> None
def validate_local_tool_path(path: str, thread_data: ThreadDataState | None, *, read_only: bool = False) -> None
def ensure_sandbox_initialized(runtime) -> Sandbox
# Lazy acquisition: stores sandbox_id in runtime.state["sandbox"] on first call
def sandbox_from_runtime(runtime) -> Sandbox  # DEPRECATED: assumes already initialized
def is_local_sandbox(runtime) -> bool  # checks sandbox_id == "local"
def get_thread_data(runtime) -> ThreadDataState | None
```

Output truncation:
- `_truncate_bash_output(output, max_chars)` — middle-truncates (50/50 head/tail)
- `_truncate_read_file_output(output, max_chars)` — head-truncates with line-range hint
- `_truncate_ls_output(output, max_chars)` — head-truncates

---

#### `omniharness/sandbox/exceptions.py`

```
SandboxError(Exception)
  ├── SandboxNotFoundError   — sandbox_id unknown
  ├── SandboxRuntimeError    — runtime misconfiguration
  ├── SandboxCommandError    — command execution failed (command, exit_code)
  └── SandboxFileError       — file operation failed (path, operation)
        ├── SandboxPermissionError
        └── SandboxFileNotFoundError
```

---

#### `omniharness/sandbox/search.py`

```python
@dataclass(frozen=True)
class GrepMatch:
    path: str
    line_number: int
    line: str

def find_glob_matches(root: Path, pattern: str, *, include_dirs=False, max_results=200) -> tuple[list[str], bool]
def find_grep_matches(root: Path, pattern: str, *, glob_pattern=None, literal=False,
                      case_sensitive=False, max_results=100,
                      max_file_size=1_000_000) -> tuple[list[GrepMatch], bool]
def should_ignore_name(name: str) -> bool  # checks IGNORE_PATTERNS
def is_binary_file(path: Path) -> bool
```

`IGNORE_PATTERNS` excludes: `.git`, `node_modules`, `__pycache__`, `.venv`,
`dist`, `build`, `.next`, `.DS_Store`, etc.

---

#### `omniharness/sandbox/file_operation_lock.py`

```python
def get_file_operation_lock(sandbox: Sandbox, path: str) -> threading.Lock
```
Returns a `threading.Lock` scoped to `(sandbox_id, path)`.
Uses `WeakValueDictionary` — locks are GC'd when no thread holds a reference.
Prevents concurrent `str_replace` / `write_file` on the same path within
a single process.

---

### 2.7 AIO Sandbox (Community)

---

#### `omniharness/community/aio_sandbox/aio_sandbox.py`

##### `class AioSandbox(Sandbox)`

Connects to a running `agent-sandbox` Docker container via HTTP.
Thread-safety: a `threading.Lock` serializes shell commands to prevent
concurrent requests from corrupting the container's single persistent session.

```python
def __init__(self, id: str, base_url: str, home_dir: str | None = None)
```

All `Sandbox` methods implemented. `glob()` uses the container's
`file.find_files()` API. `grep()` uses `file.search_in_file()` per
candidate file. `update_file()` base64-encodes content.

---

#### `omniharness/community/aio_sandbox/aio_sandbox_provider.py`

##### `class AioSandboxProvider(SandboxProvider)`

Full Docker-orchestrated sandbox lifecycle:

```python
def acquire(self, thread_id: str | None = None) -> str
# 3-layer acquisition:
#   L1: In-process cache (_thread_sandboxes dict)
#   L1.5: Warm pool (released containers still running)
#   L2: Backend discovery + create (cross-process file lock)

def get(self, sandbox_id: str) -> Sandbox | None
def release(self, sandbox_id: str) -> None  # Moves to warm pool (container keeps running)
def destroy(self, sandbox_id: str) -> None  # Stops container, frees all resources
def shutdown(self) -> None                  # Destroys all active + warm-pool sandboxes
```

Key features:
- **Deterministic IDs**: `sha256(thread_id)[:8]` — same thread always gets same container
  even across processes
- **Warm pool**: released containers park in `_warm_pool` for fast reclaim
- **Replicas enforcement**: LRU eviction from warm pool when `replicas` limit reached
- **Idle checker**: background thread evicts idle sandboxes (active + warm pool)
- **Startup reconciliation**: adopts orphaned containers from prior process into warm pool
- **Cross-process locking**: file lock `{thread_dir}/{sandbox_id}.lock` prevents duplicate creation
- **Signal handling**: SIGTERM/SIGINT/SIGHUP trigger graceful `shutdown()`
- **Thread mounts**: `{base_dir}/users/{user_id}/threads/{tid}/user-data/{workspace,uploads,outputs}` +
  `/mnt/acp-workspace` (read-only) + skills (read-only)

Backend selection:
- `provisioner_url` set → `RemoteSandboxBackend` (K8s pod provisioner)
- Default → `LocalContainerBackend` (Docker on local host)

---

### 2.8 Tools

---

#### `omniharness/tools/tools.py`

##### `get_available_tools(groups, include_mcp, model_name, subagent_enabled, *, app_config) -> list[BaseTool]`

Assembles the full tool list for an agent run:

1. Config-defined tools from `config.yaml` via `resolve_variable(cfg.use)`
   - Filters out host bash tools if `not is_host_bash_allowed()`
   - Warns on name mismatches between config name and tool `.name`
2. Built-in tools: `present_files`, `ask_clarification`
   - `skill_manage_tool` if `skill_evolution.enabled`
   - `task` if `subagent_enabled=True`
   - `view_image` if model's `supports_vision=True`
3. MCP tools (if `include_mcp=True`):
   - `ExtensionsConfig.from_file()` — always reads latest from disk
   - `get_cached_mcp_tools()` — lazy init with mtime cache invalidation
   - If `tool_search.enabled`: registers MCP tools in `DeferredToolRegistry`,
     adds `tool_search` to builtins
4. ACP tools: `build_invoke_acp_agent_tool()` if any ACP agents configured

Deduplication: config-loaded → built-ins → MCP → ACP; first-seen name wins.

---

#### `omniharness/tools/builtins/present_file_tool.py`

```python
@tool("present_files")
def present_file_tool(runtime, filepaths: list[str], tool_call_id: Annotated[str, InjectedToolCallId]) -> Command
```
Normalizes paths to `/mnt/user-data/outputs/*` contract; returns
`Command(update={"artifacts": normalized_paths, "messages": [ToolMessage(...)]})`.
The `merge_artifacts` reducer handles deduplication.

---

#### `omniharness/tools/builtins/clarification_tool.py`

```python
@tool("ask_clarification", return_direct=True)
def ask_clarification_tool(
    question: str,
    clarification_type: Literal["missing_info", "ambiguous_requirement",
                                 "approach_choice", "risk_confirmation", "suggestion"],
    context: str | None = None,
    options: list[str] | None = None,
) -> str
```
Implementation is a placeholder; actual logic is in `ClarificationMiddleware`
which intercepts this tool call and returns `Command(goto=END)`.

---

#### `omniharness/tools/builtins/task_tool.py`

```python
@tool("task")
async def task_tool(
    runtime,
    description: str,
    prompt: str,
    subagent_type: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    max_turns: int | None = None,
) -> str
```

Async execution flow:
1. Validates `subagent_type` (built-in or custom from config)
2. Builds `SubagentExecutor` with inherited sandbox/thread state
3. Calls `executor.execute_async(prompt, task_id=tool_call_id)`
4. Polls every 5 seconds via `asyncio.sleep(5)`
5. Emits SSE custom events: `task_started`, `task_running` (per AI message),
   `task_completed` / `task_failed` / `task_cancelled` / `task_timed_out`
6. On `asyncio.CancelledError`: sets `cancel_event`, defers cleanup via `asyncio.create_task`

---

#### `omniharness/tools/builtins/tool_search.py`

##### `class DeferredToolRegistry`

```python
def register(self, tool: BaseTool) -> None
def promote(self, names: set[str]) -> None  # Remove from deferred → allow in bind_tools
def search(self, query: str) -> list[BaseTool]  # Three query forms: select:, +keyword, regex
@property
def deferred_names(self) -> set[str]
def contains(self, name: str) -> bool
```

Query forms for `search()`:
- `"select:name1,name2"` — exact name match
- `"+keyword rest"` — name must contain keyword, ranked by rest
- `"regex pattern"` — scored regex match on name + description

```python
def get_deferred_registry() -> DeferredToolRegistry | None
def set_deferred_registry(registry: DeferredToolRegistry) -> None
def reset_deferred_registry() -> None
# All use ContextVar — isolated per async request
```

```python
@tool
def tool_search(query: str) -> str
# Returns JSON array of OpenAI function definitions; calls registry.promote() for matched tools
```

---

#### `omniharness/tools/builtins/view_image_tool.py`

```python
@tool("view_image")
def view_image_tool(runtime, image_path: str,
                    tool_call_id: Annotated[str, InjectedToolCallId]) -> Command
```
Validates path is under `/mnt/user-data/{workspace,uploads,outputs}`.
Reads image (JPEG/PNG/WebP, max 20 MB), validates magic bytes, base64-encodes.
Returns `Command(update={"viewed_images": {path: {"base64": ..., "mime_type": ...}}, ...})`.

---

### 2.9 Community Tools

| Module | Tool(s) | Key config |
|---|---|---|
| `community/tavily/tools.py` | `web_search` (5 results), `web_fetch` (4KB limit) | `TAVILY_API_KEY` |
| `community/jina_ai/tools.py` | `jina_reader` web fetch | `JINA_API_KEY` (optional) |
| `community/firecrawl/tools.py` | `firecrawl_scrape` | `FIRECRAWL_API_KEY` |
| `community/serper/tools.py` | `serper_search` | `SERPER_API_KEY` |
| `community/ddg_search/tools.py` | `ddg_search` | no key needed |
| `community/image_search/tools.py` | `image_search` (DDG Images) | no key needed |
| `community/exa/tools.py` | `exa_search` | `EXA_API_KEY` |

All community tools are config-loaded via `config.yaml tools[].use` pointers.

---

### 2.10 Subagents

---

#### `omniharness/subagents/config.py`

##### `@dataclass SubagentConfig`

```python
name: str
description: str
system_prompt: str
tools: list[str] | None = None          # Allowlist; None = inherit all
disallowed_tools: list[str] | None = ["task"]  # Always excludes task to prevent nesting
skills: list[str] | None = None         # None = all enabled; [] = none
model: str = "inherit"
max_turns: int = 50
timeout_seconds: int = 900
```

```python
def resolve_subagent_model_name(
    config: SubagentConfig,
    parent_model: str | None,
    *,
    app_config: AppConfig | None = None,
) -> str
# Priority: config.model (if not "inherit") → parent_model → app_config default model
```

---

#### `omniharness/subagents/registry.py`

```python
def get_subagent_config(name: str, *, app_config=None) -> SubagentConfig | None
# Resolution order:
#   1. BUILTIN_SUBAGENTS dict (general-purpose, bash)
#   2. config.yaml custom_agents section
#   3. Apply per-agent overrides (timeout, max_turns, model, skills)
#      Global defaults only apply to built-ins, not custom agents

def list_subagents(*, app_config=None) -> list[SubagentConfig]
def get_subagent_names(*, app_config=None) -> list[str]
def get_available_subagent_names(*, app_config=None) -> list[str]
# Filters out "bash" when host bash is not allowed
```

---

#### `omniharness/subagents/executor.py`

##### `class SubagentStatus(Enum)`

`PENDING | RUNNING | COMPLETED | FAILED | CANCELLED | TIMED_OUT`

##### `@dataclass SubagentResult`

```python
task_id: str
trace_id: str
status: SubagentStatus
result: str | None = None
error: str | None = None
started_at: datetime | None = None
completed_at: datetime | None = None
ai_messages: list[dict] | None = None  # Per-turn AI message dicts
cancel_event: threading.Event          # Cooperative cancellation signal
```

##### `class SubagentExecutor`

```python
def __init__(self, config, tools, app_config=None, parent_model=None,
             sandbox_state=None, thread_data=None, thread_id=None, trace_id=None)

def execute(self, task: str, result_holder=None) -> SubagentResult
# Sync wrapper. If running inside event loop → uses isolated persistent loop.
# Otherwise → asyncio.run()

async def _aexecute(self, task: str, result_holder=None) -> SubagentResult
# Core async execution: loads skills, filters tools by skill policy,
# creates agent via _create_agent(), streams via agent.astream(),
# extracts final AIMessage content, handles cancellation at iteration boundaries

def execute_async(self, task: str, task_id: str | None = None) -> str
# Non-blocking: submits to _scheduler_pool (3 workers),
# which executes on the persistent isolated event loop,
# updates _background_tasks dict with status/result
```

**Persistent isolated loop**: a single long-lived `asyncio.AbstractEventLoop`
running in a daemon thread. Reuses shared async clients (httpx, etc.) across
executions. Started on first use via `_get_isolated_subagent_loop()`.

Module-level management:
```python
MAX_CONCURRENT_SUBAGENTS = 3  # enforced by SubagentLimitMiddleware

def get_background_task_result(task_id: str) -> SubagentResult | None
def request_cancel_background_task(task_id: str) -> None  # Sets cancel_event
def cleanup_background_task(task_id: str) -> None  # Removes terminal-state tasks
def list_background_tasks() -> list[SubagentResult]
```

Thread pool: `_scheduler_pool = ThreadPoolExecutor(max_workers=3)`.

---

### 2.11 Skills

---

#### `omniharness/skills/types.py`

##### `class SkillCategory(StrEnum)`
`PUBLIC = "public"` | `CUSTOM = "custom"`

##### `@dataclass Skill`

```python
name: str
description: str
license: str | None
skill_dir: Path
skill_file: Path            # Path to SKILL.md
relative_path: Path         # Relative from category root
category: SkillCategory
allowed_tools: list[str] | None = None  # None = legacy allow-all
enabled: bool = False       # Set from ExtensionsConfig
```

```python
def get_container_path(self, container_base_path="/mnt/skills") -> str
def get_container_file_path(self, container_base_path="/mnt/skills") -> str
```

---

#### `omniharness/skills/parser.py`

```python
def parse_skill_file(
    skill_file: Path,
    category: SkillCategory,
    relative_path: Path | None = None,
) -> Skill | None
```
Parses YAML frontmatter from `SKILL.md`. Required fields: `name`, `description`.
Optional: `license`, `allowed-tools` (list of strings).

```python
def parse_allowed_tools(raw: object, skill_file: Path) -> list[str] | None
# None if field absent; empty list for explicit no-tool skills
```

---

#### `omniharness/skills/tool_policy.py`

```python
def allowed_tool_names_for_skills(skills: list[Skill]) -> set[str] | None
# Returns None only when NO skill declares allowed-tools (legacy allow-all).
# Once any skill declares it, skills without the field contribute nothing (no allow-all leak).

def filter_tools_by_skill_allowed_tools(tools: list[ToolT], skills: list[Skill]) -> list[ToolT]
# Returns tools filtered to the union of all skill allowed-tools.
# Returns original list unchanged when result is None (legacy mode).
```

---

#### `omniharness/skills/installer.py`

```python
def safe_extract_skill_archive(zip_ref: ZipFile, dest_path: Path, max_total_size=512*1024*1024) -> None
# Security: rejects absolute paths, traversal (..), symlinks; enforces size limit

class SkillAlreadyExistsError(ValueError)
class SkillSecurityScanError(ValueError)
```

Async security scan (`_scan_skill_archive_contents_or_raise`) runs against:
- `SKILL.md` (non-executable)
- `references/`, `templates/` text files
- `scripts/` files (executable=True — stricter rules)

---

#### `omniharness/skills/storage/local_skill_storage.py`

`LocalSkillStorage` implements `SkillStorage` ABC:

```python
def load_skills(self, enabled_only: bool = False) -> list[Skill]
# Recursively scans skills/{public,custom}/ for SKILL.md files,
# parses metadata, merges enabled state from ExtensionsConfig

def get_skill(self, name: str) -> Skill | None
def set_skill_enabled(self, name: str, enabled: bool) -> bool
def install_skill(self, archive_path: Path) -> Skill
```

```python
def get_or_new_skill_storage(*, app_config=None) -> LocalSkillStorage
```

---

### 2.12 MCP

---

#### `omniharness/mcp/client.py`

```python
def build_server_params(server_name: str, config: McpServerConfig) -> dict
# Builds transport-specific params for MultiServerMCPClient:
# stdio → {transport, command, args, env}
# sse/http → {transport, url, headers}

def build_servers_config(extensions_config: ExtensionsConfig) -> dict[str, dict]
# Maps enabled server names to their params
```

---

#### `omniharness/mcp/cache.py`

Module-level global: `_mcp_tools_cache: list[BaseTool] | None`, `_config_mtime: float | None`.

```python
async def initialize_mcp_tools() -> list[BaseTool]
# Protected by asyncio.Lock; loads all tools from all enabled MCP servers

def get_cached_mcp_tools() -> list[BaseTool]
# Lazy init: detects mtime changes via _is_cache_stale();
# handles running-loop case by ThreadPoolExecutor + asyncio.run

def reset_mcp_tools_cache() -> None
```

Cache invalidation: compares current `extensions_config.json` mtime against
`_config_mtime` captured at last initialization.

---

#### `omniharness/mcp/oauth.py`

##### `class OAuthTokenManager`

```python
def __init__(self, oauth_by_server: dict[str, McpOAuthConfig])

@classmethod
def from_extensions_config(cls, extensions_config) -> OAuthTokenManager

async def get_authorization_header(self, server_name: str) -> str | None
# Returns "Bearer <token>" or "token_type <access_token>"
# Double-checked locking: check expiry, lock, re-check, fetch if still expired

def has_oauth_servers(self) -> bool
def oauth_server_names(self) -> list[str]
```

```python
def build_oauth_tool_interceptor(extensions_config) -> Any | None
# Returns an async interceptor function injecting Authorization header;
# None if no OAuth servers configured

async def get_initial_oauth_headers(extensions_config) -> dict[str, str]
# Fetches initial tokens for all OAuth servers
```

---

### 2.13 Runtime

---

#### `omniharness/runtime/user_context.py`

```python
# Protocol for current user (any object with .id: str)
@runtime_checkable
class CurrentUser(Protocol):
    id: str

DEFAULT_USER_ID: Final[str] = "default"

def set_current_user(user: CurrentUser) -> Token
def reset_current_user(token: Token) -> None
def get_current_user() -> CurrentUser | None
def require_current_user() -> CurrentUser  # Raises RuntimeError if unset
def get_effective_user_id() -> str  # Returns DEFAULT_USER_ID if no user in context

# Three-state resolution for repository user_id params:
AUTO = _AutoSentinel()  # Read from contextvar; raise if unset
def resolve_user_id(value: str | None | _AutoSentinel, *, method_name="") -> str | None
```

---

#### `omniharness/runtime/stream_bridge/base.py`

##### `class StreamBridge(ABC)`

```python
@dataclass(frozen=True)
class StreamEvent:
    id: str    # Monotonic event ID (SSE id: field, supports Last-Event-ID reconnection)
    event: str # SSE event name: "metadata", "values", "messages", "custom", "error", "end"
    data: Any  # JSON-serializable payload

HEARTBEAT_SENTINEL = StreamEvent(id="", event="__heartbeat__", data=None)
END_SENTINEL = StreamEvent(id="", event="__end__", data=None)

class StreamBridge(ABC):
    @abstractmethod
    async def publish(self, run_id: str, event: str, data: Any) -> None

    @abstractmethod
    async def publish_end(self, run_id: str) -> None

    @abstractmethod
    def subscribe(self, run_id: str, *, last_event_id=None,
                  heartbeat_interval=15.0) -> AsyncIterator[StreamEvent]
    # Yields HEARTBEAT_SENTINEL every heartbeat_interval seconds with no event
    # Yields END_SENTINEL when publish_end() called

    @abstractmethod
    async def cleanup(self, run_id: str, *, delay: float = 0) -> None
    async def close(self) -> None  # Default no-op
```

---

#### `omniharness/runtime/runs/schemas.py`

```python
class RunStatus(StrEnum):
    pending | running | success | error | timeout | interrupted

class DisconnectMode(StrEnum):
    cancel | continue_
```

---

#### `omniharness/runtime/runs/manager.py`

##### `class RunRecord`

```python
run_id: str
thread_id: str
assistant_id: str | None
status: RunStatus
on_disconnect: DisconnectMode
multitask_strategy: str = "reject"
metadata: dict
kwargs: dict
created_at: str
updated_at: str
task: asyncio.Task | None     # Running asyncio task (not persisted)
abort_event: asyncio.Event    # Set to request cancellation
abort_action: str = "interrupt"  # "interrupt" or "rollback"
error: str | None
```

##### `class RunManager`

```python
def __init__(self, store: RunStore | None = None)

async def create(self, thread_id, assistant_id=None, *, on_disconnect, metadata, kwargs, multitask_strategy) -> RunRecord
async def create_or_reject(self, ...) -> RunRecord
# "reject": raises ConflictError if inflight run exists
# "interrupt"/"rollback": cancels inflight runs before creating

async def get(self, run_id: str) -> RunRecord | None
async def list_by_thread(self, thread_id: str) -> list[RunRecord]
async def set_status(self, run_id: str, status: RunStatus, *, error=None) -> None
async def cancel(self, run_id: str, *, action="interrupt") -> bool
async def has_inflight(self, thread_id: str) -> bool
async def cleanup(self, run_id: str, *, delay: float = 300) -> None
async def update_run_completion(self, run_id: str, **kwargs) -> None
```

---

#### `omniharness/runtime/runs/worker.py`

##### `async def run_agent(bridge, run_manager, record, *, ctx, agent_factory, graph_input, config, stream_modes, ...) -> None`

Core agent execution coroutine. Executed as an `asyncio.Task`.

Steps:
1. Mark run as `running`
2. Snapshot pre-run checkpoint (for rollback support)
3. Publish `"metadata"` event to `bridge` (run_id + thread_id)
4. Build runtime context (`thread_id`, `run_id`, `app_config`)
5. Inject `Runtime` object into `config["configurable"]["__pregel_runtime"]`
6. Instantiate agent via `agent_factory(config=runnable_config)`
7. Attach checkpointer, store, interrupt nodes
8. Map `stream_modes` (e.g. `"messages-tuple"` → LangGraph `"messages"`)
9. Stream via `agent.astream()` — single mode or multi-mode tuples
10. Publish each chunk as SSE event to bridge
11. On abort: set status to `interrupted` or perform checkpoint rollback
12. On exception: set status to `error`, publish `"error"` event
13. Finally: flush `RunJournal`, persist token usage to `RunStore`,
    sync title to `thread_meta`, publish `"end"`, schedule bridge cleanup

```python
@dataclass(frozen=True)
class RunContext:
    checkpointer: Any
    store: Any | None
    event_store: Any | None
    run_events_config: Any | None
    thread_store: Any | None
    app_config: AppConfig | None
```

---

### 2.14 Persistence

SQLAlchemy-based SQL persistence layer. Default backend: SQLite at
`{runtime_home}/db/omniharness.db`.

---

#### `omniharness/persistence/base.py`

`Base = declarative_base()` — all ORM models extend this.

---

#### `omniharness/persistence/feedback/model.py`

##### `class FeedbackRow(Base)`

`__tablename__ = "feedback"`

Unique constraint: `(thread_id, run_id, user_id)` — one feedback per user per run.

| Column | Type | Description |
|---|---|---|
| `feedback_id` | `String(64)` PK | UUID |
| `run_id` | `String(64)` indexed | Run identifier |
| `thread_id` | `String(64)` indexed | Thread identifier |
| `user_id` | `String(64)` nullable indexed | User identifier |
| `message_id` | `String(64)` nullable | Specific message target |
| `rating` | `Integer` | `+1` (thumbs-up) or `-1` (thumbs-down) |
| `comment` | `Text` nullable | Optional text feedback |
| `created_at` | `DateTime(tz=True)` | Creation timestamp |

---

### 2.15 Guardrails

---

#### `omniharness/guardrails/provider.py`

```python
@dataclass
class GuardrailRequest:
    tool_name: str
    tool_input: dict
    agent_id: str | None
    thread_id: str | None
    is_subagent: bool = False
    timestamp: str = ""

@dataclass
class GuardrailReason:
    code: str
    message: str = ""

@dataclass
class GuardrailDecision:
    allow: bool
    reasons: list[GuardrailReason]
    policy_id: str | None
    metadata: dict

@runtime_checkable
class GuardrailProvider(Protocol):
    name: str
    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision
    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision
```

---

#### `omniharness/guardrails/builtin.py`

##### `class AllowlistProvider`

```python
def __init__(self, *, allowed_tools: list[str] | None = None, denied_tools: list[str] | None = None)
def evaluate(self, request: GuardrailRequest) -> GuardrailDecision
async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision
```
Zero external dependencies. Allow-all when `allowed_tools=None`, deny nothing
when `denied_tools=None`.

---

### 2.16 Tracing

---

#### `omniharness/tracing/factory.py`

```python
def build_tracing_callbacks() -> list[Any]
# Reads TracingConfig; returns LangChain callback handlers for enabled providers.
# Supported: "langsmith" (LangChainTracer), "langfuse" (LangfuseCallbackHandler)
```

TracingConfig fields (from env vars at import time; singleton with thread lock):

| Field | Env Var | Description |
|---|---|---|
| LangSmith `project` | `LANGCHAIN_PROJECT` | LangSmith project name |
| LangSmith `api_key` | `LANGCHAIN_API_KEY` | LangSmith API key |
| Langfuse `secret_key` | `LANGFUSE_SECRET_KEY` | Langfuse secret key |
| Langfuse `public_key` | `LANGFUSE_PUBLIC_KEY` | Langfuse public key |
| Langfuse `host` | `LANGFUSE_HOST` | Langfuse host URL |

---

### 2.17 Reflection

---

#### `omniharness/reflection/resolvers.py`

```python
def resolve_variable(
    variable_path: str,                              # "module.path:variable_name"
    expected_type: type[T] | tuple[type, ...] | None = None,
) -> T
# Imports module, returns attribute.
# On ImportError: builds actionable "uv add <package>" hint from MODULE_TO_PACKAGE_HINTS.
# On type mismatch: raises ValueError.

def resolve_class(
    class_path: str,        # "module.path:ClassName"
    base_class: type[T] | None = None,
) -> type[T]
# Validates the resolved object is a class and subclass of base_class.
```

`MODULE_TO_PACKAGE_HINTS` maps module roots to install packages:
- `langchain_google_genai` → `langchain-google-genai`
- `langchain_anthropic` → `langchain-anthropic`
- `langchain_openai` → `langchain-openai`
- `langchain_deepseek` → `langchain-deepseek`

---

### 2.18 Client

---

#### `omniharness/client.py`

##### `class OmniHarnessClient`

Embedded Python client providing in-process access to OmniHarness without
any HTTP services. Return types match Gateway API response schemas (tested
by `TestGatewayConformance` in `tests/test_client.py`).

```python
def __init__(
    self,
    config_path: str | None = None,
    checkpointer = None,
    *,
    model_name: str | None = None,
    thinking_enabled: bool = True,
    subagent_enabled: bool = False,
    plan_mode: bool = False,
    agent_name: str | None = None,
    available_skills: set[str] | None = None,
    middlewares: Sequence[AgentMiddleware] | None = None,
)
```

Agent is created lazily on first call; recreated when `model_name`, `thinking_enabled`,
`plan_mode`, `subagent_enabled`, `agent_name`, or `available_skills` changes.

```python
def reset_agent(self) -> None  # Force recreation on next call
```

**Conversation methods**:

```python
def chat(self, message: str, thread_id: str | None = None, **kwargs) -> str
# Synchronous. Accumulates streaming deltas by message ID; returns final AI text.

def stream(self, message: str, thread_id: str | None = None, **kwargs) -> Generator[StreamEvent, None, None]
# Yields StreamEvent instances:
#   type="values"         → full state snapshot {title, messages, artifacts}
#   type="messages-tuple" → per-message update (AI text delta, tool calls, tool results)
#   type="custom"         → forwarded from StreamWriter
#   type="end"            → stream complete (cumulative usage counted once per message id)
```

```python
@dataclass
class StreamEvent:
    type: Literal["values", "messages-tuple", "custom", "end"]
    data: dict[str, Any]
```

**Gateway equivalent methods**:

```python
def list_models(self) -> dict        # {"models": [...]}
def get_model(self, name: str) -> dict
def get_mcp_config(self) -> dict     # {"mcp_servers": {...}}
def update_mcp_config(self, servers: dict) -> dict  # Saves + invalidates agent
def list_skills(self) -> dict        # {"skills": [...]}
def get_skill(self, name: str) -> dict
def update_skill(self, name: str, enabled: bool) -> dict  # Saves + invalidates agent
def install_skill(self, archive_path: Path) -> dict
def get_memory(self, ...) -> dict
def reload_memory(self, ...) -> dict
def get_memory_config(self) -> dict
def get_memory_status(self) -> dict
def upload_files(self, thread_id: str, files: list[Path]) -> dict
def list_uploads(self, thread_id: str) -> dict
def delete_upload(self, thread_id: str, filename: str) -> dict
def get_artifact(self, thread_id: str, path: str) -> tuple[bytes, str]  # (content, mime_type)
```

---

## 3. Call Graph / Dependency Map

```
Gateway HTTP request
     │
     ├─── auth middleware → set_current_user() → ContextVar[CurrentUser]
     │
     └─── POST /api/threads/{id}/runs/stream
               │
               ▼
         run_agent(bridge, run_manager, record, agent_factory=make_lead_agent, ...)
               │
               ├─ get_app_config()  ← config.yaml (auto-reloads on mtime change)
               │
               ├─ make_lead_agent(config)
               │     │
               │     ├─ create_chat_model(model_name, thinking_enabled)
               │     │     └─ resolve_class(model_config.use)  ← reflection
               │     │
               │     ├─ get_available_tools(groups, ...)
               │     │     ├─ resolve_variable(cfg.use)  ← config-defined tools
               │     │     ├─ BUILTIN_TOOLS (present_files, ask_clarification, ...)
               │     │     └─ get_cached_mcp_tools()
               │     │           └─ MultiServerMCPClient.from_extensions_config()
               │     │                 └─ build_servers_config() ← extensions_config.json
               │     │
               │     ├─ apply_prompt_template(...)
               │     │     ├─ get_memory_data()  ← FileMemoryStorage.load()
               │     │     └─ get_skills_prompt_section()  ← LocalSkillStorage.load_skills()
               │     │
               │     └─ _build_middlewares()  (18 in order)
               │
               └─ agent.astream(input, config=...)
                     │
                     ▼
               Middleware chain (inner-first, wrapping model + tool calls):
               ClarificationMiddleware
               LoopDetectionMiddleware
               SubagentLimitMiddleware
               DeferredToolFilterMiddleware
               ViewImageMiddleware
               MemoryMiddleware
               TitleMiddleware
               TokenUsageMiddleware
               TodoMiddleware
               SummarizationMiddleware
               ToolErrorHandlingMiddleware
               SandboxAuditMiddleware
               GuardrailMiddleware
               LLMErrorHandlingMiddleware
               DanglingToolCallMiddleware
               SandboxMiddleware
               UploadsMiddleware
               ThreadDataMiddleware
```

**Cross-subsystem import graph** (simplified, left = importer):

```
agents/lead_agent  →  models (create_chat_model)
                   →  tools (get_available_tools)
                   →  sandbox/middleware (SandboxMiddleware)
                   →  agents/memory (MemoryMiddleware)
                   →  skills/storage (get_skills_prompt_section)
                   →  subagents (SubagentLimitMiddleware)
                   →  guardrails (GuardrailMiddleware)
                   →  mcp (get_cached_mcp_tools)
                   →  config (get_app_config)

tools/builtins/task_tool  →  subagents (SubagentExecutor)
                           →  tools (get_available_tools)  [lazy import]

sandbox/tools     →  sandbox/sandbox_provider (get_sandbox_provider)
                  →  sandbox/search (find_glob_matches, find_grep_matches)
                  →  sandbox/security (is_host_bash_allowed)
                  →  config/paths (VIRTUAL_PATH_PREFIX, get_paths)

models/factory    →  reflection (resolve_class)
                  →  tracing (build_tracing_callbacks)
                  →  config (get_app_config)

reflection        →  (standard library only — importlib)
config            →  (pydantic, yaml, os — no omniharness imports)
runtime/worker    →  agents (agent_factory call)
                  →  runtime/stream_bridge
                  →  runtime/journal
                  →  persistence (RunStore, ThreadStore)
client            →  agents/lead_agent (make_lead_agent, _build_middlewares)
                  →  models
                  →  tools
                  →  skills/storage
                  →  uploads/manager
                  →  config
```

---

## 4. Data Flow Diagrams

### 4.1 Agent Request → Middleware → LLM → Tool Execution → Response

```
Client (SSE consumer)
     │
     │  POST /api/threads/{id}/runs/stream
     ▼
Gateway Router
     │
     ├── Creates RunRecord (RunManager.create_or_reject)
     │
     └── Spawns asyncio.Task: run_agent(bridge, ...)
               │
               │  agent.astream({"messages": [HumanMessage(...)]}, config)
               ▼
         ┌─────────────────────────────────────────────┐
         │            Middleware Stack                   │
         │  (outermost = ThreadDataMiddleware)           │
         │                                               │
         │  before_agent():                              │
         │    ThreadDataMiddleware: create dirs, stamp   │
         │    UploadsMiddleware: inject uploaded_files   │
         │    SandboxMiddleware: acquire sandbox (lazy)  │
         │                                               │
         │  wrap_model_call(model):                      │
         │    DanglingToolCallMiddleware                 │
         │    LLMErrorHandlingMiddleware (retry, CB)     │
         │    ── model.bind_tools(tools).invoke() ──     │
         │    returns AIMessage                          │
         │                                               │
         │  after_model(state):                          │
         │    SummarizationMiddleware: compress if >limit│
         │    LoopDetectionMiddleware: check loops       │
         │    SubagentLimitMiddleware: truncate excess   │
         │    DeferredToolFilterMiddleware: strip schemas│
         │    TokenUsageMiddleware: record usage         │
         │    TitleMiddleware: gen title (1st turn only) │
         │                                               │
         │  wrap_tool_call(tool):                        │
         │    GuardrailMiddleware: authorize             │
         │    SandboxAuditMiddleware: audit bash cmds    │
         │    ToolErrorHandlingMiddleware: catch errors  │
         │    ── tool.invoke(args) ──                    │
         │    returns ToolMessage                        │
         │    ClarificationMiddleware: ask_clarification │
         │      → Command(goto=END) interrupts loop      │
         │                                               │
         │  after_agent():                               │
         │    SandboxMiddleware: release sandbox         │
         │    MemoryMiddleware: queue memory update      │
         └─────────────────────────────────────────────┘
               │
               │  Each chunk published to StreamBridge
               │  (values / messages / custom events)
               ▼
         InMemoryStreamBridge.subscribe(run_id)
               │
               │  SSE events streamed to client
               ▼
         Client receives: metadata → values/messages chunks → end
```

---

### 4.2 Sandbox Lifecycle

```
Tool invocation (bash/read_file/write_file/...)
     │
     ▼
ensure_sandbox_initialized(runtime)
     │
     ├── Check runtime.state["sandbox"]["sandbox_id"]
     │     ↳ If exists and found in provider → return existing Sandbox
     │
     └── Lazy acquisition:
           thread_id = runtime.context["thread_id"]
           │
           ▼
     SandboxProvider.acquire(thread_id)
           │
           ├── [LocalSandboxProvider]
           │     └── Singleton LocalSandbox("local", path_mappings=[...])
           │           path_mappings:
           │             /mnt/skills → {project_root}/skills (read-only)
           │             custom mounts from config.yaml
           │
           └── [AioSandboxProvider]
                 │
                 L1: In-process cache (_thread_sandboxes)
                 L1.5: Warm pool (container still running)
                 L2: Backend discovery (cross-process file lock)
                       │
                       ├── LocalContainerBackend:
                       │     docker run --rm -d
                       │       -v {workspace}:/mnt/user-data/workspace
                       │       -v {uploads}:/mnt/user-data/uploads
                       │       -v {outputs}:/mnt/user-data/outputs
                       │       -v {acp-workspace}:/mnt/acp-workspace:ro
                       │       -v {skills}:/mnt/skills:ro
                       │       -p {port}:{port}
                       │       {image}
                       │
                       └── RemoteSandboxBackend:
                             POST {provisioner_url}/sandboxes
                             (K8s pod provisioner)
                 │
                 wait_for_sandbox_ready(sandbox_url, timeout=60)
                 │
                 ▼
           Returns sandbox_id → stored in runtime.state["sandbox"]

Tool runs via sandbox.execute_command / read_file / write_file / ...

After agent turn:
     SandboxMiddleware.after_agent()
          │
          ├── [LocalSandboxProvider]: release() is no-op (singleton persists)
          └── [AioSandboxProvider]: release() → moves to warm pool
                                    (container keeps running for fast reclaim)

Idle checker (every 60s):
     Containers idle > idle_timeout (600s) → destroy()
     Warm pool entries idle > idle_timeout → backend.destroy()

Shutdown / SIGTERM:
     AioSandboxProvider.shutdown()
          destroy() all active + warm-pool sandboxes
```

---

### 4.3 Memory Flow

```
Human sends message → Agent responds
     │
     ▼
MemoryMiddleware.after_agent(state)
     │
     ├── Filters messages: last HumanMessage + last AIMessage (non-tool)
     │
     ├── Captures user_id = get_effective_user_id()  (ContextVar, captured NOW)
     │
     └── MemoryUpdateQueue.add(thread_id, ConversationContext(
               messages=filtered_messages,
               user_id=captured_user_id,   ← CRITICAL: not from ContextVar later
               agent_name=agent_name,
               correction=...,
               reinforcement=...
         ))
               │
               ▼
         debounce_timer (default 30s)
               │
               ▼
     Background thread: MemoryUpdater.update_memory(messages, user_id=...)
               │
               ├── LLM call: extract context + facts from conversation
               │
               ├── _apply_updates(current, llm_output, agent_name, user_id)
               │     ├── Merge workContext / personalContext / topOfMind / history
               │     ├── Deduplicate facts by whitespace-normalized content
               │     └── Respect max_facts limit + confidence threshold
               │
               └── FileMemoryStorage.save(memory_data, agent_name, user_id=user_id)
                     └── Atomic: temp file + replace
                           └── Invalidates mtime cache

Next request:
     apply_prompt_template()
          └── _get_memory_context(user_id)
                └── FileMemoryStorage.load()  ← mtime-cached read
                      └── Injects top 15 facts + summaries into <memory> section
```

---

### 4.4 Skill Loading Pipeline

```
get_available_tools() called
     │
     ├── reset_deferred_registry()  (clear stale state)
     │
     └── if include_mcp and tool_search.enabled:
               │
               ▼
     LocalSkillStorage.load_skills(enabled_only=True)
               │
               ├── Scan: {skills_path}/public/**/ + {skills_path}/custom/**/
               │
               ├── For each SKILL.md found:
               │     parse_skill_file(skill_file, category)
               │       └── Extract YAML frontmatter: name, description, license, allowed-tools
               │
               └── Merge enabled state from ExtensionsConfig.skills dict
                     ↳ default: disabled for newly discovered skills

apply_prompt_template() called
     │
     └── get_skills_prompt_section(available_skills=frozenset)
               │
               ├── lru_cache hit? → return cached section
               │
               └── Build skill listing for system prompt:
                     For each enabled skill:
                       "- {skill.name}: {description}"
                       "  Path: {skill.get_container_file_path()}"

SubagentExecutor._load_skills() — async
     │
     ├── get_or_new_skill_storage()
     │
     ├── asyncio.to_thread(storage.load_skills, enabled_only=True)
     │
     ├── Filter by config.skills allowlist (if specified)
     │
     └── Read SKILL.md content → SystemMessage per skill
           (injected as conversation items BEFORE the task HumanMessage)

filter_tools_by_skill_allowed_tools(tools, skills)
     └── allowed_tool_names_for_skills(skills)
           ├── If no skill declares allowed-tools → None → all tools allowed
           └── If any skill declares allowed-tools → union of all declarations
                 └── Filter tool list to this union
```

---

### 4.5 Subagent Delegation Flow

```
Lead agent model response includes tool_call: task(...)
     │
     ├── SubagentLimitMiddleware.after_model():
     │     Truncate if len(task_calls) > max_concurrent_subagents
     │
     ▼
ToolErrorHandlingMiddleware.wrap_tool_call(task_tool, args)
     │
     ▼
async task_tool(runtime, description, prompt, subagent_type, tool_call_id, max_turns)
     │
     ├── get_subagent_config(subagent_type)
     │     ├── BUILTIN_SUBAGENTS["general-purpose" | "bash"]
     │     └── config.yaml custom_agents[subagent_type]
     │         + per-agent overrides (timeout, max_turns, model, skills)
     │
     ├── get_available_tools(model_name=effective_model, subagent_enabled=False)
     │     └── Inherits parent's tool_groups (same restrictions)
     │
     ├── SubagentExecutor(config, tools, parent_model, sandbox_state, thread_data, thread_id)
     │
     ├── task_id = executor.execute_async(prompt, task_id=tool_call_id)
     │     │
     │     └── _scheduler_pool.submit(run_task)
     │               │
     │               ▼
     │         [Background thread in scheduler pool]
     │               │
     │               └── _submit_to_isolated_loop_in_context(ctx, _aexecute)
     │                         │
     │                         ▼
     │                   [Persistent isolated event loop]
     │                   _aexecute(task, result_holder):
     │                     1. Load skills (asyncio.to_thread)
     │                     2. Filter tools by skill policy
     │                     3. Inject skill SystemMessages + HumanMessage
     │                     4. build_subagent_runtime_middlewares()
     │                     5. create_agent(model, tools, middleware, system_prompt)
     │                     6. async for chunk in agent.astream(state, config):
     │                           Collect AIMessages, check cancel_event
     │                     7. Extract last AIMessage.content → result
     │
     ├── Poll loop (every 5s via asyncio.sleep):
     │     get_background_task_result(task_id)
     │     │
     │     ├── Emit SSE custom events via get_stream_writer():
     │     │     task_started, task_running (per new AI message),
     │     │     task_completed / task_failed / task_cancelled / task_timed_out
     │     │
     │     └── On asyncio.CancelledError (parent cancelled):
     │           request_cancel_background_task(task_id)
     │           asyncio.create_task(cleanup_when_done())
     │
     └── Returns "Task Succeeded. Result: {result}" as ToolMessage content
```

---

## 5. Configuration Schema

### 5.1 `config.yaml` — Complete Reference

```yaml
# config_version: 1  # Bump when schema changes

models:
  - name: gpt-4o              # Required; unique identifier
    use: langchain_openai:ChatOpenAI  # Required; class path via resolve_class()
    display_name: GPT-4o      # Optional; shown in UI
    description: ""           # Optional
    model: gpt-4o             # Forwarded to LLM constructor
    api_key: $OPENAI_API_KEY  # $ prefix = env var substitution
    supports_thinking: false
    supports_vision: false
    supports_reasoning_effort: false
    when_thinking_enabled: {}   # Extra kwargs injected when thinking=True
    when_thinking_disabled: {}  # Extra kwargs injected when thinking=False
    thinking: {}                # Shortcut for when_thinking_enabled.thinking
    use_responses_api: false    # Force /v1/responses endpoint
    output_version: null        # OpenAI output version

tools:
  - name: bash                 # Must match tool .name attribute
    group: sandbox             # Logical group
    use: omniharness.sandbox.tools:bash_tool  # Variable path via resolve_variable()
  - name: ls
    group: sandbox
    use: omniharness.sandbox.tools:ls_tool
  # Additional: read_file, write_file, str_replace, glob, grep, web_search, ...

tool_groups:
  - name: sandbox
  - name: web

sandbox:
  use: omniharness.sandbox.local.local_sandbox_provider:LocalSandboxProvider
  allow_host_bash: false
  # For AioSandboxProvider:
  # use: omniharness.community.aio_sandbox:AioSandboxProvider
  image: ghcr.io/archimedes-run/omni-harness-sandbox:latest
  port: 8080
  replicas: 3
  container_prefix: omni-harness-sandbox
  idle_timeout: 600
  mounts:
    - host_path: /absolute/host/path
      container_path: /mnt/custom
      read_only: false
  environment:
    NODE_ENV: production
    API_KEY: $MY_API_KEY
  bash_output_max_chars: 20000
  read_file_output_max_chars: 50000
  ls_output_max_chars: 20000

skills:
  path: null             # Host path; auto-detected if null
  container_path: /mnt/skills

title:
  enabled: true
  max_words: 6
  max_chars: 60
  model_name: null       # null = use default model
  prompt_template: null  # null = built-in template

summarization:
  enabled: false
  model_name: null
  trigger:
    type: tokens         # tokens | messages | fraction
    value: 100000
  keep:
    type: tokens
    value: 50000
  trim_tokens_to_summarize: 4000
  preserve_recent_skill_count: 5
  preserve_recent_skill_tokens: 25000
  preserve_recent_skill_tokens_per_skill: 5000

memory:
  enabled: true
  injection_enabled: true
  storage_path: null     # null = per-user path; absolute path = shared
  debounce_seconds: 30
  model_name: null
  max_facts: 100
  fact_confidence_threshold: 0.7
  max_injection_tokens: 2000

subagents:
  timeout_seconds: 900
  max_turns: null
  agents:
    general-purpose:
      timeout_seconds: 900
      max_turns: 50
      model: null
      skills: null
  custom_agents:
    my-agent:
      description: "When to use this agent"
      system_prompt: "You are..."
      tools: [bash, read_file]     # null = inherit all
      disallowed_tools: [task]
      skills: null                 # null = all; [] = none
      model: inherit
      max_turns: 50
      timeout_seconds: 900

tool_search:
  enabled: false

token_usage:
  enabled: false

loop_detection:
  enabled: true
  warn_threshold: 3
  hard_limit: 5
  window_size: 20
  max_tracked_threads: 100
  tool_freq_warn: 30
  tool_freq_hard_limit: 50
  tool_freq_overrides:
    bash:
      warn: 50
      hard_limit: 100

guardrails:
  enabled: false
  fail_closed: false
  provider:
    use: omniharness.guardrails.builtin:AllowlistProvider
    config:
      allowed_tools: null
      denied_tools: []

checkpointer:
  type: sqlite           # memory | sqlite | postgres
  connection_string: null

database:
  backend: sqlite        # memory | sqlite | postgres
  sqlite_dir: null       # null = {runtime_home}/db/
  postgres_url: null
  echo_sql: false
  pool_size: 5

run_events:
  backend: memory        # memory | db | jsonl
  max_trace_content: 10240
  track_token_usage: true

stream_bridge:
  type: memory           # memory | redis
  redis_url: null
  queue_maxsize: 256

skill_evolution:
  enabled: false
  moderation_model_name: null

agents_api:
  enabled: false

acp_agents:
  codex:
    command: npx
    args: ["-y", "@zed-industries/codex-acp"]
    env: {}
    description: "OpenAI Codex CLI agent"
    model: null
    auto_approve_permissions: false
```

---

### 5.2 `extensions_config.json` — Complete Reference

```json
{
  "mcpServers": {
    "filesystem": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/allowed/path"],
      "env": {},
      "description": "File system access"
    },
    "my-sse-server": {
      "enabled": true,
      "type": "sse",
      "url": "https://example.com/mcp/sse",
      "headers": {"X-Custom": "value"},
      "oauth": {
        "enabled": true,
        "token_url": "https://auth.example.com/token",
        "grant_type": "client_credentials",
        "client_id": "$CLIENT_ID",
        "client_secret": "$CLIENT_SECRET",
        "scope": "read write",
        "audience": null,
        "token_field": "access_token",
        "expires_in_field": "expires_in",
        "refresh_skew_seconds": 60,
        "extra_token_params": {}
      }
    }
  },
  "skills": {
    "my-skill": { "enabled": true },
    "other-skill": { "enabled": false }
  }
}
```

---

### 5.3 `SKILL.md` Frontmatter Schema

```yaml
---
name: my-skill            # Required; unique identifier
description: |            # Required; shown in system prompt
  What this skill does.
license: MIT              # Optional
allowed-tools:            # Optional; absent = legacy allow-all
  - bash
  - read_file
  - write_file
---

# Skill Content

Markdown content injected into the agent's context when skill is active.
```

---

## 6. Public API Entry Points

### Agent Creation

```python
from omniharness.agents.lead_agent.agent import make_lead_agent
# LangGraph factory — registered in langgraph.json
# Signature: make_lead_agent(config: RunnableConfig) -> CompiledGraph

from omniharness.agents.factory import create_omniharness_agent
# Pure-Python SDK factory
# create_omniharness_agent(model, tools, system_prompt, *, features=RuntimeFeatures(), ...)

from langchain.agents import create_agent
# Low-level LangGraph primitive used internally
```

### Configuration

```python
from omniharness.config import get_app_config
from omniharness.config.app_config import AppConfig, push_current_app_config, pop_current_app_config
from omniharness.config.extensions_config import get_extensions_config, ExtensionsConfig
from omniharness.config.paths import get_paths, VIRTUAL_PATH_PREFIX
from omniharness.config.runtime_paths import project_root, runtime_home
```

### Model Factory

```python
from omniharness.models import create_chat_model
# create_chat_model(name=None, thinking_enabled=False, *, app_config=None, **kwargs) -> BaseChatModel
```

### Tools

```python
from omniharness.tools import get_available_tools
# get_available_tools(groups=None, include_mcp=True, model_name=None,
#                     subagent_enabled=False, *, app_config=None) -> list[BaseTool]

from omniharness.sandbox.tools import (
    bash_tool, ls_tool, read_file_tool, write_file_tool, str_replace_tool, glob_tool, grep_tool,
    ensure_sandbox_initialized, is_local_sandbox, get_thread_data,
    replace_virtual_path, mask_local_paths_in_output,
)
```

### Sandbox

```python
from omniharness.sandbox import get_sandbox_provider, set_sandbox_provider
from omniharness.sandbox.sandbox import Sandbox
from omniharness.sandbox.sandbox_provider import SandboxProvider
from omniharness.sandbox.local import LocalSandboxProvider, LocalSandbox
from omniharness.community.aio_sandbox import AioSandboxProvider, AioSandbox
```

### Memory

```python
from omniharness.agents.memory.updater import (
    MemoryUpdater,
    get_memory_data, reload_memory_data, import_memory_data, clear_memory_data,
    create_memory_fact, delete_memory_fact, update_memory_fact,
)
from omniharness.agents.memory.queue import get_memory_queue, MemoryUpdateQueue
from omniharness.agents.memory.storage import get_memory_storage, FileMemoryStorage
```

### Skills

```python
from omniharness.skills.storage import get_or_new_skill_storage
from omniharness.skills.types import Skill, SkillCategory
from omniharness.skills.parser import parse_skill_file
from omniharness.skills.tool_policy import filter_tools_by_skill_allowed_tools
from omniharness.skills.installer import safe_extract_skill_archive, SkillAlreadyExistsError
```

### MCP

```python
from omniharness.mcp.cache import get_cached_mcp_tools, initialize_mcp_tools, reset_mcp_tools_cache
from omniharness.mcp.client import build_servers_config
from omniharness.mcp.oauth import OAuthTokenManager
```

### Subagents

```python
from omniharness.subagents import SubagentExecutor
from omniharness.subagents.registry import get_subagent_config, list_subagents
from omniharness.subagents.config import SubagentConfig
from omniharness.subagents.executor import (
    SubagentStatus, SubagentResult,
    get_background_task_result, request_cancel_background_task, cleanup_background_task,
)
```

### Guardrails

```python
from omniharness.guardrails.provider import GuardrailProvider, GuardrailRequest, GuardrailDecision
from omniharness.guardrails.builtin import AllowlistProvider
```

### Runtime

```python
from omniharness.runtime.user_context import (
    get_effective_user_id, set_current_user, reset_current_user, get_current_user,
    DEFAULT_USER_ID, AUTO,
)
from omniharness.runtime.stream_bridge.base import StreamBridge, StreamEvent
from omniharness.runtime.runs.manager import RunManager
from omniharness.runtime.runs.worker import run_agent, RunContext
from omniharness.runtime.runs.schemas import RunStatus, DisconnectMode
```

### Reflection

```python
from omniharness.reflection import resolve_variable, resolve_class
# resolve_variable("module.path:name", expected_type=None) -> T
# resolve_class("module.path:ClassName", base_class=None) -> type[T]
```

### Tracing

```python
from omniharness.tracing import build_tracing_callbacks
# Returns list of LangChain callback handlers for enabled providers
```

### Embedded Client

```python
from omniharness.client import OmniHarnessClient, StreamEvent
# client = OmniHarnessClient(config_path=None, checkpointer=None, **kwargs)
# client.chat("message", thread_id="t1")  # sync
# for event in client.stream("message"):  # streaming
#     ...
```
