"""No configuration can start an agent's command on the host.

Host bash was removed (not made opt-in): LocalSandbox runs nothing, the bash
tool and bash subagent need a container sandbox, and a config that still names
a host-execution key is refused at startup with the line to delete. Every code
path that spawns a process is enumerated below; a new one fails this file
until it is classified.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]

#: Every module that spawns a process, and why that is not an agent command
#: running on the host. A new spawner anywhere in app/ or packages/ fails
#: test_every_process_spawner_is_classified until it is added here.
SPAWNERS = {
    "app/gateway/mcp_server_manager.py": "container runtime only (docker build/run/rm for built MCP servers; published on 127.0.0.1). Its in-gateway stdio test phase is refused (#76)",
    "packages/harness/omniharness/community/aio_sandbox/local_backend.py": "container runtime only (the sandbox containers themselves)",
    # Library launchers (a process started by a library from a spec we build):
    "packages/harness/omniharness/mcp/client.py": (
        "NOT agent-reachable: stdio MCP servers the OWNER configured in extensions_config.json (file, or PUT /api/mcp/config: signed-in owner only, never the internal token); the sandbox has no route to the gateway"
    ),
    "packages/harness/omniharness/tools/connector_tools.py": "NOT agent-chosen: fixed command (sys.executable + the bundled Composio server script), scrubbed env + exactly four COMPOSIO_* keys",
    "packages/harness/omniharness/utils/readability.py": "NOT agent-chosen: readabilipy's fixed node script (Readability.js) on fetched HTML passed as data, no shell",
}

_SPAWN_CALLS = {
    ("subprocess", "run"),
    ("subprocess", "Popen"),
    ("subprocess", "call"),
    ("subprocess", "check_call"),
    ("subprocess", "check_output"),
    ("asyncio", "create_subprocess_exec"),
    ("asyncio", "create_subprocess_shell"),
    ("os", "system"),
    ("os", "popen"),
    ("os", "execv"),
    ("os", "execvp"),
    ("os", "spawnv"),
    ("pty", "spawn"),
}
_SPAWN_NAMES = {"spawn_agent_process", "create_subprocess_exec", "create_subprocess_shell", "Popen", "stdio_client", "StdioServerParameters", "StdioConnection"}
#: Library calls that start a process for us.
_LIBRARY_LAUNCHERS = {"stdio_client", "StdioServerParameters", "StdioConnection"}


def _launches_via_library(node: ast.AST) -> bool:
    # A langchain-mcp-adapters / MultiServerMCPClient spec: {"transport": "stdio", ...}
    # or the transport chosen at run time from config ({"transport": transport_type}).
    if isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value == "transport":
                if not (isinstance(value, ast.Constant) and value.value in ("sse", "http", "streamable_http", "websocket")):
                    return True
    # readabilipy runs node when use_readability is truthy.
    if isinstance(node, ast.Call):
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        if name == "simple_json_from_html_string":
            for kw in node.keywords:
                if kw.arg == "use_readability" and not (isinstance(kw.value, ast.Constant) and not kw.value.value):
                    return True
    return False


def _spawns(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and (func.value.id, func.attr) in _SPAWN_CALLS:
                return True
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Attribute) and func.attr in ("create_subprocess_exec", "create_subprocess_shell"):
                return True
            if isinstance(func, ast.Name) and func.id in _SPAWN_NAMES:
                return True
            if isinstance(func, ast.Attribute) and func.attr in _LIBRARY_LAUNCHERS:
                return True
        if _launches_via_library(node):
            return True
    return False


def test_every_process_spawner_is_classified() -> None:
    found = set()
    for root in ("app", "packages"):
        for path in (BACKEND / root).rglob("*.py"):
            if "tests" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            if _spawns(tree):
                found.add(path.relative_to(BACKEND).as_posix())
    assert found, "the sweep found no spawner at all"
    unclassified = sorted(found - set(SPAWNERS))
    assert not unclassified, f"new process spawners, classify them in SPAWNERS: {unclassified}"
    stale = sorted(set(SPAWNERS) - found)
    assert not stale, f"no longer spawn, drop from SPAWNERS: {stale}"
    assert "packages/harness/omniharness/sandbox/local/local_sandbox.py" not in found, "the host-bash executor came back"


@pytest.mark.parametrize("key", ["allow_host_bash", "allow_host_bash_unsafe", "allow_host_execution"])
def test_a_config_naming_a_host_execution_key_is_refused_with_the_line_to_delete(key) -> None:
    from pydantic import ValidationError

    from omniharness.config.sandbox_config import SandboxConfig

    with pytest.raises(ValidationError) as exc:
        SandboxConfig(use="omniharness.sandbox.local:LocalSandboxProvider", **{key: False})
    assert f"Delete the line 'sandbox.{key}'" in str(exc.value)
    SandboxConfig(use="omniharness.sandbox.local:LocalSandboxProvider")  # positive control


def test_the_gateway_refuses_to_start_on_such_a_config(tmp_path, monkeypatch) -> None:
    import yaml

    from omniharness.config.app_config import AppConfig

    example = (BACKEND.parent / "config.example.yaml").read_text()
    data = yaml.safe_load(example)
    data.setdefault("sandbox", {})["allow_host_bash"] = False  # even false: the key itself is refused
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(Exception) as exc:
        AppConfig.from_file(str(path))
    assert "allow_host_bash" in str(exc.value) and "Delete the line" in str(exc.value)


def test_local_sandbox_and_bash_tool_never_run_a_host_command(monkeypatch) -> None:
    import subprocess

    from omniharness.sandbox.local.local_sandbox import HOST_EXECUTION_REMOVED, LocalSandbox
    from omniharness.sandbox.security import is_host_bash_allowed

    def boom(*args, **kwargs):
        raise AssertionError("a host process was spawned")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    assert LocalSandbox("t").execute_command("id") == HOST_EXECUTION_REMOVED
    from types import SimpleNamespace

    local = SimpleNamespace(sandbox=SimpleNamespace(use="omniharness.sandbox.local:LocalSandboxProvider", allow_host_bash=True))
    container = SimpleNamespace(sandbox=SimpleNamespace(use="omniharness.community.aio_sandbox:AioSandboxProvider"))
    assert is_host_bash_allowed(local) is False
    assert is_host_bash_allowed(container) is True


def _example_config() -> dict:
    import yaml

    return yaml.safe_load((BACKEND.parent / "config.example.yaml").read_text())


@pytest.mark.parametrize(
    "mutate, named",
    [
        (lambda d: d.__setitem__("acp_agents", {"codex": {"command": "npx", "args": ["-y", "@zed-industries/codex-acp"]}}), "acp_agents"),
        (lambda d: d.__setitem__("acp_agents", {}), "acp_agents"),  # even empty: the key itself is refused
        (lambda d: d.__setitem__("acp", {"agents": {}}), "acp"),
        (lambda d: d.setdefault("tools", []).append({"name": "openclaude_coder", "group": "code", "use": "app.tools.openclaude:OpenClaudeTool"}), "openclaude_coder"),
        (lambda d: d.setdefault("tools", []).append({"name": "coder", "group": "code", "use": "omniharness.tools.builtins.invoke_acp_agent_tool:x"}), "invoke_acp_agent"),
    ],
)
def test_a_config_naming_openclaude_or_acp_is_refused_at_startup(tmp_path, mutate, named) -> None:
    import yaml

    from omniharness.config.app_config import AppConfig

    data = _example_config()
    mutate(data)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(Exception) as exc:
        AppConfig.from_file(str(path))
    assert named in str(exc.value) and "Delete" in str(exc.value) and "container sandbox" in str(exc.value)
    with pytest.raises(Exception):  # and through direct construction, not only from_file
        AppConfig.model_validate(data)


def test_the_example_config_still_loads(tmp_path) -> None:
    """Positive control for the refusals above."""
    import yaml

    from omniharness.config.app_config import AppConfig

    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(_example_config()))
    assert not hasattr(AppConfig.from_file(str(path)), "acp_agents")


def test_no_code_can_start_openclaude_or_an_acp_agent() -> None:
    """The launchers are gone: no module, no tool, no rule, nothing reachable."""
    import importlib.util

    for module in ("app.tools.openclaude", "omniharness.tools.builtins.invoke_acp_agent_tool", "omniharness.config.acp_config"):
        try:
            spec = importlib.util.find_spec(module)
        except ModuleNotFoundError:
            spec = None
        assert spec is None, module
    hits = []
    for root in ("app", "packages"):
        for path in (BACKEND / root).rglob("*"):
            if path.suffix not in {".py", ".yaml", ".json"} or "tests" in path.parts or path.name == "app_config.py":
                continue
            text = path.read_text(errors="ignore")
            hits += [f"{path.relative_to(BACKEND)}: {n}" for n in ("openclaude", "invoke_acp_agent", "acp_agents", "get_acp_agents", "spawn_agent_process") if n in text]
    assert not hits, hits
