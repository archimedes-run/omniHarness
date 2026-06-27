"""Workflow run executor — Phase 1 Slice 2.

Single entrypoint: execute_workflow_run(workflow_run_id, *, app).

This function is the ONLY place that launches a lead-agent run for a workflow.
It calls launch_agent_run_detached() from app.gateway.services — the same
function the HTTP thread-runs router uses — so a workflow run IS a normal run
visible in the existing chat/run views, executed through the same pipeline.

Called by:
- POST /api/workflows/{id}/run via FastAPI BackgroundTask (Slice 2 manual runs)
- Phase 2 scheduler (unchanged call signature)
- Phase 4 event triggers (unchanged call signature)
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from langchain_core.messages import HumanMessage

from app.gateway.services import build_run_config, launch_agent_run_detached
from omniharness.platform.events import EventSource
from omniharness.platform.writer import emit_platform_event
from omniharness.runtime import ConflictError, DisconnectMode, RunContext, RunStatus

logger = logging.getLogger(__name__)

# WorkflowRun statuses that mean execution is already done — guard against double execution.
_TERMINAL_WF_STATUSES: frozenset[str] = frozenset({"succeeded", "failed", "canceled", "expired"})

# Map underlying RunStatus → WorkflowRun terminal status.
_RUN_STATUS_TO_WF_STATUS: dict[str, str] = {
    RunStatus.success: "succeeded",
    RunStatus.error: "failed",
    RunStatus.interrupted: "failed",
    RunStatus.timeout: "expired",
}


def _build_run_ctx(app) -> RunContext:
    """Build a RunContext from app.state — mirrors get_run_context() without Request."""
    app_config = getattr(app.state, "config", None)
    return RunContext(
        checkpointer=getattr(app.state, "checkpointer", None),
        store=getattr(app.state, "store", None),
        event_store=getattr(app.state, "run_event_store", None),
        run_events_config=getattr(app_config, "run_events", None),
        thread_store=getattr(app.state, "thread_store", None),
        app_config=app_config,
        preview_controller=getattr(app.state, "preview_controller", None),
    )


async def _fail_run(
    wf_run_repo,
    event_store,
    workflow_run_id: str,
    workflow_id: str,
    error_summary: str,
    *,
    step_run_repo=None,
    step_run_id: str | None = None,
) -> None:
    """Transition a workflow_run to failed, set error_summary, and emit event."""
    try:
        await wf_run_repo.set_error_summary(workflow_run_id, error_summary)
        await wf_run_repo.transition_status(workflow_run_id, "failed")
    except Exception:
        logger.exception("Failed to set workflow_run %s to failed", workflow_run_id)

    if step_run_repo and step_run_id:
        try:
            await step_run_repo.update_status(step_run_id, "failed", error_summary=error_summary)
        except Exception:
            logger.debug("Failed to update step_run %s to failed (non-fatal)", step_run_id)

    if event_store:
        try:
            await emit_platform_event(
                event_store,
                thread_id=f"plat-workflow-{workflow_id}",
                event_type="workflow.run.failed",
                source=EventSource.WORKFLOW,
                metadata={"workflow_id": workflow_id, "workflow_run_id": workflow_run_id, "error": error_summary},
            )
        except Exception:
            logger.debug("Failed to emit workflow.run.failed event (non-fatal)", exc_info=True)


async def execute_workflow_run(workflow_run_id: str, *, app) -> None:
    """Execute a workflow run end-to-end through the existing run pipeline.

    This is the single callable the manual-run API, the Phase 2 scheduler,
    and Phase 4 triggers all invoke.  It is idempotent: calling it on an
    already-terminal workflow_run is a silent no-op.

    Invariants:
    - A workflow_run is NEVER left in "running" on any exit path.
    - The underlying thread+run is always launched through launch_agent_run_detached(),
      the same function the HTTP runs router uses.
    - Lifecycle events carry source="workflow" in the shared run_events table.
    """
    # ── 0. Pull singletons from app.state ───────────────────────────────────
    wf_run_repo = getattr(app.state, "workflow_run_repo", None)
    wf_repo = getattr(app.state, "workflow_repo", None)
    wf_version_repo = getattr(app.state, "workflow_version_repo", None)
    wf_step_run_repo = getattr(app.state, "workflow_step_run_repo", None)
    wf_artifact_link_repo = getattr(app.state, "workflow_artifact_link_repo", None)
    bridge = getattr(app.state, "stream_bridge", None)
    run_mgr = getattr(app.state, "run_manager", None)
    run_ctx = _build_run_ctx(app)
    event_store = run_ctx.event_store

    if wf_run_repo is None or wf_repo is None or bridge is None or run_mgr is None:
        logger.error("execute_workflow_run: required singletons missing from app.state (persistence backend may be 'memory')")
        return

    # ── 1. Load workflow_run ─────────────────────────────────────────────────
    wf_run = await wf_run_repo.get(workflow_run_id)
    if wf_run is None:
        logger.error("execute_workflow_run: workflow_run %s not found", workflow_run_id)
        return

    # Idempotent guard — already terminal or already being executed
    if wf_run["status"] in _TERMINAL_WF_STATUSES:
        logger.info("execute_workflow_run: %s already terminal (%s), skipping", workflow_run_id, wf_run["status"])
        return
    if wf_run["status"] == "running":
        logger.warning("execute_workflow_run: %s already running, skipping duplicate invocation", workflow_run_id)
        return

    workflow_id = wf_run["workflow_id"]

    # ── 2. Load workflow + current version ───────────────────────────────────
    wf = await wf_repo.get(workflow_id)
    if wf is None:
        await _fail_run(wf_run_repo, event_store, workflow_run_id, workflow_id, "workflow not found")
        return

    version_id = wf.get("current_version_id")
    instruction_prompt: str | None = None
    if version_id and wf_version_repo is not None:
        version = await wf_version_repo.get(version_id)
        if version:
            instruction_prompt = version.get("instruction_prompt")

    if not instruction_prompt:
        await _fail_run(wf_run_repo, event_store, workflow_run_id, workflow_id, "workflow has no runnable instruction")
        return

    owner_id: str | None = wf.get("owner_id")

    # ── 3. queued → running; emit workflow.run.started ───────────────────────
    try:
        await wf_run_repo.transition_status(workflow_run_id, "running")
    except Exception as exc:
        logger.error("execute_workflow_run: cannot transition %s to running: %s", workflow_run_id, exc)
        return

    if event_store:
        try:
            await emit_platform_event(
                event_store,
                thread_id=f"plat-workflow-{workflow_id}",
                event_type="workflow.run.started",
                source=EventSource.WORKFLOW,
                metadata={"workflow_id": workflow_id, "workflow_run_id": workflow_run_id},
            )
        except Exception:
            logger.debug("Failed to emit workflow.run.started (non-fatal)", exc_info=True)

    # Create a coarse step_run for the timeline (granular steps are Slice 4).
    step_run_id: str | None = None
    if wf_step_run_repo is not None:
        try:
            step_run_id = str(uuid.uuid4())
            await wf_step_run_repo.create(
                id=step_run_id,
                workflow_run_id=workflow_run_id,
                step_key="workflow_execution",
                step_index=0,
            )
            await wf_step_run_repo.update_status(step_run_id, "running")
        except Exception:
            logger.debug("Failed to create step_run (non-fatal)", exc_info=True)
            step_run_id = None

    # ── 4. Launch the underlying run through the existing pipeline ───────────
    thread_id = str(uuid.uuid4())
    graph_input = {"messages": [HumanMessage(content=instruction_prompt)]}
    run_config = build_run_config(thread_id, None, {"workflow_run_id": workflow_run_id})
    if owner_id:
        ctx_dict = run_config.setdefault("context", {})
        if isinstance(ctx_dict, dict):
            ctx_dict.setdefault("user_id", owner_id)

    record = None
    try:
        record = await launch_agent_run_detached(
            bridge=bridge,
            run_mgr=run_mgr,
            run_ctx=run_ctx,
            thread_id=thread_id,
            graph_input=graph_input,
            run_config=run_config,
            user_id=owner_id,
            metadata={"workflow_run_id": workflow_run_id},
            multitask_strategy="reject",  # fresh thread — no conflict possible
            on_disconnect=DisconnectMode.continue_,
            stream_modes=["values"],
        )
    except (ConflictError, Exception) as exc:
        error_summary = f"Failed to launch run: {exc}"
        logger.exception("execute_workflow_run: launch failed for %s", workflow_run_id)
        await _fail_run(wf_run_repo, event_store, workflow_run_id, workflow_id, error_summary, step_run_repo=wf_step_run_repo, step_run_id=step_run_id)
        return

    # ── 5. Persist thread_id + run_id immediately so UI can deep-link ────────
    underlying_run_id = record.run_id
    try:
        await wf_run_repo.set_thread_run(workflow_run_id, thread_id=thread_id, run_id=underlying_run_id)
    except Exception:
        logger.warning("Failed to persist thread_id/run_id on workflow_run %s (non-fatal)", workflow_run_id, exc_info=True)

    # ── 6. Await the underlying run to completion ────────────────────────────
    error_summary = None
    try:
        await record.task
    except asyncio.CancelledError:
        error_summary = "Underlying run was cancelled"
    except Exception as exc:
        error_summary = f"Underlying run error: {exc}"

    # record.status is set by run_agent() in its finally block
    run_status = record.status

    # ── 7. On success: link artifacts, succeed step_run, transition ──────────
    if run_status == RunStatus.success and error_summary is None:
        # Link artifacts by reference (virtual paths from thread state — no bytes stored)
        if wf_artifact_link_repo is not None and run_ctx.checkpointer is not None:
            try:
                ckpt_config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
                ckpt_tuple = await run_ctx.checkpointer.aget_tuple(ckpt_config)
                if ckpt_tuple is not None:
                    artifacts = (getattr(ckpt_tuple, "checkpoint", {}) or {}).get("channel_values", {}).get("artifacts") or []
                    for artifact_path in artifacts:
                        await wf_artifact_link_repo.create(
                            id=str(uuid.uuid4()),
                            workflow_run_id=workflow_run_id,
                            artifact_path=str(artifact_path),
                            artifact_type="file",
                        )
            except Exception:
                logger.debug("Failed to link artifacts for workflow_run %s (non-fatal)", workflow_run_id, exc_info=True)

        if step_run_id and wf_step_run_repo is not None:
            try:
                await wf_step_run_repo.update_status(step_run_id, "succeeded")
            except Exception:
                logger.debug("Failed to update step_run to succeeded (non-fatal)", exc_info=True)

        try:
            await wf_run_repo.transition_status(workflow_run_id, "succeeded")
        except Exception:
            logger.exception("Failed to transition workflow_run %s to succeeded", workflow_run_id)

        if event_store:
            try:
                await emit_platform_event(
                    event_store,
                    thread_id=f"plat-workflow-{workflow_id}",
                    event_type="workflow.run.succeeded",
                    source=EventSource.WORKFLOW,
                    metadata={"workflow_id": workflow_id, "workflow_run_id": workflow_run_id, "thread_id": thread_id},
                )
            except Exception:
                logger.debug("Failed to emit workflow.run.succeeded (non-fatal)", exc_info=True)
        return

    # ── 8. On failure: set error_summary, transition to failed/expired ────────
    wf_terminal = _RUN_STATUS_TO_WF_STATUS.get(str(run_status), "failed")
    if error_summary is None:
        error_summary = f"Underlying run ended with status: {run_status}"

    await _fail_run(
        wf_run_repo,
        event_store,
        workflow_run_id,
        workflow_id,
        error_summary,
        step_run_repo=wf_step_run_repo,
        step_run_id=step_run_id,
    )
    # Override status to "expired" if the run timed out
    if wf_terminal == "expired":
        try:
            await wf_run_repo.transition_status(workflow_run_id, "expired")
        except Exception:
            logger.debug("Failed to re-transition to expired (may already be failed)", exc_info=True)
