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
    "app/gateway/mcp_server_manager.py": "container runtime only (docker build/run/rm for built MCP servers; published on 127.0.0.1)",
    "packages/harness/omniharness/community/aio_sandbox/local_backend.py": "container runtime only (the sandbox containers themselves)",
    "app/tools/openclaude.py": "EXTERNAL coding-agent CLI on the host (openclaude_coder, Tier 3): scrubbed env, only OPENAI_* passed (reported for a decision)",
    "packages/harness/omniharness/tools/builtins/invoke_acp_agent_tool.py": "EXTERNAL ACP agent CLIs on the host (invoke_acp_agent, Tier 3): scrubbed env + configured keys (reported for a decision)",
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
_SPAWN_NAMES = {"spawn_agent_process", "create_subprocess_exec", "create_subprocess_shell", "Popen"}


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


def test_openclaude_gets_no_gateway_secrets() -> None:
    from app.tools.openclaude import openclaude_environment

    env = openclaude_environment({"PATH": "/bin", "HOME": "/h", "OPENAI_API_KEY": "sk-1", "OMNI_HARNESS_INTERNAL_AUTH_TOKEN": "t", "AUTH_JWT_SECRET": "j", "COMPOSIO_API_KEY": "c", "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/x"})
    assert env == {"PATH": "/bin", "HOME": "/h", "OPENAI_API_KEY": "sk-1"}
