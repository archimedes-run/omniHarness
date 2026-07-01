"""Robustness tests for extensions_config.json read/write (Part C).

Covers atomic writes (temp + fsync + os.replace) and the fail-safe loader that
keeps the last-known-good config when the file is found truncated/invalid —
so a partial write can never wipe out ALL loaded tools.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from omniharness.config import extensions_config as ec
from omniharness.config.extensions_config import ExtensionsConfig, atomic_write_json


@pytest.fixture(autouse=True)
def _clear_last_known_good():
    ec._last_known_good.clear()
    yield
    ec._last_known_good.clear()


def test_atomic_write_produces_valid_json_no_temp_leftovers(tmp_path: Path):
    cfg = tmp_path / "extensions_config.json"
    data = {"mcpServers": {"filesystem": {"enabled": True, "type": "stdio"}}, "skills": {}}

    atomic_write_json(cfg, data)

    loaded = ExtensionsConfig.from_file(str(cfg))
    assert list(loaded.mcp_servers.keys()) == ["filesystem"]
    # No leftover temp files in the directory.
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "extensions_config.json"]
    assert leftovers == []


def test_atomic_write_overwrites_existing(tmp_path: Path):
    cfg = tmp_path / "extensions_config.json"
    cfg.write_text(json.dumps({"mcpServers": {"old": {"enabled": True}}, "skills": {}}))

    atomic_write_json(cfg, {"mcpServers": {"new": {"enabled": True}}, "skills": {}})

    assert list(json.loads(cfg.read_text())["mcpServers"].keys()) == ["new"]


def test_truncated_file_falls_back_to_last_known_good(tmp_path: Path):
    cfg = tmp_path / "extensions_config.json"
    cfg.write_text(json.dumps({"mcpServers": {"filesystem": {"enabled": True, "type": "stdio"}}, "skills": {}}))

    good = ExtensionsConfig.from_file(str(cfg))
    assert list(good.mcp_servers.keys()) == ["filesystem"]

    # Simulate a partial/torn write (the Docker single-file bind-mount bug).
    cfg.write_text('{"mcpServers": {"composio-gm')

    recovered = ExtensionsConfig.from_file(str(cfg))
    # Must NOT drop all tools — keeps the last-known-good.
    assert list(recovered.mcp_servers.keys()) == ["filesystem"]


def test_invalid_file_without_prior_good_returns_empty_not_raise(tmp_path: Path):
    cfg = tmp_path / "extensions_config.json"
    cfg.write_text('{"mcpServers": {"broke')  # invalid, and no prior good load

    # Should return an empty config rather than raising and killing tool loading.
    recovered = ExtensionsConfig.from_file(str(cfg))
    assert recovered.mcp_servers == {}
    assert recovered.skills == {}
