"""Tests for the three live-preview loop features:

Feature 3: client-side JS error capture (shim + proxy intercept)
Feature 2: PreviewVerificationMiddleware
Feature 1: PreviewController protocol + GatewayPreviewController adapter
Feature 1a: auto-start hook in worker (RunContext.preview_controller)
Feature 1b: preview_tool
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from omniharness.preview.preview_controller import (
    PreviewController,
    PreviewStatusSummary,
    get_preview_controller,
    reset_preview_controller,
    set_preview_controller,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockController:
    """Minimal in-memory PreviewController for unit testing."""

    def __init__(self, status: PreviewStatusSummary | None = None) -> None:
        self._status = status or PreviewStatusSummary(has_web_app=False, session_status="not_started")
        self.request_preview_calls: list[dict] = []

    async def get_status(self, *, thread_id: str, user_id: str) -> PreviewStatusSummary:
        return self._status

    async def request_preview(self, *, thread_id: str, user_id: str) -> None:
        self.request_preview_calls.append({"thread_id": thread_id, "user_id": user_id})


@pytest.fixture(autouse=True)
def reset_controller():
    """Ensure no controller leaks between tests."""
    reset_preview_controller()
    yield
    reset_preview_controller()


# ---------------------------------------------------------------------------
# Feature: PreviewController singleton
# ---------------------------------------------------------------------------


def test_get_preview_controller_none_by_default():
    assert get_preview_controller() is None


def test_set_and_get_controller():
    ctrl = _MockController()
    set_preview_controller(ctrl)
    assert get_preview_controller() is ctrl


def test_reset_controller():
    ctrl = _MockController()
    set_preview_controller(ctrl)
    reset_preview_controller()
    assert get_preview_controller() is None


def test_preview_controller_protocol_check():
    ctrl = _MockController()
    assert isinstance(ctrl, PreviewController)


# ---------------------------------------------------------------------------
# Feature 3: client-error intercept in proxy_request
# ---------------------------------------------------------------------------


def test_preview_session_record_has_client_errors_field():
    from datetime import UTC, datetime

    from app.gateway.preview_sessions import _PreviewSessionRecord

    now = datetime.now(UTC)
    record = _PreviewSessionRecord(
        id="test",
        user_id="u1",
        thread_id="t1",
        artifact_id="a1",
        root_path="/mnt/user-data/workspace/a1",
        command="npm run dev",
        port=3000,
        sandbox_id="sb1",
        shell_session_id="sh1",
        status="running",
        created_at=now,
        updated_at=now,
        expires_at=now,
    )
    assert record.client_errors == []


def test_preview_html_shim_contains_error_capture():
    from app.gateway.preview_sessions import _preview_html_shim

    shim = _preview_html_shim("/api/threads/t1/previews/p1/proxy")
    assert "_reportErr" in shim
    assert "__omni_preview__/client-error" in shim
    assert "unhandledrejection" in shim
    assert "console.error" in shim


@pytest.mark.asyncio
async def test_proxy_request_intercepts_client_error():
    """Client-error POST to /__omni_preview__/client-error returns 204 and stores the error."""
    from datetime import UTC, datetime
    from unittest.mock import MagicMock

    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient

    from app.gateway.preview_sessions import PreviewSessionManager, _PreviewSessionRecord

    manager = PreviewSessionManager()
    now = datetime.now(UTC)
    from datetime import timedelta

    session = _PreviewSessionRecord(
        id="prev1",
        user_id="u1",
        thread_id="t1",
        artifact_id="a1",
        root_path="/mnt/user-data/workspace/a1",
        command="npm run dev",
        port=3000,
        sandbox_id="sb1",
        shell_session_id="sh1",
        status="running",
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(minutes=15),
    )
    manager._sessions["prev1"] = session

    # Mock the sandbox lookup so the intercept path is reached before it
    sandbox_mock = MagicMock()
    sandbox_mock.fetch_local_url.return_value = {"status": 200, "headers": {}, "body": b""}

    with patch.object(manager, "_get_sandbox_for_existing_session", new=AsyncMock(return_value=sandbox_mock)):
        app = FastAPI()

        @app.post("/proxy/{path:path}")
        async def proxy(path: str, request: Request):
            return await manager.proxy_request(
                user_id="u1",
                thread_id="t1",
                preview_id="prev1",
                request=request,
                path=path,
            )

        client = TestClient(app, raise_server_exceptions=True)
        payload = json.dumps({"type": "error", "message": "ReferenceError: foo is not defined"})
        resp = client.post(
            "/proxy/__omni_preview__/client-error",
            content=payload,
            headers={"content-type": "application/json"},
        )

    assert resp.status_code == 204
    assert len(session.client_errors) == 1
    assert session.client_errors[0]["message"] == "ReferenceError: foo is not defined"


# ---------------------------------------------------------------------------
# Feature 2: PreviewVerificationMiddleware
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verification_middleware_noop_when_no_controller():
    from langchain_core.messages import AIMessage

    from omniharness.agents.middlewares.preview_verification_middleware import PreviewVerificationMiddleware

    mw = PreviewVerificationMiddleware()
    runtime = MagicMock()
    runtime.context = {"thread_id": "t1", "user_id": "u1"}

    state = {"messages": [AIMessage(content="done", tool_calls=[])]}
    result = await mw.aafter_model(state, runtime)
    assert result is None


@pytest.mark.asyncio
async def test_verification_middleware_noop_when_tool_calls():
    from langchain_core.messages import AIMessage

    from omniharness.agents.middlewares.preview_verification_middleware import PreviewVerificationMiddleware

    ctrl = _MockController(PreviewStatusSummary(has_web_app=True, session_status="not_started"))
    set_preview_controller(ctrl)

    mw = PreviewVerificationMiddleware()
    runtime = MagicMock()
    runtime.context = {"thread_id": "t1", "user_id": "u1"}

    # AI message still has tool calls — should not gate
    state = {"messages": [AIMessage(content="", tool_calls=[{"name": "bash", "id": "x", "args": {}}])]}
    result = await mw.aafter_model(state, runtime)
    assert result is None


@pytest.mark.asyncio
async def test_verification_middleware_noop_when_no_web_app():
    from langchain_core.messages import AIMessage

    from omniharness.agents.middlewares.preview_verification_middleware import PreviewVerificationMiddleware

    ctrl = _MockController(PreviewStatusSummary(has_web_app=False, session_status="not_started"))
    set_preview_controller(ctrl)

    mw = PreviewVerificationMiddleware()
    runtime = MagicMock()
    runtime.context = {"thread_id": "t1", "user_id": "u1"}

    state = {"messages": [AIMessage(content="done")]}
    result = await mw.aafter_model(state, runtime)
    assert result is None


@pytest.mark.asyncio
async def test_verification_middleware_triggers_start_when_not_started():
    from langchain_core.messages import AIMessage, HumanMessage

    from omniharness.agents.middlewares.preview_verification_middleware import PreviewVerificationMiddleware

    ctrl = _MockController(PreviewStatusSummary(has_web_app=True, session_status="not_started"))
    set_preview_controller(ctrl)

    mw = PreviewVerificationMiddleware()
    runtime = MagicMock()
    runtime.context = {"thread_id": "t1", "user_id": "u1"}

    state = {"messages": [AIMessage(content="app is ready")]}
    result = await mw.aafter_model(state, runtime)

    assert result is not None
    assert result["jump_to"] == "model"
    msgs = result["messages"]
    assert len(msgs) == 1
    assert isinstance(msgs[0], HumanMessage)
    assert msgs[0].name == "preview_verification_reminder"
    # auto-trigger was called
    assert len(ctrl.request_preview_calls) == 1


@pytest.mark.asyncio
async def test_verification_middleware_loops_on_failed():
    from langchain_core.messages import AIMessage

    from omniharness.agents.middlewares.preview_verification_middleware import PreviewVerificationMiddleware

    ctrl = _MockController(PreviewStatusSummary(has_web_app=True, session_status="failed", session_error="npm not found"))
    set_preview_controller(ctrl)

    mw = PreviewVerificationMiddleware()
    runtime = MagicMock()
    runtime.context = {"thread_id": "t1", "user_id": "u1"}

    state = {"messages": [AIMessage(content="done")]}
    result = await mw.aafter_model(state, runtime)

    assert result is not None
    assert result["jump_to"] == "model"
    assert "npm not found" in result["messages"][0].content


@pytest.mark.asyncio
async def test_verification_middleware_loops_on_client_errors():
    from langchain_core.messages import AIMessage

    from omniharness.agents.middlewares.preview_verification_middleware import PreviewVerificationMiddleware

    ctrl = _MockController(
        PreviewStatusSummary(
            has_web_app=True,
            session_status="running",
            client_errors=["Uncaught TypeError: Cannot read property 'foo'"],
        )
    )
    set_preview_controller(ctrl)

    mw = PreviewVerificationMiddleware()
    runtime = MagicMock()
    runtime.context = {"thread_id": "t1", "user_id": "u1"}

    state = {"messages": [AIMessage(content="done")]}
    result = await mw.aafter_model(state, runtime)

    assert result is not None
    assert result["jump_to"] == "model"
    assert "TypeError" in result["messages"][0].content


@pytest.mark.asyncio
async def test_verification_middleware_allows_exit_when_running_cleanly():
    from langchain_core.messages import AIMessage

    from omniharness.agents.middlewares.preview_verification_middleware import PreviewVerificationMiddleware

    ctrl = _MockController(PreviewStatusSummary(has_web_app=True, session_status="running", client_errors=[]))
    set_preview_controller(ctrl)

    mw = PreviewVerificationMiddleware()
    runtime = MagicMock()
    runtime.context = {"thread_id": "t1", "user_id": "u1"}

    state = {"messages": [AIMessage(content="done")]}
    result = await mw.aafter_model(state, runtime)
    assert result is None


@pytest.mark.asyncio
async def test_verification_middleware_caps_retries():
    from langchain_core.messages import AIMessage, HumanMessage

    from omniharness.agents.middlewares.preview_verification_middleware import PreviewVerificationMiddleware

    ctrl = _MockController(PreviewStatusSummary(has_web_app=True, session_status="not_started"))
    set_preview_controller(ctrl)

    mw = PreviewVerificationMiddleware()
    runtime = MagicMock()
    runtime.context = {"thread_id": "t1", "user_id": "u1"}

    # Stuff the messages with MAX reminders already present
    reminders = [HumanMessage(name="preview_verification_reminder", content="reminder") for _ in range(mw._MAX_VERIFICATION_REMINDERS)]
    state = {"messages": [AIMessage(content="done")] + reminders}
    result = await mw.aafter_model(state, runtime)
    assert result is None  # cap hit → allow exit


# ---------------------------------------------------------------------------
# Feature 1: GatewayPreviewController adapter
# ---------------------------------------------------------------------------


def test_gateway_controller_get_status_not_started(tmp_path):
    from unittest.mock import MagicMock, patch

    from app.gateway.preview_controller_adapter import GatewayPreviewController
    from app.gateway.preview_sessions import PreviewSessionManager

    manager = PreviewSessionManager()
    ctrl = GatewayPreviewController(manager)

    paths_mock = MagicMock()
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir()
    paths_mock.sandbox_outputs_dir.return_value = outputs_dir

    with patch("app.gateway.preview_controller_adapter.get_paths", return_value=paths_mock):
        status = asyncio.get_event_loop().run_until_complete(ctrl.get_status(thread_id="t1", user_id="u1"))

    assert status.has_web_app is False
    assert status.session_status == "not_started"


def test_gateway_controller_detects_web_app_manifest(tmp_path):
    from unittest.mock import MagicMock, patch

    from app.gateway.preview_controller_adapter import _find_first_web_app_manifest

    # Create a minimal web_app manifest
    artifact_dir = tmp_path / "my-app"
    artifact_dir.mkdir()
    manifest = {
        "id": "my-app",
        "title": "My App",
        "type": "web_app",
        "source_path": "/mnt/user-data/workspace/my-app",
        "preview": {"mode": "dev_server", "command": "npm run dev", "port": 3000},
    }
    (artifact_dir / "artifact_manifest.json").write_text(json.dumps(manifest))

    paths_mock = MagicMock()
    paths_mock.sandbox_outputs_dir.return_value = tmp_path

    with patch("app.gateway.preview_controller_adapter.get_paths", return_value=paths_mock):
        result = _find_first_web_app_manifest("t1", "u1")

    assert result is not None
    assert result["id"] == "my-app"
    assert result["preview"]["command"] == "npm run dev"


def test_gateway_controller_skips_static_site_manifest(tmp_path):
    from unittest.mock import MagicMock, patch

    from app.gateway.preview_controller_adapter import _find_first_web_app_manifest

    artifact_dir = tmp_path / "site"
    artifact_dir.mkdir()
    manifest = {
        "id": "site",
        "title": "Site",
        "type": "static_site",
        "entrypoint": "index.html",
        "root": ".",
        "preview": {"mode": "static"},
    }
    (artifact_dir / "artifact_manifest.json").write_text(json.dumps(manifest))

    paths_mock = MagicMock()
    paths_mock.sandbox_outputs_dir.return_value = tmp_path

    with patch("app.gateway.preview_controller_adapter.get_paths", return_value=paths_mock):
        result = _find_first_web_app_manifest("t1", "u1")

    assert result is None  # static_site should not trigger


# ---------------------------------------------------------------------------
# Feature 1a: RunContext.preview_controller field
# ---------------------------------------------------------------------------


def test_run_context_has_preview_controller_field():
    from omniharness.runtime.runs.worker import RunContext

    ctx = RunContext(checkpointer=None)
    assert ctx.preview_controller is None

    mock_ctrl = _MockController()
    ctx2 = RunContext(checkpointer=None, preview_controller=mock_ctrl)
    assert ctx2.preview_controller is mock_ctrl


@pytest.mark.asyncio
async def test_worker_calls_auto_start_on_success():
    """run_agent's finally block should call request_preview when run succeeds."""
    from unittest.mock import MagicMock, patch

    from omniharness.runtime.runs.manager import RunManager
    from omniharness.runtime.runs.worker import RunContext, run_agent

    ctrl = _MockController()
    # Pre-wire a user_id into the run config context
    config = {"configurable": {"thread_id": "t1"}, "context": {"user_id": "u1"}}

    bridge = MagicMock()
    bridge.publish = AsyncMock()
    bridge.publish_end = AsyncMock()
    bridge.cleanup = AsyncMock()
    bridge.subscribe = MagicMock()

    run_mgr = RunManager()
    record = await run_mgr.create("t1")

    async def fake_factory(config=None, app_config=None):
        pass

    def agent_factory(config):
        agent = MagicMock()

        async def astream_gen(*a, **kw):
            return
            yield  # make it a generator

        agent.astream = MagicMock(return_value=astream_gen())
        agent.checkpointer = None
        agent.store = None
        return agent

    ctx = RunContext(checkpointer=None, preview_controller=ctrl)

    with (
        patch("omniharness.runtime.runs.worker.Runtime"),
        patch("omniharness.runtime.runs.worker._build_runtime_context", return_value={"thread_id": "t1", "run_id": record.run_id, "user_id": "u1"}),
        patch("omniharness.runtime.runs.worker._install_runtime_context"),
        patch("langchain_core.runnables.RunnableConfig", side_effect=lambda **kw: kw),
    ):
        await run_agent(
            bridge,
            run_mgr,
            record,
            ctx=ctx,
            agent_factory=agent_factory,
            graph_input={},
            config=config,
            stream_modes=["values"],
        )

    assert len(ctrl.request_preview_calls) == 1
    assert ctrl.request_preview_calls[0]["thread_id"] == "t1"
    assert ctrl.request_preview_calls[0]["user_id"] == "u1"


# ---------------------------------------------------------------------------
# Feature 1b: preview_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_tool_calls_request_preview():
    from unittest.mock import MagicMock

    from omniharness.tools.builtins.preview_tool import preview_tool

    ctrl = _MockController(PreviewStatusSummary(has_web_app=True, session_status="starting"))
    set_preview_controller(ctrl)

    runtime = MagicMock()
    runtime.context = {"thread_id": "t1", "user_id": "u1"}

    result = await preview_tool.ainvoke({"tool_call_id": "tc1", "runtime": runtime})
    assert "starting" in str(result).lower() or "starting" in result.update.get("messages", [{}])[-1].content.lower()
    assert len(ctrl.request_preview_calls) == 1


@pytest.mark.asyncio
async def test_preview_tool_no_controller():
    from unittest.mock import MagicMock

    from omniharness.tools.builtins.preview_tool import preview_tool

    runtime = MagicMock()
    runtime.context = {"thread_id": "t1", "user_id": "u1"}

    result = await preview_tool.ainvoke({"tool_call_id": "tc1", "runtime": runtime})
    assert "not available" in str(result).lower()


# ---------------------------------------------------------------------------
# user_id threading: services.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_run_threads_user_id_into_config():
    """Ensure start_run injects user_id into config['context'] when authenticated."""
    from unittest.mock import MagicMock, patch

    from app.gateway.services import start_run

    mock_request = MagicMock()
    mock_request.app.state = MagicMock()

    body = MagicMock()
    body.on_disconnect = "cancel"
    body.assistant_id = None
    body.metadata = {}
    body.input = {"messages": []}
    body.config = None
    body.context = None
    body.stream_mode = None
    body.stream_subgraphs = False
    body.interrupt_before = None
    body.interrupt_after = None
    body.multitask_strategy = "reject"

    captured_config: dict = {}

    async def fake_run_agent(bridge, run_mgr, record, *, ctx, agent_factory, graph_input, config, **kwargs):
        captured_config.update(config)

    with (
        patch("app.gateway.services.get_stream_bridge", return_value=MagicMock()),
        patch("app.gateway.services.get_run_manager") as mock_mgr,
        patch("app.gateway.services.get_run_context", return_value=MagicMock(thread_store=MagicMock(get=AsyncMock(return_value=None), create=AsyncMock(), update_status=AsyncMock()))),
        patch("app.gateway.services.get_current_user", new=AsyncMock(return_value="user-123")),
        patch("app.gateway.services.run_agent", new=fake_run_agent),
        patch("asyncio.create_task"),
    ):
        mgr_instance = MagicMock()
        mgr_instance.create_or_reject = AsyncMock(return_value=MagicMock(run_id="r1", thread_id="t1", task=None))
        mock_mgr.return_value = mgr_instance

        try:
            await start_run(body, "t1", mock_request)
        except Exception:
            pass  # We only care about captured_config

    ctx_dict = captured_config.get("context", {})
    assert ctx_dict.get("user_id") == "user-123"
