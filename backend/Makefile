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

# The lead agent's eval suite (spec 009 Slice 0). EVAL_MODEL=mock (default:
# scripted models, no network, no secrets) or real (the configured model,
# against an isolated gateway per trial, cost-capped by EVAL_BUDGET_USD,
# default 5). See tests/eval/omni_eval/run.py for EVAL_TASKS, EVAL_TRIALS,
# EVAL_ENV_FILE.
eval:
	PYTHONPATH=.:tests/eval uv run python -m omni_eval.run

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
