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
    old = {k: os.environ.get(k) for k in values}
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
def gateway(task: dict, mode: str, *, model_config: list[dict] | None = None, env_extra: dict | None = None, keep: Path | None = None) -> Iterator[Trial]:
    root = Path(tempfile.mkdtemp(prefix=f"omni-eval-{task['id']}-"))
    config_path = build_config(root, task, mode, model_config=model_config)
    env = trial_env(root, config_path)
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
    env = {k: v for k, v in os.environ.items() if not k.startswith("OMNI_HARNESS_")}
    env.update(env_extra)
    env.update(trial.env)
    env["PYTHONPATH"] = os.pathsep.join([str(BACKEND), str(EVAL_DIR)])
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
        with httpx.Client(base_url=trial.base_url, timeout=900) as client:
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


def _wait_idle(client: Any, thread_id: str, timeout: float) -> None:
    deadline = time.time() + timeout
    time.sleep(0.2)
    while time.time() < deadline:
        runs = client.get(f"/api/threads/{thread_id}/runs").json()
        if not any(r.get("status") in ("pending", "running") for r in runs):
            return
        time.sleep(0.5)


def _open_cards(client: Any, thread_id: str) -> list[dict]:
    body = client.get("/api/confirmations").json()
    return [a for a in body.get("actions") or [] if a.get("thread_id") == thread_id]


def _answer_cards(client: Any, thread_id: str, policy: str, seen: dict[str, dict], timeout: float) -> None:
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
        _wait_idle(client, thread_id, timeout)


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
    budget = task.get("budget") or {}
    timeout = float(budget.get("seconds", 600 if mode == "real" else 60))
    with gateway(task, mode, **gateway_kwargs) as trial:
        client = trial.client
        _seed(client, task.get("fixtures") or {})
        thread_id = client.post("/api/threads", json={}).json()["thread_id"]
        context = {**MODES[task.get("mode", "pro")], "thread_id": thread_id}
        turns = task["prompt"] if isinstance(task["prompt"], list) else [task["prompt"]]
        seen: dict[str, dict] = {}
        error = None
        for text in turns:
            body = {"assistant_id": "lead_agent", "input": {"messages": [{"type": "human", "content": [{"type": "text", "text": text}]}]}, "config": {"recursion_limit": 200}, "context": context}
            try:
                resp = client.post(f"/api/threads/{thread_id}/runs/wait", json=body, timeout=timeout)
                if resp.status_code != 200:
                    error = f"run failed: HTTP {resp.status_code}: {resp.text[:200]}"
            except Exception as exc:  # noqa: BLE001
                error = f"run failed: {type(exc).__name__}: {exc}"[:300]
            _wait_idle(client, thread_id, timeout)
            _answer_cards(client, thread_id, task.get("confirm", "none"), seen, timeout)
            _wait_idle(client, thread_id, timeout)
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
        tokens = {"input": sum((t.get("tokens") or {}).get("input", 0) for t in traces), "output": sum((t.get("tokens") or {}).get("output", 0) for t in traces)}
        costs = [t.get("cost_usd") for t in traces]
        cost = round(sum(c for c in costs if c), 6) if traces and all(c is not None for c in costs) else (None if mode == "real" else 0.0)
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
            "thread_id": thread_id,
            "final": outcome.final[:4000],
            "tools": outcome.names,
            "cards": [{"tool": c.get("tool_name"), "answered": c.get("answered")} for c in seen.values()],
            "verification": outcome.final_verification,
            "trace_count": len(traces),
        }


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
