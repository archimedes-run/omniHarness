"""One eval trial: a fresh, isolated gateway, one task, its checks (spec 009 FR-072).

Each trial starts a NEW gateway through `create_app()` and its lifespan, with:
  * a temporary data directory and a temporary HOME (run-history keys, the
    session watcher's token and any CLI auth folders are empty and thrown away);
  * a config built from the tracked config.example.yaml plus the tracked
    overrides in fixtures/overrides.yaml: no channels, no connectors, no MCP
    servers, no trigger engine, no memory, no titles; the policy layer ON with
    the SHIPPED rules (so cards and tiers are the real ones);
  * fixture tools under their real names (stubs.py) and, in mock mode, the
    scripted model (scripted.py) and recorded web results;
  * a throwaway owner account the harness creates, and fixtures loaded through
    the public API.
Nothing reads or writes the owner's data dir, `.env` (real mode reads the
model key from a file the caller names, into this process only, never
printing it), `config.yaml` or real accounts.

Mock mode runs the gateway in this process (TestClient, no port). Real mode
runs it as a separate uvicorn process on a free localhost port, so the run is
a production-shaped request path and nothing is shared with the caller.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import scripted, stubs
from .checks import Outcome, run_checks

EVAL_DIR = Path(__file__).resolve().parent.parent
BACKEND = EVAL_DIR.parents[1]
REPO = BACKEND.parent
TASKS_DIR = EVAL_DIR / "tasks"
FIXTURES = EVAL_DIR / "fixtures"
OWNER = {"email": "eval-owner@example.com", "password": "Eval-Owner-Pass-9x!"}

MODES = {
    "flash": {"thinking_enabled": False, "is_plan_mode": False, "subagent_enabled": False},
    "thinking": {"thinking_enabled": True, "is_plan_mode": False, "subagent_enabled": False, "reasoning_effort": "low"},
    "pro": {"thinking_enabled": True, "is_plan_mode": True, "subagent_enabled": False, "reasoning_effort": "medium"},
    "ultra": {"thinking_enabled": True, "is_plan_mode": True, "subagent_enabled": True, "reasoning_effort": "high"},
}

STUB_TOOLS = [
    {"name": "googlecalendar_list-events", "group": "eval", "use": "omni_eval.stubs:calendar_list_events"},
    {"name": "gmail_search_emails", "group": "eval", "use": "omni_eval.stubs:gmail_search_emails"},
    {"name": "gmail_read_email", "group": "eval", "use": "omni_eval.stubs:gmail_read_email"},
    {"name": "gmail_draft_email", "group": "eval", "use": "omni_eval.stubs:gmail_draft_email"},
]
MOCK_WEB = [
    {"name": "web_search", "group": "web", "use": "omni_eval.stubs:web_search"},
    {"name": "web_fetch", "group": "web", "use": "omni_eval.stubs:web_fetch"},
    {"name": "image_search", "group": "web", "use": "omni_eval.stubs:image_search"},
]


#: Wall-clock limit per task (owner rule, 2026-11-13): 300 s unless the task's
#: `budget.seconds` says otherwise, never more than 600 s, enforced by the
#: harness whatever the gateway does.
DEFAULT_TASK_SECONDS = 300
MAX_TASK_SECONDS = 600
#: A run with no new journal event for this long is stalled and stopped.
#: Not 60: one high-effort model call on a long context can pass a minute.
STALL_SECONDS = 120
#: ... except while a delegation or coding job it started is still out: the
#: lead writes nothing until its result returns (the research subagent's own
#: limit is 240 s). The wall clock still bounds it.
LONG_TOOL_STALL_SECONDS = 300
LONG_TOOLS = frozenset({"task", "research", "code_job"})
ACTIVE = ("pending", "running")

#: The provider SDK's default key variable, by the model class's package. A
#: key named in the model's config (`$VAR`) is passed too; nothing else is.
PROVIDER_KEYS = {
    "langchain_openai": ("OPENAI_API_KEY",),
    "langchain_anthropic": ("ANTHROPIC_API_KEY",),
    "langchain_google_genai": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "langchain_deepseek": ("DEEPSEEK_API_KEY",),
}
#: Endpoint settings, not secrets: passed when the env file has them.
ENDPOINT_VARS = frozenset({"OPENAI_BASE_URL", "OPENAI_API_BASE", "ANTHROPIC_BASE_URL"})
#: The only variables of the caller's environment a real-mode trial gateway
#: inherits (an allowlist: anything else, secret or not, stays out).
ENV_ALLOW = frozenset(
    {
        "PATH", "LANG", "LANGUAGE", "TZ", "TMPDIR", "TERM", "USER", "LOGNAME", "SHELL",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
        "VIRTUAL_ENV", "PYTHONHASHSEED", "PYTHONDONTWRITEBYTECODE", "DOCKER_HOST",
    }
)  # fmt: skip


def task_seconds(task: dict) -> float:
    """The task's wall-clock limit: budget.seconds (default 300), capped at 600."""
    budget = (task.get("budget") or {}).get("seconds")
    return float(min(float(budget) if budget else DEFAULT_TASK_SECONDS, MAX_TASK_SECONDS))


def needed_keys(models: list[dict] | None, tools: list[dict] | None) -> set[str]:
    """The secrets a real-mode trial needs: its model's key (the SDK default
    for the model class, and any `$VAR` its config names), and JINA_API_KEY
    only when a web_fetch tool explicitly selects that reader."""
    names: set[str] = set()
    for model in models or []:
        use = str(model.get("use") or "")
        names.update(PROVIDER_KEYS.get(use.split(":", 1)[0].split(".", 1)[0], ()))
        names.update(re.findall(r"\$([A-Z][A-Z0-9_]*)", json.dumps(model)))
    for tool in tools or []:
        if tool.get("name") == "web_fetch" and str(tool.get("provider") or "") == "jina":
            names.add("JINA_API_KEY")
    return names


def trial_process_env(parent: dict[str, str], env_file: dict[str, str], needed: set[str]) -> tuple[dict[str, str], list[str]]:
    """The real-mode gateway's environment: from the caller's, only the
    allowlisted variables (ENV_ALLOW, LC_*) and the needed keys; from the env
    file, only the needed keys (and endpoint settings). Returns the env and
    the NAMES of the secrets passed (never their values)."""
    env = {k: v for k, v in parent.items() if k in ENV_ALLOW or k.startswith("LC_") or k in needed}
    for key, value in env_file.items():
        if key in needed or key in ENDPOINT_VARS:
            env[key] = value
    passed = sorted(k for k in env if k in needed)
    return env, passed


def load_tasks(selected: list[str] | None = None) -> list[dict]:
    tasks = []
    for path in sorted(TASKS_DIR.glob("*.yaml")):
        task = yaml.safe_load(path.read_text())
        task["_file"] = path.name
        tasks.append(task)
    if selected:
        wanted = {s.strip().upper() for s in selected if s.strip()}
        tasks = [t for t in tasks if str(t["id"]).upper() in wanted]
    return tasks


def build_config(root: Path, task: dict, mode: str, *, model_config: list[dict] | None = None) -> Path:
    """The trial's config.yaml, from the tracked example and overrides."""
    config = yaml.safe_load((REPO / "config.example.yaml").read_text())
    overrides = yaml.safe_load((FIXTURES / "overrides.yaml").read_text())
    for key, value in overrides.items():
        config[key] = value
    config["database"] = {"backend": "sqlite", "sqlite_dir": str(root / "data")}
    config["policy"] = {"enabled": True, "state_dir": str(root / "policy")}
    tools = [t for t in config["tools"] if t["name"] not in ("web_search", "web_fetch", "image_search")] if mode == "mock" else list(config["tools"])
    if mode == "real":
        # The page reader is the built-in fetcher through the fetch egress
        # proxy (fetch_egress.py), as on the live stack; never a fallback
        # reader the env happens to have a key for.
        tools = [{**t, "jina_fallback": False} if t.get("name") == "web_fetch" and str(t.get("provider") or "builtin") == "builtin" else t for t in tools]
    if mode == "mock":
        tools = MOCK_WEB + tools
        config["models"] = [{"name": "default", "display_name": "Scripted", "use": "omni_eval.scripted:ScriptedChatModel", "model": "scripted", "supports_thinking": True, "supports_reasoning_effort": True, "supports_vision": False}]
    elif model_config:
        config["models"] = model_config
    present = set(task.get("tools") or ["calendar", "mail"])
    stubs_wanted = [t for t in STUB_TOOLS if ("calendar" in present and "calendar" in t["name"]) or ("mail" in present and "gmail" in t["name"])]
    config["tools"] = tools + stubs_wanted
    groups = {g["name"] for g in config.get("tool_groups") or []}
    for group in ("eval", "web"):
        if group not in groups:
            config.setdefault("tool_groups", []).append({"name": group})
    # Forced summarisation is a mock-mode device (M-SUMMARY, T07's CI run); a
    # real-model trial keeps the shipped threshold.
    summarization = (task.get("fixtures") or {}).get("summarization_tokens") if mode == "mock" else None
    if summarization:
        config["summarization"]["enabled"] = True
        config["summarization"]["trigger"] = [{"type": "tokens", "value": int(summarization)}]
        config["summarization"]["keep"] = {"type": "messages", "value": 4}
    path = root / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    return path


@dataclass
class Trial:
    task: dict
    mode: str  # "mock" | "real"
    root: Path
    client: Any = None
    env: dict = field(default_factory=dict)
    proc: Any = None
    base_url: str | None = None
    passed_keys: list[str] = field(default_factory=list)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def trial_env(root: Path, config_path: Path) -> dict[str, str]:
    home = root / "home"
    home.mkdir(parents=True, exist_ok=True)
    (root / "watcher").mkdir(exist_ok=True)
    token = root / "watcher" / "watcher.token"
    token.write_text("eval-watcher-token\n")
    extensions = root / "extensions.json"
    extensions.write_text('{"mcpServers": {}, "skills": {}}')
    return {
        "HOME": str(home),
        "OMNI_HARNESS_HOME": str(root / "omni-home"),
        "OMNI_HARNESS_CONFIG_PATH": str(config_path),
        "OMNI_HARNESS_EXTENSIONS_CONFIG_PATH": str(extensions),
        "OMNI_HARNESS_WATCHER_TOKEN_FILE": str(token),
        "AUTH_JWT_SECRET": secrets.token_hex(32),
        "GATEWAY_ALLOWED_HOSTS": "testserver,127.0.0.1,localhost",
    }


@contextlib.contextmanager
def _patched_environ(values: dict[str, str]) -> Iterator[None]:
    """The trial's variables set, and every OMNI_HARNESS_* variable of the
    caller that the trial does not set removed (a caller's data dir, proxy or
    config must not reach the in-process gateway); all restored after."""
    dropped = [k for k in os.environ if k.startswith("OMNI_HARNESS_") and k not in values]
    old = {k: os.environ.get(k) for k in [*values, *dropped]}
    for key in dropped:
        os.environ.pop(key, None)
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _wire_real_executor() -> None:
    """Under pytest, tests/conftest.py replaces the subagent executor with a
    MagicMock for the session (an import cycle); the eval needs the real one."""
    import importlib
    from unittest.mock import MagicMock

    module = sys.modules.get("omniharness.subagents.executor")
    if module is not None and not isinstance(module, MagicMock) and not isinstance(getattr(module, "SubagentExecutor", None), type(MagicMock)):
        return
    sys.modules.pop("omniharness.subagents.executor", None)
    executor_module = importlib.import_module("omniharness.subagents.executor")
    task_tool_module = importlib.import_module("omniharness.tools.builtins.task_tool")
    for name in ("SubagentExecutor", "SubagentStatus", "get_background_task_result", "cleanup_background_task", "request_cancel_background_task"):
        setattr(task_tool_module, name, getattr(executor_module, name))
    import omniharness.subagents as subagents_package

    subagents_package.SubagentExecutor = executor_module.SubagentExecutor


@contextlib.contextmanager
def gateway(task: dict, mode: str, *, model_config: list[dict] | None = None, env_extra: dict | None = None, keep: Path | None = None, fetch_proxy: str | None = None) -> Iterator[Trial]:
    root = Path(tempfile.mkdtemp(prefix=f"omni-eval-{task['id']}-"))
    config_path = build_config(root, task, mode, model_config=model_config)
    env = trial_env(root, config_path)
    if fetch_proxy:
        env["OMNI_HARNESS_FETCH_EGRESS_PROXY"] = fetch_proxy
    trial = Trial(task=task, mode=mode, root=root, env=env)
    try:
        if mode == "mock":
            yield from _in_process(trial)
        else:
            yield from _subprocess(trial, env_extra or {})
    finally:
        if keep is not None:
            keep.mkdir(parents=True, exist_ok=True)
            target = keep / root.name
            shutil.copytree(root, target, dirs_exist_ok=True)
        shutil.rmtree(root, ignore_errors=True)


def _in_process(trial: Trial):
    from fastapi.testclient import TestClient

    cwd = os.getcwd()
    with _patched_environ(trial.env):
        os.chdir(trial.root)
        import app.gateway.deps as deps
        from app.gateway.auth.config import AuthConfig, set_auth_config
        from omniharness.config.app_config import reset_app_config
        from omniharness.config.extensions_config import reset_extensions_config

        reset_app_config()
        reset_extensions_config()
        set_auth_config(AuthConfig(jwt_secret=trial.env["AUTH_JWT_SECRET"]))
        _wire_real_executor()
        for attr in ("_cached_local_provider", "_cached_repo"):
            if hasattr(deps, attr):
                setattr(deps, attr, None)
        from app.gateway.app import create_app

        try:
            with TestClient(create_app()) as client:
                trial.client = client
                _login(client, first=True)
                yield trial
        finally:
            os.chdir(cwd)
            reset_app_config()
            reset_extensions_config()


def load_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines, read into memory for the gateway process only. Values
    are never printed or written anywhere."""
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        out[key] = value
    return out


def _subprocess(trial: Trial, env_extra: dict):
    import httpx

    port = _free_port()
    config = yaml.safe_load(Path(trial.env["OMNI_HARNESS_CONFIG_PATH"]).read_text())
    env, trial.passed_keys = trial_process_env(dict(os.environ), env_extra, needed_keys(config.get("models"), config.get("tools")))
    env.update(trial.env)
    # This checkout's code, ahead of whatever an editable install in the venv
    # points at (another checkout's packages would be scored instead).
    env["PYTHONPATH"] = os.pathsep.join([str(BACKEND), str(BACKEND / "packages" / "harness"), str(BACKEND / "packages" / "session_watcher"), str(EVAL_DIR)])
    log = open(trial.root / "gateway.log", "w")  # noqa: SIM115 - closed below
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.gateway.app:app", "--host", "127.0.0.1", "--port", str(port)], cwd=str(trial.root), env=env, stdout=log, stderr=subprocess.STDOUT)
    trial.proc = proc
    trial.base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 90
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"the eval gateway exited at startup (see {trial.root / 'gateway.log'})")
            try:
                if httpx.get(f"{trial.base_url}/health", timeout=2).status_code < 500:
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        else:
            raise RuntimeError("the eval gateway did not start within 90 s")
        # Runs are started in the background and watched (run_trial), so no
        # request waits long; a gateway that stops answering fails the trial.
        with httpx.Client(base_url=trial.base_url, timeout=60) as client:
            trial.client = client
            _login(client, first=True)
            yield trial
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


def _login(client: Any, *, first: bool) -> None:
    resp = client.post("/api/v1/auth/initialize", json=OWNER) if first else None
    if resp is None or resp.status_code not in (200, 201):
        resp = client.post("/api/v1/auth/login/local", data={"username": OWNER["email"], "password": OWNER["password"]})
        resp.raise_for_status()
    csrf = client.cookies.get("csrf_token")
    if csrf:
        client.headers["X-CSRF-Token"] = csrf


# ---------------------------------------------------------------- the trial


def _seed(client: Any, fixtures: dict) -> None:
    for project in fixtures.get("ledger") or []:
        resp = client.post("/api/ledger/projects", json={"name": project["name"], "why": project.get("why", "")})
        resp.raise_for_status()
        body = resp.json()
        pid = body.get("id") or (body.get("project") or {}).get("id")
        for title in project.get("tasks") or []:
            client.post(f"/api/ledger/projects/{pid}/tasks", json={"title": title}).raise_for_status()


def _project(client: Any, name: str) -> dict | None:
    for project in client.get("/api/ledger/projects").json():
        if str(project.get("name", "")).lower() == name.lower():
            return client.get(f"/api/ledger/projects/{project['id']}").json()
    return None


class Stop(Exception):
    """The trial is stopped: timeout, stall or a pause nobody will answer."""


def _activity(client: Any, thread_id: str, runs: list[dict]) -> tuple[int, bool]:
    """(journal events so far over the active runs, whether a delegation or
    coding job the lead started is still out)."""
    count = 0
    outstanding = False
    for run in runs:
        resp = client.get(f"/api/threads/{thread_id}/runs/{run['run_id']}/events", params={"limit": 2000})
        events = resp.json() if resp.status_code == 200 else []
        count += len(events)
        started: set[str] = set()
        finished: set[str] = set()
        for event in events:
            content = event.get("content") if isinstance(event.get("content"), dict) else {}
            if event.get("event_type") == "llm.ai.response":
                started.update(str(c.get("id")) for c in content.get("tool_calls") or [] if c.get("name") in LONG_TOOLS)
            elif event.get("event_type") == "llm.tool.result":
                finished.add(str(content.get("tool_call_id")))
        outstanding = outstanding or bool(started - finished)
    return count, outstanding


def _cancel_active(client: Any, thread_id: str) -> None:
    with contextlib.suppress(Exception):
        for run in client.get(f"/api/threads/{thread_id}/runs").json():
            if run.get("status") in ACTIVE:
                client.post(f"/api/threads/{thread_id}/runs/{run['run_id']}/cancel", params={"action": "interrupt"})


def _watch(client: Any, thread_id: str, deadline: float, *, stall: float | None = None) -> None:
    """Wait until no run of the thread is active (resume runs included).

    Raises Stop on the task's wall clock ("timeout") or when the active runs
    write no journal event for `stall` seconds ("stalled"); the active runs are
    cancelled first. Never waits past the deadline, whatever the gateway does."""
    stall = float(os.environ.get("EVAL_STALL_SECONDS") or STALL_SECONDS) if stall is None else stall
    last_count = -1
    last_change = time.time()
    time.sleep(0.2)
    while True:
        now = time.time()
        if now >= deadline:
            _cancel_active(client, thread_id)
            raise Stop("timeout: the task's wall-clock limit was reached")
        runs = [r for r in client.get(f"/api/threads/{thread_id}/runs").json() if r.get("status") in ACTIVE]
        if not runs:
            return
        count, outstanding = _activity(client, thread_id, runs)
        if count != last_count:
            last_count, last_change = count, now
        limit = max(stall, LONG_TOOL_STALL_SECONDS) if outstanding else stall
        if now - last_change > limit:
            _cancel_active(client, thread_id)
            raise Stop(f"stalled: no activity for {int(limit)} s")
        time.sleep(0.5)


def _paused(client: Any, thread_id: str, task: dict, seen: dict[str, dict]) -> str | None:
    """Why the thread is waiting on the person, if it is and nobody will
    answer: a question (ask_clarification), or a card the task's confirm
    policy does not answer (a task whose checks expect a card is not paused,
    it is done)."""
    values = client.get(f"/api/threads/{thread_id}/state").json()
    messages = (values.get("values", values) or {}).get("messages") or []
    last = messages[-1] if messages else {}
    if isinstance(last, dict) and last.get("type") == "tool" and last.get("name") == "ask_clarification":
        return "paused: waiting on clarification"
    expects_card = any((next(iter(c)) if isinstance(c, dict) else c) in ("card_raised", "open_card") for c in task.get("checks") or [])
    cards = _open_cards(client, thread_id)
    if cards and not expects_card and task.get("confirm", "none") in (None, "none"):
        return f"paused: waiting on a card ({', '.join(sorted({c.get('tool_name') or '?' for c in cards}))})"
    return None


def _open_cards(client: Any, thread_id: str) -> list[dict]:
    body = client.get("/api/confirmations").json()
    return [a for a in body.get("actions") or [] if a.get("thread_id") == thread_id]


def _answer_cards(client: Any, thread_id: str, policy: str, seen: dict[str, dict], deadline: float) -> None:
    """Apply the task's confirm policy until no card it covers is open (each
    round bounded). Only ever inside the isolated gateway."""
    if policy in (None, "none"):
        for card in _open_cards(client, thread_id):
            seen.setdefault(card["id"], {**card, "answered": None})
        return
    for _round in range(6):
        cards = _open_cards(client, thread_id)
        for card in cards:
            seen.setdefault(card["id"], {**card, "answered": None})
        if not cards:
            return
        if policy == "apply-all":
            outbound = [c["id"] for c in cards if c["tool_name"] in ("web_search", "web_fetch", "image_search", "research")]
            if outbound:
                client.post("/api/confirmations/apply-all", json={"ids": outbound})
                for i in outbound:
                    seen[i]["answered"] = "apply-all"
            rest = [c for c in cards if c["id"] not in outbound]
            for card in rest:
                _confirm(client, card)
                seen[card["id"]]["answered"] = "confirm"
        elif policy == "confirm-all":
            for card in cards:
                _confirm(client, card)
                seen[card["id"]]["answered"] = "confirm"
        elif policy.startswith("decline:"):
            tool = policy.split(":", 1)[1]
            handled = False
            for card in cards:
                if card["tool_name"] == tool:
                    client.post(f"/api/confirmations/{card['id']}/decline", json={})
                    seen[card["id"]]["answered"] = "decline"
                    handled = True
                else:
                    _confirm(client, card)
                    seen[card["id"]]["answered"] = "confirm"
            if not handled and not cards:
                return
        _watch(client, thread_id, deadline)


def _confirm(client: Any, card: dict) -> None:
    body: dict = {}
    if card.get("requires_typed_count"):
        body["typed_count"] = len(card.get("targets") or [])
    client.post(f"/api/confirmations/{card['id']}/confirm", json=body)


def run_trial(task: dict, mode: str, **gateway_kwargs: Any) -> dict:
    """Run one task in a fresh gateway; returns its result record."""
    started = time.time()
    stubs.reset()
    if mode == "mock":
        scripted.SCRIPT.load(task.get("mock"))
    limit = task_seconds(task) if (task.get("budget") or {}).get("seconds") or mode == "real" else 60.0
    deadline = started + limit
    with gateway(task, mode, **gateway_kwargs) as trial:
        client = trial.client
        _seed(client, task.get("fixtures") or {})
        thread_id = client.post("/api/threads", json={}).json()["thread_id"]
        context = {**MODES[task.get("mode", "pro")], "thread_id": thread_id}
        turns = task["prompt"] if isinstance(task["prompt"], list) else [task["prompt"]]
        seen: dict[str, dict] = {}
        error = None
        stopped = None
        for text in turns:
            body = {"assistant_id": "lead_agent", "input": {"messages": [{"type": "human", "content": [{"type": "text", "text": text}]}]}, "config": {"recursion_limit": 200}, "context": context}
            try:
                # Started in the background and watched, never waited on:
                # a run that pauses, stalls or overruns stops the trial.
                resp = client.post(f"/api/threads/{thread_id}/runs", json=body)
                if resp.status_code != 200:
                    error = f"run failed: HTTP {resp.status_code}: {resp.text[:200]}"
                    break
                _watch(client, thread_id, deadline)
                _answer_cards(client, thread_id, task.get("confirm", "none"), seen, deadline)
                _watch(client, thread_id, deadline)
                stopped = _paused(client, thread_id, task, seen)
            except Stop as stop:
                stopped = str(stop)
            except Exception as exc:  # noqa: BLE001
                error = f"run failed: {type(exc).__name__}: {exc}"[:300]
            if stopped or error:
                break
        time.sleep(0.3)  # the last trace write is fire-and-forget
        state = client.get(f"/api/threads/{thread_id}/state").json()
        values = state.get("values", state) or {}
        open_cards = _open_cards(client, thread_id)
        for card in open_cards:
            seen.setdefault(card["id"], {**card, "answered": None})
        traces = []
        for _attempt in range(10):
            listing = client.get("/api/run-history/runs", params={"kind": "chat", "thread_id": thread_id, "limit": 50})
            if listing.status_code == 200 and listing.json():
                traces = []
                for summary in listing.json():
                    detail = client.get(f"/api/run-history/runs/{summary['id']}").json()
                    trace = (detail.get("body") or {}).get("trace")
                    if isinstance(trace, dict):
                        traces.append(trace)
                break
            time.sleep(0.3)
        outputs = (values.get("thread_data") or {}).get("outputs_path")
        outcome = Outcome(
            task=task,
            messages=values.get("messages") or [],
            todos=values.get("todos") or [],
            artifacts=values.get("artifacts") or [],
            verifications=values.get("verifications") or {},
            open_cards=open_cards,
            cards_seen=list(seen.values()),
            traces=traces,
            outputs_dir=Path(outputs) if outputs else None,
            ledger=lambda name: _project(client, name),
            divergence=scripted.SCRIPT.divergence if mode == "mock" else None,
        )
        specs = _resolve_answer(task, mode)
        checks = run_checks(outcome, specs, mode=mode)
        if error and not any(c["name"] == "run_ok" for c in checks):
            checks.append({"name": "run_ok", "pass": False, "reason": error, "strict": False})
        if stopped and not (stopped.startswith("paused") and task.get("allow_pause")):
            reason = stopped + (f" after {int(limit)} s" if stopped.startswith("timeout") else "")
            checks.append({"name": "run_ok", "pass": False, "reason": reason, "strict": False})
        tokens, cost, cost_source = trial_cost(client, thread_id, traces, mode=mode, model_config=gateway_kwargs.get("model_config"))
        core = [c for c in checks if not c["strict"]]
        return {
            "id": task["id"],
            "title": task.get("title", ""),
            "pass": all(c["pass"] for c in checks),
            "core_pass": all(c["pass"] for c in core),
            "live_only": bool(task.get("live_only")),
            "checks": checks,
            "seconds": round(time.time() - started, 1),
            "tokens": tokens,
            "cost_usd": cost,
            "cost_source": cost_source,
            "stopped": stopped,
            "keys_passed": trial.passed_keys,
            "thread_id": thread_id,
            "final": outcome.final[:4000],
            "tools": outcome.names,
            "cards": [{"tool": c.get("tool_name"), "answered": c.get("answered")} for c in seen.values()],
            "verification": outcome.final_verification,
            "trace_count": len(traces),
        }


def trial_cost(client: Any, thread_id: str, traces: list[dict], *, mode: str, model_config: list[dict] | None) -> tuple[dict, float | None, str | None]:
    """(tokens, cost in USD, where the cost came from) for one trial.

    1. The run traces (each run's tokens by model at list price): exact per
       model, and what the trace view shows.
    2. Otherwise (a trace missing, or a model the price table cannot name):
       the thread's run totals (/token-usage, written by the run journal) at
       the configured model's list price, labelled as such.
    None only when no tokens were counted at all, or the model has no price."""
    from app.run_history.chat_trace import price_of

    tokens = {"input": sum((t.get("tokens") or {}).get("input", 0) for t in traces), "output": sum((t.get("tokens") or {}).get("output", 0) for t in traces)}
    costs = [t.get("cost_usd") for t in traces]
    if traces and all(c is not None for c in costs):
        return tokens, round(sum(costs), 6), "trace"
    if mode == "mock":
        return tokens, 0.0, "scripted"
    usage = {}
    with contextlib.suppress(Exception):
        usage = client.get(f"/api/threads/{thread_id}/token-usage").json()
    total_in, total_out = int(usage.get("total_input_tokens") or 0), int(usage.get("total_output_tokens") or 0)
    if total_in or total_out:
        tokens = {"input": max(tokens["input"], total_in), "output": max(tokens["output"], total_out)}
    model = str(((model_config or [{}])[0] or {}).get("model") or "")
    price = price_of(model)
    if price is None or not (tokens["input"] or tokens["output"]):
        return tokens, None, None
    # No cached-token split in the run totals: priced as uncached (an upper bound).
    return tokens, round((tokens["input"] * price[0] + tokens["output"] * price[2]) / 1e6, 6), f"run totals at {model} list price"


def _resolve_answer(task: dict, mode: str) -> list:
    """Checks with "{answer}" replaced by the task's `answer_from_url` value:
    the recorded one in mock mode, read live (a public JSON API) in real mode."""
    spec = task.get("answer_from_url")
    checks = task.get("checks") or []
    if not spec:
        return checks
    value = spec.get("mock")
    if mode == "real":
        import httpx

        try:
            data = httpx.get(spec["url"], timeout=30).json()
            for key in spec.get("path") or []:
                data = data[key]
            value = str(data)
        except Exception:  # noqa: BLE001
            value = spec.get("mock")
    return json.loads(json.dumps(checks).replace("{answer}", str(value)))


def dump(result: dict) -> str:
    return json.dumps(result, indent=1, default=str)
