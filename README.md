# OmniHarness


[![Star History Chart](https://api.star-history.com/svg?repos=archimedes-run/omniHarness&type=Date)](https://star-history.com/#archimedes-run/omniHarness&Date)


[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](./backend/pyproject.toml)
[![Node.js](https://img.shields.io/badge/Node.js-22%2B-339933?logo=node.js&logoColor=white)](./Makefile)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

OmniHarness is an open-source **super agent harness** that orchestrates **sub-agents**, **persistent memory**, and **sandboxed execution** to handle tasks that take minutes to hours — powered by extensible skills and MCP tools.

Built on [LangGraph](https://github.com/langchain-ai/langgraph) and [LangChain](https://github.com/langchain-ai/langchain). Works with any OpenAI-compatible LLM.

---

## Table of Contents

- [What it does](#what-it-does)
- [Quick Start](#quick-start)
  - [Prerequisites](#prerequisites)
  - [Configuration](#configuration)
  - [Running with Docker](#running-with-docker)
    - [1. Pull the sandbox image](#1-pull-the-sandbox-image)
    - [2. Start all services](#2-start-all-services)
    - [3. How it works under the hood](#3-how-it-works-under-the-hood)
    - [4. Management commands](#4-management-commands)
    - [5. Troubleshooting sandbox issues](#5-troubleshooting-sandbox-issues)
  - [Production deployment](#production-deployment)
  - [Advanced](#advanced)
    - [Sandbox Mode](#sandbox-mode)
    - [MCP Servers](#mcp-servers)
    - [IM Channels](#im-channels)
    - [Observability](#observability)
- [Core Features](#core-features)
  - [Skills & Tools](#skills--tools)
  - [Sub-Agents](#sub-agents)
  - [Sandbox & File System](#sandbox--file-system)
  - [Long-Term Memory](#long-term-memory)
  - [Context Engineering](#context-engineering)
- [Recommended Models](#recommended-models)
- [Embedded Python Client](#embedded-python-client)
- [Security Notice](#security-notice)
- [Contributing](#contributing)
- [License](#license)
- [Acknowledgments](#acknowledgments)

---

## What it does

- **Research & report generation** — web search, fetch, multi-source synthesis, structured output
- **Code execution** — sandboxed Python and shell in isolated per-thread containers
- **File operations** — read, write, generate documents, slides, websites, data visualisations
- **Sub-agent delegation** — fan out to specialised agents running in parallel, collect results
- **Persistent memory** — remembers preferences, context, and facts across sessions
- **MCP tool integration** — connect any Model Context Protocol server as a first-class toolset

---

## Quick Start

Docker is the only supported way to run OmniHarness. It handles all service wiring, sandbox isolation, and path mappings automatically.

### Prerequisites

| Requirement | Minimum | Notes |
|-------------|---------|-------|
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | 4.x+ | macOS, Windows, Linux. [OrbStack](https://orbstack.dev) also works on macOS. |
| Docker Compose | v2 | Bundled with Docker Desktop |
| Disk space | 12 GB free | ~9 GB for the sandbox image + build artefacts |
| RAM | 8 GB | 16 GB recommended for parallel sub-agents |
| CPU | 4 vCPU | 8 vCPU recommended |

> **Linux users**: add your user to the `docker` group (`sudo usermod -aG docker $USER`) so you can run Docker commands without `sudo`.

### Configuration

1. **Clone the repository**

   ```bash
   git clone https://github.com/archimedes-run/omni-harness.git
   cd omni-harness
   ```

2. **Run the setup wizard**

   ```bash
   make setup
   ```

   The wizard guides you through choosing an LLM provider, optional web search, and sandbox settings. It generates `config.yaml` and writes your API keys to `.env`.

   Run `make doctor` at any time to verify your configuration.

   <details>
   <summary>Manual model configuration examples</summary>

   ```yaml
   models:
     - name: gpt-4o
       display_name: GPT-4o
       use: langchain_openai:ChatOpenAI
       model: gpt-4o
       api_key: $OPENAI_API_KEY

     - name: claude-sonnet-4-6
       display_name: Claude Sonnet 4.6
       use: langchain_anthropic:ChatAnthropic
       model: claude-sonnet-4-6
       api_key: $ANTHROPIC_API_KEY
       supports_thinking: true

     - name: gemini-2-5-pro
       display_name: Gemini 2.5 Pro
       use: langchain_google_genai:ChatGoogleGenerativeAI
       model: gemini-2.5-pro
       gemini_api_key: $GEMINI_API_KEY

     - name: openrouter-model
       display_name: Any model via OpenRouter
       use: langchain_openai:ChatOpenAI
       model: google/gemini-2.5-flash-preview
       api_key: $OPENROUTER_API_KEY
       base_url: https://openrouter.ai/api/v1

     - name: qwen3-32b-vllm
       display_name: Qwen3 32B (self-hosted vLLM)
       use: omniharness.models.vllm_provider:VllmChatModel
       model: Qwen/Qwen3-32B
       api_key: $VLLM_API_KEY
       base_url: http://localhost:8000/v1
       supports_thinking: true
       when_thinking_enabled:
         extra_body:
           chat_template_kwargs:
             enable_thinking: true
   ```

   CLI-backed providers:

   ```yaml
   models:
     - name: codex-cli
       display_name: GPT-5.4 (Codex CLI)
       use: omniharness.models.openai_codex_provider:CodexChatModel
       model: gpt-5.4
       supports_thinking: true

     - name: claude-code-oauth
       display_name: Claude Sonnet 4.6 (Claude Code OAuth)
       use: omniharness.models.claude_provider:ClaudeChatModel
       model: claude-sonnet-4-6
       supports_thinking: true
   ```

   - Codex CLI reads auth from `~/.codex/auth.json`
   - Claude Code OAuth reads from `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_AUTH_TOKEN`, or `~/.claude/.credentials.json`

   </details>

3. **Set the repository root in `.env`**

   The Docker sandbox uses bind mounts to give each agent thread an isolated filesystem on the host. It needs to know the absolute path to this repository:

   ```bash
   # .env
   OMNI_HARNESS_ROOT=/absolute/path/to/omni-harness
   ```

   On macOS/Linux you can generate this automatically:

   ```bash
   echo "OMNI_HARNESS_ROOT=$(pwd)" >> .env
   ```

   > This is the most common reason sandbox tools (`bash`, `write_file`, `execute_python`) silently fail. If agent output looks like it's running but files never appear, check this value first.

### Running with Docker

#### 1. Pull the sandbox image

```bash
make docker-init
```

This pulls the [AIO Sandbox](https://github.com/agent-infra/sandbox) container image (~9 GB) and tags it locally as `omni-harness-sandbox:latest`. The AIO Sandbox is a pre-built, isolated execution environment with Python 3, Node.js, bash, and common system tools — one container is spawned per agent thread and automatically cleaned up after 10 minutes of idle time.

You only need to run this once, or again after an image update. The download can take several minutes depending on your connection.

**Verifying the image is ready:**

```bash
docker images | grep omni-harness-sandbox
# omni-harness-sandbox   latest   <id>   <date>   9.35GB
```

**Manual tag** (if `make docker-init` fails or you already have the image under a different name):

```bash
docker tag <your-existing-image> omni-harness-sandbox:latest
```

Then confirm `config.yaml` has the image name set:

```yaml
sandbox:
  use: omniharness.community.aio_sandbox:AioSandboxProvider
  image: omni-harness-sandbox:latest
```

#### 2. Start all services

```bash
make docker-start
```

Access: **http://localhost:2026**

This starts three containers:

| Container | Role | Internal port |
|-----------|------|---------------|
| `omni-harness-nginx` | Reverse proxy — single entry point | 2026 |
| `omni-harness-gateway` | Backend API + LangGraph agent runtime | 8001 |
| `omni-harness-frontend` | Next.js web UI (hot-reload in dev) | 3000 |

Source code is mounted directly into the containers (`backend/` and `frontend/src/`), so code changes are reflected without a rebuild.

**Stop services:**

```bash
make docker-stop
```

**Restart after a config change:**

```bash
make docker-stop && make docker-start
```

> `config.yaml` changes (models, skills, tools) are hot-reloaded automatically by the gateway — no restart needed for those. A restart is only required when adding new environment variables to `.env`.

#### 3. How it works under the hood

Understanding this architecture helps diagnose issues quickly.

```
Your browser
    │
    ▼
nginx (port 2026)
    ├── /api/langgraph/* → gateway:8001  (agent runtime / LangGraph)
    ├── /api/*          → gateway:8001  (REST API)
    └── /*              → frontend:3000 (Next.js UI)

gateway container
    ├── Reads config.yaml (hot-reload on mtime change)
    ├── Mounts /var/run/docker.sock  ← can run Docker commands on the host
    ├── On each agent thread:
    │     docker run omni-harness-sandbox:latest  (spawns on HOST daemon)
    │         bind-mount: $OMNI_HARNESS_ROOT/backend/.omni-harness/
    │                     users/{user}/threads/{thread}/user-data/
    │     Sandbox is reachable at host.docker.internal:{port}
    └── Sandbox containers auto-removed after 10 min idle (--rm + idle GC)
```

**Key environment variables set automatically by docker-compose:**

| Variable | Value | Purpose |
|----------|-------|---------|
| `OMNI_HARNESS_ROOT` | from `.env` | Root of the repo on the host — required for bind mounts |
| `OMNI_HARNESS_HOST_BASE_DIR` | `$OMNI_HARNESS_ROOT/backend/.omni-harness` | Host path prefix for thread directories |
| `OMNI_HARNESS_SANDBOX_HOST` | `host.docker.internal` | Hostname to reach sandbox containers from inside the gateway |
| `OMNI_HARNESS_HOST_SKILLS_PATH` | `$OMNI_HARNESS_ROOT/skills` | Host path for skills directory mount |

#### 4. Management commands

```bash
make docker-start       # Start all services (dev mode, hot-reload)
make docker-stop        # Stop all services
make docker-restart     # Stop then start
make docker-logs        # Tail logs from all containers
make docker-status      # Show container status
make docker-init        # Pull / re-tag sandbox image (run once)
```

View logs for a specific service:

```bash
docker logs -f omni-harness-gateway    # backend + agent logs
docker logs -f omni-harness-frontend   # Next.js build / page logs
docker logs -f omni-harness-nginx      # proxy access logs
```

List active sandbox containers (spawned per agent thread):

```bash
docker ps --filter "name=omni-harness-sandbox"
```

#### 5. Troubleshooting sandbox issues

The sandbox is what gives agents the ability to run `bash`, write files, and execute Python. If those tools silently fail or return errors, work through this checklist:

**Sandbox containers never start**

Check that the image exists and the tag matches `config.yaml`:

```bash
docker images | grep omni-harness-sandbox
# Expected: omni-harness-sandbox   latest   <id>
```

If missing, re-run `make docker-init` or tag an existing image manually (see [step 1](#1-pull-the-sandbox-image)).

**`bind source path does not exist` errors in gateway logs**

`OMNI_HARNESS_ROOT` is unset or wrong. The gateway uses it to build host-side bind-mount paths. Fix:

```bash
# In your .env file at the project root:
OMNI_HARNESS_ROOT=/absolute/path/to/omni-harness
```

Then restart: `make docker-stop && make docker-start`.

**Sandbox starts but agent can't reach it**

The gateway connects to sandbox containers via `host.docker.internal`. Verify it resolves:

```bash
docker exec omni-harness-gateway ping -c 1 host.docker.internal
```

On Linux, add `extra_hosts: ["host.docker.internal:host-gateway"]` to the gateway service in `docker/docker-compose-dev.yaml` if it doesn't resolve.

**Port conflicts on startup**

Port 2026 is the default entry point. If it's in use:

```bash
lsof -i :2026
# Change the port in docker/docker-compose-dev.yaml:
#   ports: ["YOUR_PORT:2026"]
```

**Checking the gateway picked up your `config.yaml` changes**

```bash
docker exec omni-harness-gateway /app/backend/.venv/bin/python3 -c "
from omniharness.config.app_config import get_app_config
cfg = get_app_config()
print('sandbox.image:', cfg.sandbox.image)
print('models:', [m.name for m in cfg.models])
"
```

### Production deployment

For a stable, persistent server (pre-built images, no source mounts):

```bash
make up      # Build images and start all services
make down    # Stop and remove containers
```

| Target | Minimum | Recommended |
|--------|---------|-------------|
| Docker dev (`make docker-start`) | 4 vCPU, 8 GB RAM | 8 vCPU, 16 GB RAM |
| Production (`make up`) | 8 vCPU, 16 GB RAM | 16 vCPU, 32 GB RAM |

---

### Advanced

#### Sandbox Mode

OmniHarness supports three sandbox execution modes:

- **Docker** (recommended) — each thread gets an isolated container with a full filesystem, powered by [AIO Sandbox](https://github.com/agent-infra/sandbox)
- **Local** — file tools mapped to per-thread host directories; host `bash` disabled by default
- **Kubernetes** — containers provisioned as Pods via the optional provisioner service

`config.yaml` sandbox section:

```yaml
sandbox:
  use: omniharness.community.aio_sandbox:AioSandboxProvider
  image: omni-harness-sandbox:latest     # local tag — see docker-init
  bash_output_max_chars: 20000
  read_file_output_max_chars: 50000
  ls_output_max_chars: 20000
```

See [Configuration Guide](backend/docs/CONFIGURATION.md#sandbox) for all options including idle timeout, replica count, and Kubernetes provisioner setup.

#### MCP Servers

Connect any MCP server to extend the agent's toolset. HTTP/SSE and stdio transports are supported. OAuth token flows (`client_credentials`, `refresh_token`) are supported for HTTP/SSE servers.

See [MCP Server Guide](backend/docs/MCP_SERVER.md) for setup instructions.

#### IM Channels

OmniHarness can receive tasks from messaging apps. Channels auto-start when configured and require no public IP.

| Channel | Transport |
|---------|-----------|
| Telegram | Bot API long-polling |
| Slack | Socket Mode |

**Configuration in `config.yaml`:**

```yaml
channels:
  langgraph_url: http://localhost:8001/api
  gateway_url: http://localhost:8001

  telegram:
    enabled: true
    bot_token: $TELEGRAM_BOT_TOKEN
    allowed_users: []   # empty = allow all

  slack:
    enabled: true
    bot_token: $SLACK_BOT_TOKEN    # xoxb-...
    app_token: $SLACK_APP_TOKEN    # xapp-... (Socket Mode)
    allowed_users: []
```

**Keys in `.env`:**

```bash
TELEGRAM_BOT_TOKEN=...
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
```

**Telegram Setup**

1. Chat with [@BotFather](https://t.me/BotFather), send `/newbot`, copy the token.
2. Set `TELEGRAM_BOT_TOKEN` in `.env` and enable the channel in `config.yaml`.

**Slack Setup**

1. Create a Slack App at [api.slack.com/apps](https://api.slack.com/apps).
2. Under **OAuth & Permissions**, add scopes: `app_mentions:read`, `chat:write`, `im:history`, `im:read`, `im:write`, `files:write`.
3. Enable **Socket Mode**, generate an App-Level Token (`xapp-…`) with `connections:write`.
4. Subscribe to bot events: `app_mention`, `message.im`.
5. Set both tokens in `.env` and enable the channel in `config.yaml`.

> When running in Docker Compose, use container service names: `http://gateway:8001/api` and `http://gateway:8001`, or set `OMNI_HARNESS_CHANNELS_LANGGRAPH_URL` and `OMNI_HARNESS_CHANNELS_GATEWAY_URL`.

**In-chat commands:**

| Command | Description |
|---------|-------------|
| `/new` | Start a new conversation |
| `/status` | Show current thread info |
| `/models` | List available models |
| `/memory` | View memory |
| `/help` | Show help |

#### Observability

**LangSmith:**

```bash
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=lsv2_pt_...
LANGSMITH_PROJECT=my-project
```

**Langfuse:**

```bash
LANGFUSE_TRACING=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

Both can be enabled simultaneously.

---

## Core Features

### Skills & Tools

Skills are structured capability modules — a `SKILL.md` file that defines a workflow, best practices, and references. OmniHarness ships with built-in skills for research, report generation, slide creation, web pages, and chart visualisation. You can add your own or replace the built-in ones.

Skills are loaded progressively — only when a task needs them. This keeps the context window lean.

Tools ship as a core set — web search, web fetch, file operations, bash execution — and extend via MCP servers or custom Python functions.

```
/mnt/skills/public/
├── research/SKILL.md
├── report-generation/SKILL.md
├── slide-creation/SKILL.md
├── web-page/SKILL.md
└── chart-visualization/SKILL.md

/mnt/skills/custom/
└── your-skill/SKILL.md
```

### Sub-Agents

The lead agent can spawn specialised sub-agents on the fly. Each runs in its own isolated context with scoped tools and a defined termination condition. Sub-agents execute in parallel when possible and report structured results back to the lead agent, which synthesises everything into a coherent output.

Up to 3 sub-agents run concurrently by default (configurable).

### Sandbox & File System

Each task gets a per-thread execution environment powered by [AIO Sandbox](https://github.com/agent-infra/sandbox) — an isolated Docker container with a full filesystem the agent can read, write, and execute inside.

```
/mnt/user-data/
├── uploads/     ← files you upload
├── workspace/   ← agent working directory
└── outputs/     ← final deliverables
```

Containers are spawned on demand, bind-mounted to a per-thread directory on the host, and removed automatically after 10 minutes of idle time. With `LocalSandboxProvider`, file tools map to per-thread host directories instead — host `bash` is disabled by default in that mode.

### Long-Term Memory

Across sessions, OmniHarness builds a persistent memory of your preferences, working context, and accumulated facts. Memory is stored locally per user and injected into the system prompt on each turn. The agent extracts and stores facts asynchronously after each conversation.

### Context Engineering

- **Isolated sub-agent context** — each sub-agent sees only what it needs
- **Automatic summarisation** — completed sub-task context is compressed to keep the window lean
- **Tool-call recovery** — dangling tool calls from interrupted turns are resolved before the next model invocation so provider-strict models do not fail with malformed history errors

---

## Recommended Models

OmniHarness works with any OpenAI-compatible LLM. It performs best with models that support:

- Long context windows (100k+ tokens)
- Reasoning / extended thinking
- Multimodal input (vision)
- Reliable tool use

Tested providers: OpenAI, Anthropic, Google Gemini, DeepSeek, vLLM (self-hosted), OpenRouter (multi-model gateway).

---

## Embedded Python Client

Use OmniHarness as a library without running HTTP services:

```python
from omniharness.client import OmniHarnessClient

client = OmniHarnessClient()

# Synchronous chat
response = client.chat("Summarise this paper", thread_id="my-thread")

# Streaming (LangGraph SSE protocol)
for event in client.stream("Write a report on quantum computing"):
    if event.type == "messages-tuple" and event.data.get("type") == "ai":
        print(event.data["content"], end="", flush=True)

# Management
models = client.list_models()
skills = client.list_skills()
client.update_skill("web-search", enabled=True)
client.upload_files("thread-1", ["./report.pdf"])
```

All dict-returning methods are validated against Gateway Pydantic response schemas in CI to keep the embedded client in sync with the HTTP API.

See [`backend/packages/harness/omniharness/client.py`](backend/packages/harness/omniharness/client.py) for full documentation.

---

## Security Notice

OmniHarness has high-privilege capabilities — system command execution, file read/write — and is designed for deployment in a **local trusted environment** (loopback only by default).

If you expose it to a network, apply appropriate controls:

- **Authentication** — OmniHarness has a built-in auth system. Ensure it is enabled and `AUTH_JWT_SECRET` is set to a strong secret in production.
- **IP allowlist** — restrict inbound access to known addresses via firewall rules or nginx ACLs.
- **Network isolation** — place the service and trusted clients on a dedicated VLAN where possible.
- **TLS** — terminate HTTPS at the reverse proxy for any non-localhost deployment.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and workflow.

For local (non-Docker) development:

```bash
make check    # Verify prerequisites: Node.js 22+, pnpm, uv, nginx
make install  # Install backend + frontend dependencies
make dev      # Start all services with hot-reload (http://localhost:2026)
```

## License

MIT — see [LICENSE](./LICENSE).

---

## Acknowledgments

OmniHarness is built on the work of the open-source community. Special thanks to:

- **[LangGraph](https://github.com/langchain-ai/langgraph)** — multi-agent orchestration runtime
- **[LangChain](https://github.com/langchain-ai/langchain)** — LLM integration framework
- **[AIO Sandbox](https://github.com/agent-infra/sandbox)** — isolated per-thread execution containers
- **[Shadcn UI](https://ui.shadcn.com/)** — frontend component system
- **[Next.js](https://nextjs.org/)** — frontend framework
