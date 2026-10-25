"""Coding jobs in the gateway (spec 009, Slice 1): wiring.

`start(app)` runs in the gateway lifespan. It opens the job store, works out
whether coding jobs can run here at all (the hardened container sandbox, the
gateway's address on the sandbox network for the LLM proxy, a model the proxy
can serve), starts the proxy listener, and registers the manager as the
harness's CodeJobController so `code_job` is offered. When any precondition
fails, the controller still answers `unavailable_reason()`, the tool is not
offered, and the reason is logged once.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI

logger = logging.getLogger(__name__)


def _hardened() -> bool:
    from app.policy.runtime_floors import bash_runs_in_the_hardened_sandbox

    return bash_runs_in_the_hardened_sandbox()


def production_sandbox_for(thread_id: str, user_id: str):
    """The thread's own container sandbox, through the provider (keyed, #98)."""
    from omniharness.community.aio_sandbox.aio_sandbox import AioSandbox
    from omniharness.community.aio_sandbox.aio_sandbox_provider import AioSandboxProvider
    from omniharness.sandbox.sandbox_provider import get_sandbox_provider

    from .sandbox_ops import AioJobSandbox

    provider = get_sandbox_provider()
    if not isinstance(provider, AioSandboxProvider):
        raise RuntimeError("coding jobs need the container sandbox provider")
    sandbox_id = provider.acquire(thread_id)
    sandbox = provider.get(sandbox_id)
    info = provider.info(sandbox_id)
    if not isinstance(sandbox, AioSandbox) or info is None or not info.container_name:
        raise RuntimeError("the thread's sandbox is not a local container")
    return sandbox_id, AioJobSandbox(sandbox=sandbox, container=info.container_name, touch=lambda: provider.get(sandbox_id))


def start(app: FastAPI) -> None:
    from omniharness.code_jobs import set_code_job_controller
    from omniharness.community.aio_sandbox.local_backend import sandbox_network
    from omniharness.config import get_app_config
    from omniharness.config.paths import get_paths

    from . import upstream as upstream_mod
    from .llm_proxy import ProxyListener, ProxySettings, build_proxy_app
    from .network import sandbox_network_address
    from .runner import CodeJobManager, Settings
    from .store import CodeJobStore

    base = Path(get_paths().base_dir) / "code_jobs"
    store = CodeJobStore(base / "jobs.db")
    app.state.code_job_store = store
    # Jobs a previous process left "running" cannot be watched any more: they
    # are reported as interrupted, never resumed silently or called done.
    # (Only jobs whose worker stopped beating: another worker's live job is
    # left alone.)
    store.reap_stale()

    config = get_app_config()
    cj = config.code_jobs
    proxy_host: str | None = None
    subnets: list = []
    network = sandbox_network()
    if cj.enabled and _hardened() and network:
        proxy_host, subnets = sandbox_network_address(network, cj.proxy_bind)
    app.state.code_job_proxy_host = proxy_host

    def model_name() -> str | None:
        current = get_app_config()
        return current.code_jobs.model or (current.models[0].name if current.models else None)

    def upstream_for():
        return upstream_mod.resolve(get_app_config(), model_name())

    def unavailable() -> str | None:
        current = get_app_config().code_jobs
        if not current.enabled:
            return "coding jobs are turned off in config (code_jobs.enabled)"
        if not _hardened():
            return "they need the container sandbox (the hardened Docker sandbox with the registries proxy)"
        if not proxy_host:
            return "the gateway has no address on the sandbox network for its model proxy"
        _, why = upstream_for()
        return why

    def settings() -> Settings:
        current = get_app_config().code_jobs
        up, _ = upstream_for()
        return Settings(
            proxy_url=f"http://{proxy_host}:{current.proxy_port}/v1" if proxy_host else None,
            proxy_host=proxy_host,
            budget_usd=current.budget_usd,
            monthly_cap_usd=current.monthly_cap_usd,
            wall_seconds=current.wall_seconds,
            verify_timeout_seconds=current.verify_timeout_seconds,
            model_label=up.model if up else "",
        )

    def record_history(body: dict) -> None:
        history = getattr(app.state, "run_history", None)
        if history is None:
            return
        job = body["job"]
        owner = body.pop("owner_id", None)
        history.record(kind="code_job", source_id=job["id"], body=body, status=job["status"], thread_id=job["thread_id"], error=job.get("reason"), owner_id=owner)

    manager = CodeJobManager(store=store, settings=settings, unavailable=unavailable, sandbox_for=lambda t, u: production_sandbox_for(t, u), relay_dir=base / "watch", record_history=record_history)
    app.state.code_job_manager = manager
    set_code_job_controller(manager)

    listener = None
    if proxy_host:
        policy_dir = Path(config.policy.state_dir) if getattr(config.policy, "state_dir", None) else base
        proxy_app = build_proxy_app(
            ProxySettings(
                store=store,
                upstream_for=upstream_for,
                subnets=subnets,
                monthly_cap_usd=cj.monthly_cap_usd,
                rate_per_minute=cj.rate_per_minute,
                max_request_bytes=cj.max_request_bytes,
                prices=dict(cj.prices),
                policy_log=policy_dir / "llm-proxy.jsonl",
            )
        )
        listener = ProxyListener(proxy_app, proxy_host, cj.proxy_port)
        listener.start()
    app.state.code_job_proxy = listener
    reason = unavailable()
    if reason:
        logger.info("code jobs: not offered (%s)", reason)
    else:
        logger.info("code jobs: offered; the worker's model calls go through the proxy on %s:%s", proxy_host, cj.proxy_port)


def stop(app: FastAPI) -> None:
    from omniharness.code_jobs import set_code_job_controller

    listener = getattr(app.state, "code_job_proxy", None)
    if listener is not None:
        listener.stop()
    set_code_job_controller(None)
