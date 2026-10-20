"""Tiers of built MCP tools (Feature 006, #59).

A built server's tools never match the shared rules: their tier is the one
the user set on the approval screen, recorded with the approval in the
server's ``extensions_config.json`` entry (``built.tool_tiers``), and Tier 3
when unset. The file is re-read when its mtime changes, so every gateway
worker sees an approval as soon as it is written.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from omniharness.tools.names import canonical_tool_name

from .models import Tier

BUILT_PREFIX = "built__"

_lock = threading.Lock()
_cache: dict[str, object] = {"path": None, "mtime": None, "tiers": {}}


def _config_path() -> Path | None:
    from omniharness.config.extensions_config import ExtensionsConfig

    try:
        return ExtensionsConfig.resolve_config_path()
    except Exception:
        return None


def _load(path: Path) -> dict[str, Tier]:
    tiers: dict[str, Tier] = {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return tiers
    for key, entry in (data.get("mcpServers") or {}).items():
        if not canonical_tool_name(key).startswith(BUILT_PREFIX) or not isinstance(entry, dict):
            continue
        built = entry.get("built") or {}
        for tool, tier in (built.get("tool_tiers") or {}).items():
            if tier in (1, 2, 3):
                tiers[canonical_tool_name(f"{key}_{tool}")] = Tier(tier)
    return tiers


def is_built_tool(tool_name: str) -> bool:
    return canonical_tool_name(tool_name).startswith(BUILT_PREFIX)


def built_tool_tier(tool_name: str) -> Tier:
    """The tier set on the approval screen for this built tool; Tier 3 if none."""
    path = _config_path()
    tiers: dict[str, Tier] = {}
    if path is not None:
        try:
            mtime = os.stat(path).st_mtime_ns
        except OSError:
            mtime = None
        with _lock:
            if _cache["path"] != str(path) or _cache["mtime"] != mtime:
                _cache.update(path=str(path), mtime=mtime, tiers=_load(path) if mtime is not None else {})
            tiers = _cache["tiers"]  # type: ignore[assignment]
    return tiers.get(canonical_tool_name(tool_name), Tier.TIER_3)
