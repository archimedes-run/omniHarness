install:
	uv sync

dev:
	PYTHONPATH=. uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001 --reload

gateway:
	PYTHONPATH=. uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001

test:
	PYTHONPATH=. uv run pytest tests/ -v

# `uv run`, not `uvx`. uvx resolves the LATEST ruff every invocation, so a new
# release adds rules and turns CI red without anyone changing code — which is
# how this repo ended up with a red baseline nobody trusted. `uv run` uses the
# version pinned in [dependency-groups].dev, so CI and local agree by
# construction and a ruff upgrade is a deliberate dependency bump.
lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check . --fix && uv run ruff format .

# Type checking. NOT in CI yet — see the report in the PR that added it.
# Wiring a check that currently fails would make it decorative on day one,
# which is the exact antipattern the lint audit just found.
typecheck:
	uv run mypy app/policy app/trigger_engine packages/session_watcher/session_watcher

typecheck-all:
	uv run mypy app packages
