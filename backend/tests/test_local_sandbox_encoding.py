import builtins

import omniharness.sandbox.local.local_sandbox as local_sandbox
from omniharness.sandbox.local.local_sandbox import LocalSandbox


def _open(base, file, mode="r", *args, **kwargs):
    if "b" in mode:
        return base(file, mode, *args, **kwargs)
    return base(file, mode, *args, encoding=kwargs.pop("encoding", "gbk"), **kwargs)


def test_read_file_uses_utf8_on_windows_locale(tmp_path, monkeypatch):
    path = tmp_path / "utf8.txt"
    text = "\u201cutf8\u201d"
    path.write_text(text, encoding="utf-8")
    base = builtins.open

    monkeypatch.setattr(local_sandbox, "open", lambda file, mode="r", *args, **kwargs: _open(base, file, mode, *args, **kwargs), raising=False)

    assert LocalSandbox("t").read_file(str(path)) == text


def test_write_file_uses_utf8_on_windows_locale(tmp_path, monkeypatch):
    path = tmp_path / "utf8.txt"
    text = "emoji \U0001f600"
    base = builtins.open

    monkeypatch.setattr(local_sandbox, "open", lambda file, mode="r", *args, **kwargs: _open(base, file, mode, *args, **kwargs), raising=False)

    LocalSandbox("t").write_file(str(path), text)

    assert path.read_text(encoding="utf-8") == text


def test_execute_command_runs_nothing_on_the_host(monkeypatch):
    """Host command execution was removed: execute_command refuses, and no
    process is ever spawned (security baseline)."""
    import subprocess

    def boom(*args, **kwargs):
        raise AssertionError("a host process was spawned")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    out = local_sandbox.LocalSandbox("t").execute_command("echo hello")
    assert out == local_sandbox.HOST_EXECUTION_REMOVED
