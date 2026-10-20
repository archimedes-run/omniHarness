"""Files handed to built servers (#59): no secret in any argv or env, and a
secrets file whose lines can't be forged or redirect the proxy."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib.util
import os
import sys
import textwrap

import pytest
from mcp_fakes import FakeDockerRunner

from app.gateway.mcp_container_files import SecretFileError, deliver, render_secrets, secret_name_problem
from app.gateway.mcp_runtime import ASSEMBLER, LAUNCHER


@pytest.mark.parametrize("name", ["HTTPS_PROXY", "https_proxy", "ld_preload", "LD_PRELOAD", "MCP_PORT", "__INBOUND_TOKEN", "PYTHONPATH", "HOME", "PATH", "SSL_CERT_FILE", "OMNI_RUN_DIR", "1BAD", "bad-name", ""])
def test_reserved_or_malformed_names_are_refused(name: str) -> None:
    assert secret_name_problem(name) is not None
    with pytest.raises(SecretFileError):
        render_secrets({name: "x"})


def test_a_value_with_a_line_break_is_refused() -> None:
    with pytest.raises(SecretFileError, match="line break"):
        render_secrets({"GITHUB_TOKEN": "ghp_x\nHTTPS_PROXY=http://evil:1"})


def test_only_the_gateway_sets_proxy_keys() -> None:
    data = render_secrets({"GITHUB_TOKEN": "t0k"}, gateway={"HTTPS_PROXY": "http://mcp:pw@10.0.0.2:3128"})
    assert data == b"GITHUB_TOKEN=t0k\nHTTPS_PROXY=http://mcp:pw@10.0.0.2:3128\n"
    with pytest.raises(SecretFileError):
        render_secrets({}, gateway={"LD_PRELOAD": "/x.so"})


def test_values_travel_on_stdin_only() -> None:
    runner = FakeDockerRunner()
    secret = b"GITHUB_TOKEN=ghp_REALLYSECRET123\n"
    asyncio.run(deliver(runner, "omni-mcp-abc", "10001", {"secrets": secret}))
    assert all(b"REALLYSECRET" not in " ".join(c.args).encode() for c in runner.calls)
    assert runner.calls[0].stdin == secret
    assert "umask 0377" in runner.calls[0].args[-1]
    assert runner.calls[-1].args[-1].endswith("chmod 0500 /run/omni")
    with pytest.raises(ValueError):
        asyncio.run(deliver(runner, "c", "10001", {"../etc/passwd": b"x"}))


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_launcher_reads_keys_into_its_own_process_and_never_runs_main(tmp_path, monkeypatch) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "secrets").write_text("GITHUB_TOKEN=ghp_abc\n")
    (run / "ready").write_text("")
    server = tmp_path / "server.py"
    server.write_text(
        textwrap.dedent(
            """
            from mcp.server.fastmcp import FastMCP
            mcp = FastMCP("t")
            if __name__ == "__main__":
                raise SystemExit("the server's own main block ran")
            """
        )
    )
    monkeypatch.setenv("OMNI_RUN_DIR", str(run))
    monkeypatch.setenv("OMNI_SERVER_PATH", str(server))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    launch = _load(LAUNCHER, "omni_launch_under_test")
    launch.wait_for_files()
    assert launch.load_secrets() == 1
    assert os.environ["GITHUB_TOKEN"] == "ghp_abc"
    from mcp.server.fastmcp import FastMCP

    assert isinstance(launch.load_server(), FastMCP)
    sys.modules.pop("omni_built_server", None)


def test_the_package_assembler_refuses_a_file_that_does_not_match_its_record(tmp_path, monkeypatch) -> None:
    assemble = _load(ASSEMBLER, "omni_assemble_under_test")
    site = tmp_path / "site"
    pkg = site / "fakepkg"
    pkg.mkdir(parents=True)
    good = b"print('hello')\n"
    (pkg / "__init__.py").write_bytes(good)
    digest = base64.urlsafe_b64encode(hashlib.sha256(good).digest()).rstrip(b"=").decode()
    info = site / "fakepkg-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: fakepkg\nVersion: 1.0\n")
    (info / "RECORD").write_text(f"fakepkg/__init__.py,sha256={digest},{len(good)}\nfakepkg-1.0.dist-info/METADATA,,\nfakepkg-1.0.dist-info/RECORD,,\n")
    monkeypatch.syspath_prepend(str(site))
    data, versions = assemble.assemble(roots=("fakepkg",))
    assert versions == {"fakepkg": "1.0"}
    (pkg / "__init__.py").write_bytes(b"import os; os.system('curl evil')\n")
    with pytest.raises(assemble.IntegrityError):
        assemble.assemble(roots=("fakepkg",))
