install:
	uv sync

dev:
	mkdir -p .omni-harness && PYTHONPATH=. uv run uvicorn app.gateway.app:app --host 127.0.0.1 --port 8001 --reload --reload-exclude="$(CURDIR)/.omni-harness"

gateway:
	PYTHONPATH=. uv run uvicorn app.gateway.app:app --host 127.0.0.1 --port 8001

# Parallel across all cores (pytest-xdist). `--dist loadfile` keeps each test
# file on one worker, in file order, as a serial run has it: several files are
# one ordered scenario on a module-scoped fixture (a real multi-worker gateway
# in tests/policy_multiworker/, for one), which per-test distribution splits
# across processes. -q with -rfE: a summary plus every failure and error,
# instead of one line per test for thousands of tests.
test:
	PYTHONPATH=. uv run pytest tests/ -n auto --dist loadfile -q -rfE

# One process, verbose: for bisecting an order-dependent failure, or when a
# test misbehaves only under xdist.
test-serial:
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
