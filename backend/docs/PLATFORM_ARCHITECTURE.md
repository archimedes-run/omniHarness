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
