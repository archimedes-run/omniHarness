import logging
import os
from types import SimpleNamespace

from omniharness.community.aio_sandbox.local_backend import (
    LocalContainerBackend,
    _format_container_command_for_log,
    _format_container_mount,
    _redact_container_command_for_log,
)


def test_format_container_mount_uses_mount_syntax_for_docker_windows_paths():
    args = _format_container_mount("docker", "D:/omni-harness/backend/.omni-harness/threads", "/mnt/threads", False)

    assert args == [
        "--mount",
        "type=bind,src=D:/omni-harness/backend/.omni-harness/threads,dst=/mnt/threads",
    ]


def test_format_container_mount_marks_docker_readonly_mounts():
    args = _format_container_mount("docker", "/host/path", "/mnt/path", True)

    assert args == [
        "--mount",
        "type=bind,src=/host/path,dst=/mnt/path,readonly",
    ]


def test_format_container_mount_keeps_volume_syntax_for_apple_container():
    args = _format_container_mount("container", "/host/path", "/mnt/path", True)

    assert args == [
        "-v",
        "/host/path:/mnt/path:ro",
    ]


def test_redact_container_command_for_log_redacts_env_values():
    redacted = _redact_container_command_for_log(
        [
            "docker",
            "run",
            "-e",
            "API_KEY=secret-value",
            "--env=TOKEN=token-value",
            "--name",
            "sandbox",
            "image",
        ]
    )

    assert "API_KEY=<redacted>" in redacted
    assert "--env=TOKEN=<redacted>" in redacted
    assert "secret-value" not in " ".join(redacted)
    assert "token-value" not in " ".join(redacted)


def test_redact_container_command_for_log_keeps_inherited_env_names():
    redacted = _redact_container_command_for_log(
        [
            "docker",
            "run",
            "-e",
            "API_KEY",
            "--env=TOKEN",
            "--name",
            "sandbox",
            "image",
        ]
    )

    assert redacted == [
        "docker",
        "run",
        "-e",
        "API_KEY",
        "--env=TOKEN",
        "--name",
        "sandbox",
        "image",
    ]


def test_format_container_command_for_log_uses_windows_quoting(monkeypatch):
    monkeypatch.setattr(os, "name", "nt")

    command = _format_container_command_for_log(["docker", "run", "--name", "sandbox one", "image"])

    assert command == 'docker run --name "sandbox one" image'


def test_start_container_logs_redacted_env_values(monkeypatch, caplog):
    backend = LocalContainerBackend(
        image="sandbox:latest",
        base_port=8080,
        container_prefix="sandbox",
        config_mounts=[],
        environment={"API_KEY": "secret-value", "NORMAL": "visible-value"},
    )
    monkeypatch.setattr(backend, "_runtime", "docker")

    captured_cmd: list[str] = []

    def fake_run(cmd, **kwargs):
        captured_cmd.extend(cmd)
        return SimpleNamespace(stdout="container-id\n", stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)

    with caplog.at_level(logging.INFO, logger="omniharness.community.aio_sandbox.local_backend"):
        backend._start_container("sandbox-test", "omni-harness-sandboxes")

    joined_cmd = " ".join(captured_cmd)
    assert "API_KEY=secret-value" in joined_cmd
    assert "NORMAL=visible-value" in joined_cmd

    log_output = "\n".join(record.getMessage() for record in caplog.records)
    assert "API_KEY=<redacted>" in log_output
    assert "NORMAL=<redacted>" in log_output
    assert "secret-value" not in log_output
    assert "visible-value" not in log_output


def _capture_start_container_command(monkeypatch, backend: LocalContainerBackend, runtime: str = "docker") -> list[str]:
    monkeypatch.setattr(backend, "_runtime", runtime)
    captured_cmd: list[str] = []

    def fake_run(cmd, **kwargs):
        captured_cmd.extend(cmd)
        return SimpleNamespace(stdout="container-id\n", stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)
    backend._start_container("sandbox-test", "omni-harness-sandboxes")
    return captured_cmd


def test_start_container_publishes_no_host_port_and_joins_the_private_network(monkeypatch):
    """Security baseline: the sandbox API runs shell commands. No -p at all;
    the container joins the network it shares with the gateway."""
    backend = LocalContainerBackend(image="sandbox:latest", base_port=8080, container_prefix="sandbox", config_mounts=[], environment={})

    captured_cmd = _capture_start_container_command(monkeypatch, backend)

    assert "-p" not in captured_cmd and "--publish" not in captured_cmd
    assert captured_cmd[captured_cmd.index("--network") + 1] == "omni-harness-sandboxes"


def _create(monkeypatch, *, runtime="docker", network="omni-harness-sandboxes"):
    import pytest

    from omniharness.community.aio_sandbox import local_backend as lb

    if network is None:
        monkeypatch.delenv(lb.SANDBOX_NETWORK_ENV, raising=False)
    else:
        monkeypatch.setenv(lb.SANDBOX_NETWORK_ENV, network)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(stdout="cid\n", stderr="", returncode=0)

    monkeypatch.setattr(lb.subprocess, "run", fake_run)
    backend = LocalContainerBackend(image="img", base_port=18080, container_prefix="omni-harness-sandbox", config_mounts=[], environment={})
    backend._runtime = runtime
    return backend, calls, pytest


def test_a_sandbox_is_reached_by_name_on_the_private_network(monkeypatch):
    backend, calls, _ = _create(monkeypatch)
    info = backend.create("t", "abc")
    assert info.sandbox_url == "http://omni-harness-sandbox-abc:8080"
    [run] = [c for c in calls if c[1] == "run"]
    assert "-p" not in run


def test_a_gateway_on_the_host_refuses_to_start_sandboxes(monkeypatch):
    from omniharness.community.aio_sandbox.local_backend import SANDBOX_REFUSED_WITHOUT_NETWORK

    backend, calls, pytest = _create(monkeypatch, network=None)
    with pytest.raises(RuntimeError) as exc:
        backend.create("t", "abc")
    assert str(exc.value) == SANDBOX_REFUSED_WITHOUT_NETWORK
    assert not [c for c in calls if c[1] == "run"], "nothing was started"
    assert backend.discover("abc") is None


def test_the_apple_container_runtime_is_refused(monkeypatch):
    from omniharness.community.aio_sandbox.local_backend import SANDBOX_REFUSED_APPLE

    backend, calls, pytest = _create(monkeypatch, runtime="container")
    with pytest.raises(RuntimeError) as exc:
        backend.create("t", "abc")
    assert str(exc.value) == SANDBOX_REFUSED_APPLE
    assert not [c for c in calls if c[1] == "run"]
