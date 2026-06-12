"""Tests for omniharness.skills.code_scanner.

Static patterns must block without an LLM call. Tests run fully offline.
"""

from __future__ import annotations

import pytest

from omniharness.skills.code_scanner import ScanResult, extract_env_keys, scan_python_code, scan_python_code_static

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _scan(source: str) -> ScanResult:
    """Run the scanner with no app_config (LLM stage will fail-closed if hit)."""
    return await scan_python_code(source, location="test")


# ---------------------------------------------------------------------------
# Static block patterns — must return immediately without hitting LLM
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_subprocess_is_blocked() -> None:
    result = await _scan("import subprocess\nsubprocess.run(['ls'])")
    assert result.decision == "block"
    assert "subprocess" in result.reason.lower()


@pytest.mark.anyio
async def test_os_system_is_blocked() -> None:
    result = await _scan("import os\nos.system('rm -rf /')")
    assert result.decision == "block"


@pytest.mark.anyio
async def test_os_popen_is_blocked() -> None:
    result = await _scan("import os\nos.popen('ls')")
    assert result.decision == "block"


@pytest.mark.anyio
async def test_eval_is_blocked() -> None:
    result = await _scan("eval(user_input)")
    assert result.decision == "block"
    assert "eval" in result.reason.lower()


@pytest.mark.anyio
async def test_exec_is_blocked() -> None:
    result = await _scan("exec(compiled_code)")
    assert result.decision == "block"


@pytest.mark.anyio
async def test_pickle_is_blocked() -> None:
    result = await _scan("import pickle\npickle.loads(data)")
    assert result.decision == "block"


@pytest.mark.anyio
async def test_ctypes_is_blocked() -> None:
    result = await _scan("import ctypes\nctypes.CDLL('libc.so.6')")
    assert result.decision == "block"


@pytest.mark.anyio
async def test_dunder_import_is_blocked() -> None:
    result = await _scan("m = __import__('os')")
    assert result.decision == "block"


# ---------------------------------------------------------------------------
# env-var extraction
# ---------------------------------------------------------------------------


def test_extract_env_keys_single() -> None:
    keys = extract_env_keys("import os\napi_key = os.getenv('API_KEY')")
    assert keys == ["API_KEY"]


def test_extract_env_keys_multiple_deduplicated() -> None:
    src = "os.getenv('FOO')\nos.getenv('BAR')\nos.getenv('FOO')"
    keys = extract_env_keys(src)
    assert keys == ["FOO", "BAR"]


def test_extract_env_keys_empty() -> None:
    assert extract_env_keys("x = 1\ny = 2") == []


def test_extract_env_keys_double_quotes() -> None:
    keys = extract_env_keys('os.getenv("SECRET_TOKEN")')
    assert "SECRET_TOKEN" in keys


def test_extract_env_keys_lowercase_ignored() -> None:
    """Lowercase env var names don't match — convention is UPPER_CASE."""
    keys = extract_env_keys("os.getenv('not_upper')")
    assert keys == []


# ---------------------------------------------------------------------------
# Clean code — no static block, but LLM will fail without a real model
# (fail-closed → "block"). Verify the *static* stage doesn't block it.
# ---------------------------------------------------------------------------


_STATIC_REASONS = frozenset(
    {
        "subprocess usage is not permitted in MCP server code",
        "os shell execution is not permitted",
        "eval() usage is not permitted",
        "exec() usage is not permitted",
        "__import__() usage is not permitted",
        "pickle deserialization is not permitted",
        "ctypes usage is not permitted",
        "base64-decode-then-execute pattern detected",
    }
)


@pytest.mark.anyio
async def test_clean_code_passes_static_stage() -> None:
    """A simple HTTP request has no static-block matches; decision depends on LLM.

    In CI without a model, the LLM stage fails and returns 'block' (fail-closed).
    We only verify the *reason* doesn't come from the static pre-filter.
    """
    clean = "import httpx\nresponse = httpx.get('https://api.example.com/data')\nprint(response.json())"
    result = await scan_python_code(clean, location="test")
    # The static stage would set reason to one of the known patterns; if we get
    # 'Security scan unavailable' that means the static stage passed and the LLM
    # stage failed-closed correctly.
    assert result.reason not in _STATIC_REASONS


@pytest.mark.anyio
async def test_egress_hosts_parameter_accepted() -> None:
    """egress_hosts can be passed without errors; static stage still governs."""
    api_connector = (
        "import json, os, httpx\n"
        "from mcp.server.fastmcp import FastMCP\n"
        "mcp = FastMCP('hunter')\n"
        "API_KEY = os.getenv('HUNTERIO_API_KEY')\n"
        "@mcp.tool()\n"
        "def search(domain: str) -> str:\n"
        '    """Search emails for a domain."""\n'
        "    if not API_KEY: return json.dumps({'error': 'missing key'})\n"
        "    r = httpx.get('https://api.hunter.io/v2/domain-search', params={'domain': domain, 'api_key': API_KEY})\n"
        "    return r.text\n"
        "if __name__ == '__main__': mcp.run()\n"
    )
    result = await scan_python_code(
        api_connector,
        location="test",
        egress_hosts=["api.hunter.io"],
    )
    # Static stage must not block — no subprocess/eval/exec in this code
    assert result.reason not in _STATIC_REASONS


def test_scan_python_code_static_does_not_block_clean_api_code() -> None:
    """An httpx API wrapper with os.getenv passes the static scanner."""
    clean = "import json, os, httpx\nAPI_KEY = os.getenv('HUNTERIO_API_KEY')\ndef fetch(domain: str) -> str:\n    r = httpx.get('https://api.hunter.io/v2/domain-search', params={'api_key': API_KEY, 'domain': domain})\n    return r.text\n"
    assert scan_python_code_static(clean) is None
