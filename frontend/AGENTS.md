# Agents Architecture

## Overview

OmniHarness is built on a sophisticated agent-based architecture using the [LangGraph SDK](https://github.com/langchain-ai/langgraph) to enable intelligent, stateful AI interactions. This document outlines the agent system architecture, patterns, and best practices for working with agents in the frontend application.

## Architecture Overview

### Core Components

```
┌────────────────────────────────────────────────────────┐
│                    Frontend (Next.js)                  │
├────────────────────────────────────────────────────────┤
│  ┌──────────────┐    ┌──────────────┐    ┌──────────┐  │
│  │ UI Components│───▶│ Thread Hooks │───▶│ LangGraph│  │
│  │              │    │              │    │   SDK    │  │
│  └──────────────┘    └──────────────┘    └──────────┘  │
│         │                    │                  │      │
│         │                    ▼                  │      │
│         │            ┌──────────────┐           │      │
│         └───────────▶│ Thread State │◀──────────┘      │
│                      │  Management  │                  │
│                      └──────────────┘                  │
└────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────┐
│              LangGraph Backend (lead_agent)            │
│  ┌────────────┐  ┌──────────┐  ┌───────────────────┐   │
│  │Main Agent  │─▶│Sub-Agents│─▶│  Tools & Skills   │   │
│  └────────────┘  └──────────┘  └───────────────────┘   │
└────────────────────────────────────────────────────────┘
```

## Project Structure

```
tests/
├── e2e/                    # E2E tests (Playwright, Chromium, mocked backend)
└── unit/                   # Unit tests (mirrors src/ layout, powered by Vitest)
src/
├── app/                    # Next.js App Router pages
│   ├── api/                # API routes
│   ├── workspace/          # Main workspace pages
│   └── mock/               # Mock/demo pages
├── components/             # React components
│   ├── ui/                 # Reusable UI components
│   ├── workspace/          # Workspace-specific components
│   ├── landing/            # Landing page components
│   └── ai-elements/        # AI-related UI elements
├── core/                   # Core business logic
│   ├── api/                # API client & data fetching
│   ├── artifacts/          # Artifact management
│   ├── config/              # App configuration
│   ├── i18n/               # Internationalization
│   ├── mcp/                # MCP integration
│   ├── messages/           # Message handling
│   ├── models/             # Data models & types
│   ├── settings/           # User settings
│   ├── skills/             # Skills system
│   ├── threads/            # Thread management
│   ├── todos/              # Todo system
│   └── utils/              # Utility functions
├── hooks/                  # Custom React hooks
├── lib/                    # Shared libraries & utilities
├── server/                 # Server-side code (Not available yet)
│   └── better-auth/        # Authentication setup (Not available yet)
└── styles/                 # Global styles
```

### Artifact viewers

Registered coding jobs link **Open the app** to `/workspace/apps/{app_id}` with native anchors. Chat-to-app navigation must load a new document: client-side transitions retain the chat CSP, which cannot frame `/api/apps/`. The published build remains a separate sample-data preview when the job includes app checks or registration. Preview metadata is scoped to the chat; generic files are not labelled as sample data.

File previews and saved artifacts share `ViewerHeader`, accessible icon controls, preview sizes, and the mobile `ArtifactOverlay`. Keep their renderers separate: file/live-preview frame links and stored artifact frames retain their existing sandbox rules. Regression coverage lives in `tests/rendering/code-job.spec.ts`, `artifacts-viewer.spec.ts`, and `live-preview.spec.ts`.

### Technology Stack

- **LangGraph SDK** (`@langchain/langgraph-sdk@1.5.3`) - Agent orchestration and streaming
- **LangChain Core** (`@langchain/core@1.1.15`) - Fundamental AI building blocks
- **TanStack Query** (`@tanstack/react-query@5.90.17`) - Server state management
- **React Hooks** - Thread lifecycle and state management
- **Shadcn UI** - UI components
- **MagicUI** - Magic UI components
- **React Bits** - React bits components

### Interaction Ownership

- `src/app/workspace/chats/[thread_id]/page.tsx` owns composer busy-state wiring.
- `src/core/threads/hooks.ts` owns pre-submit upload state and thread submission.
- `src/hooks/usePoseStream.ts` is a passive store selector; global WebSocket lifecycle stays in `App.tsx`.

## Resources

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangChain Core Concepts](https://js.langchain.com/docs/concepts)
- [TanStack Query Documentation](https://tanstack.com/query/latest)
- [Next.js App Router](https://nextjs.org/docs/app)

## Contributing

When adding new agent features:

1. Follow the established project structure
2. Add comprehensive TypeScript types
3. Implement proper error handling
4. Write unit tests under `tests/unit/` (run with `pnpm test`) and E2E tests under `tests/e2e/` (run with `pnpm test:e2e`)
5. Update this documentation
6. Follow the code style guide (ESLint + Prettier)

## License

This agent architecture is part of the OmniHarness project.
