"""Test configuration for the backend test suite.

Sets up sys.path and pre-mocks modules that would cause circular import
issues when unit-testing lightweight config/registry code in isolation.
"""

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Article XIV: the suite runs against the tracked config.example.yaml, never a
# developer's gitignored config.yaml. A fresh clone has no config.yaml, and a
# developer's one makes the suite's result depend on their local settings.
# An explicit OMNI_HARNESS_CONFIG_PATH still wins. Tests never call a model
# provider, but the example interpolates $OPENAI_API_KEY eagerly, so a fresh
# clone needs a placeholder for config loading to succeed.
os.environ.setdefault("OMNI_HARNESS_CONFIG_PATH", str(Path(__file__).resolve().parents[2] / "config.example.yaml"))
os.environ.setdefault("OPENAI_API_KEY", "placeholder-not-a-real-key")
# TestClient sends Host: testserver; the gateway answers only allowlisted
# hosts (app.gateway.config.HostGuardMiddleware), so tests allow that name.
os.environ.setdefault("GATEWAY_ALLOWED_HOSTS", "testserver")
# The session-watcher's token is REQUIRED; tests share one throwaway token file
# (read by the watcher and sent by the gateway's MCP client), never the user's.
if not os.environ.get("OMNI_HARNESS_WATCHER_TOKEN_FILE"):
    import tempfile as _tempfile

    _token_dir = _tempfile.mkdtemp(prefix="omni-test-watcher-")
    with open(os.path.join(_token_dir, "watcher.token"), "w", encoding="utf-8") as _fh:
        _fh.write("test-watcher-token\n")
    os.environ["OMNI_HARNESS_WATCHER_TOKEN_FILE"] = os.path.join(_token_dir, "watcher.token")

# Make 'app' and 'omniharness' importable from any working directory
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

# Break the circular import chain that exists in production code:
#   omniharness.subagents.__init__
#     -> .executor (SubagentExecutor, SubagentResult)
#       -> omniharness.agents.thread_state
#         -> omniharness.agents.__init__
#           -> lead_agent.agent
#             -> subagent_limit_middleware
#               -> omniharness.subagents.executor  <-- circular!
#
# By injecting a mock for omniharness.subagents.executor *before* any test module
# triggers the import, __init__.py's "from .executor import ..." succeeds
# immediately without running the real executor module.
_executor_mock = MagicMock()
_executor_mock.SubagentExecutor = MagicMock
_executor_mock.SubagentResult = MagicMock
_executor_mock.SubagentStatus = MagicMock
_executor_mock.MAX_CONCURRENT_SUBAGENTS = 3
_executor_mock.get_background_task_result = MagicMock()

sys.modules["omniharness.subagents.executor"] = _executor_mock


@pytest.fixture()
def provisioner_module():
    """Load docker/provisioner/app.py as an importable test module.

    Shared by test_provisioner_kubeconfig and test_provisioner_pvc_volumes so
    that any change to the provisioner entry-point path or module name only
    needs to be updated in one place.
    """
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "docker" / "provisioner" / "app.py"
    spec = importlib.util.spec_from_file_location("provisioner_app_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Auto-set user context for every test unless marked no_auto_user
# ---------------------------------------------------------------------------
#
# Repository methods read ``user_id`` from a contextvar by default
# (see ``omniharness.runtime.user_context``). Without this fixture, every
# pre-existing persistence test would raise RuntimeError because the
# contextvar is unset. The fixture sets a default test user on every
# test; tests that explicitly want to verify behaviour *without* a user
# context should mark themselves ``@pytest.mark.no_auto_user``.


@pytest.fixture(autouse=True)
def _restore_policy_builder():
    """Keep the policy-builder registration from leaking between tests.

    `policy_hook._builder` is process-global, and anything that runs the
    gateway lifespan or `app.policy.registration.install()` sets it. Leaked,
    the next test's agents get a real policy gate or a refusing one depending
    on which tests ran first — a result inherited from ambient state (Article
    XIV). Found when a test passed alone and failed in the full run.
    """
    from omniharness.agents.middlewares import policy_hook

    saved = policy_hook._builder
    yield
    policy_hook._builder = saved


@pytest.fixture(autouse=True)
def _restore_memory_config():
    """Keep the memory configuration from leaking between tests.

    `memory_config._memory_config` is process-global, and every app-config
    load replaces it (`load_memory_config_from_dict`). A test whose config
    turns memory off left it off, and a later memory-queue or updater test in
    the same process found every `add()` a no-op. Which tests share a process
    differs between a serial and a parallel run, so this failed only under
    `make test` (pytest-xdist), and only on some workers.
    """
    from omniharness.config import memory_config

    saved = memory_config._memory_config
    yield
    memory_config._memory_config = saved


@pytest.fixture(autouse=True)
def _restore_title_and_summarization_config():
    """The same leak as memory's above, for the title and summarization
    sections: many create_app() tests load a config with them turned off,
    and a later title test in the same worker found titles disabled."""
    from omniharness.config import summarization_config, title_config

    saved = (title_config._title_config, summarization_config._summarization_config)
    yield
    title_config._title_config, summarization_config._summarization_config = saved


@pytest.fixture(autouse=True)
def _reset_skill_storage_singleton():
    """Reset the SkillStorage singleton between tests to prevent cross-test contamination."""
    try:
        from omniharness.skills.storage import reset_skill_storage
    except ImportError:
        yield
        return
    reset_skill_storage()
    try:
        yield
    finally:
        reset_skill_storage()


@pytest.fixture(autouse=True)
def _auto_user_context(request):
    """Inject a default ``test-user-autouse`` into the contextvar.

    Opt-out via ``@pytest.mark.no_auto_user``. Uses lazy import so that
    tests which don't touch the persistence layer never pay the cost
    of importing runtime.user_context.
    """
    if request.node.get_closest_marker("no_auto_user"):
        yield
        return

    try:
        from omniharness.runtime.user_context import (
            reset_current_user,
            set_current_user,
        )
    except ImportError:
        yield
        return

    user = SimpleNamespace(id="test-user-autouse", email="test@local")
    token = set_current_user(user)
    try:
        yield
    finally:
        reset_current_user(token)


@pytest.fixture(autouse=True)
def _enable_workflows_feature_flag(request, monkeypatch):
    """Turn the Workflows feature flag on for the workflow test modules.

    ``workflows.enabled`` defaults to False and is False in config.example.yaml,
    so these tests only ever passed against a developer's local config that had
    opted in. Without this the routers answer 404 and every assertion reads as a
    routing bug rather than a disabled feature.
    """
    if "workflow" not in request.node.nodeid:
        return

    from app.gateway.routers import workflows as _workflows_router

    real = _workflows_router.get_app_config

    def _enabled_config():
        config = real()
        if not config.workflows.enabled:
            config = config.model_copy(update={"workflows": config.workflows.model_copy(update={"enabled": True})})
        return config

    monkeypatch.setattr(_workflows_router, "get_app_config", _enabled_config)


@pytest.fixture(autouse=True)
def _run_store_key_outside_home(tmp_path_factory, monkeypatch):
    """The run history's key file (app/run_history/crypto.py) lives in a fresh
    temp dir per test: no test reads or writes ~/.omni-harness-secrets."""
    keydir = tmp_path_factory.mktemp("run-store-key")
    monkeypatch.setenv("OMNI_HARNESS_RUN_STORE_KEY_FILE", str(keydir / "run_store.key"))


# -- a hung test fails instead of holding the job ----------------------------
#
# pytest-timeout is not a dependency. A test that hangs (a run that never
# ends, a request into a stuck event loop) used to hold the CI job until its
# 40-minute limit, with no test named. Past this limit the test gets an
# exception in its main thread (SIGALRM), after every thread's stack is
# written to stderr, so it FAILS by name and the run carries on. If even that
# cannot interrupt it, the worker dumps the stacks and exits a minute later
# (xdist reports it as crashed). No test needs anywhere near this long;
# OMNI_TEST_HARD_TIMEOUT moves it (0 turns it off).
_HARD_TIMEOUT = float(os.environ.get("OMNI_TEST_HARD_TIMEOUT") or 300)


class HardTestTimeout(BaseException):
    """Raised in a test that ran past OMNI_TEST_HARD_TIMEOUT."""


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    import faulthandler
    import signal
    import threading

    armed = _HARD_TIMEOUT > 0 and hasattr(signal, "SIGALRM") and threading.current_thread() is threading.main_thread()
    previous = None
    if armed:

        def _expired(signum, frame):
            faulthandler.dump_traceback(all_threads=True)
            raise HardTestTimeout(f"{item.nodeid} ran past {_HARD_TIMEOUT:.0f} s (OMNI_TEST_HARD_TIMEOUT)")

        previous = signal.signal(signal.SIGALRM, _expired)
        signal.setitimer(signal.ITIMER_REAL, _HARD_TIMEOUT)
        faulthandler.dump_traceback_later(_HARD_TIMEOUT + 60, exit=True)
    try:
        yield
    finally:
        if armed:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
            faulthandler.cancel_dump_traceback_later()
