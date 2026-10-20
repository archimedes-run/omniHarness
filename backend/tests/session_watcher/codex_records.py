"""Synthetic Codex rollout records, shaped like a real ~/.codex (2026-10-19).

The SHAPES (keys, types, nesting, the outputs' acknowledgement and exit-code
lines) were taken from the user's own files, structure only. The CONTENT here
is invented. See specs/005-project-ledger/research.md section 2.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

T0 = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)


def ts(minutes: float) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def row(minutes: float, rtype: str, payload: dict) -> dict:
    return {"timestamp": ts(minutes), "type": rtype, "payload": payload}


def meta(minutes: float, sid: str, cwd: str = "/Users/dev/projects/beta-site", **extra) -> dict:
    return row(minutes, "session_meta", {"id": sid, "cwd": cwd, "timestamp": ts(minutes), "cli_version": "0.0.0", "originator": "codex_vscode", "model_provider": "openai", "source": "vscode", "base_instructions": {"text": "x"}, **extra})


def event(minutes: float, ptype: str, **payload) -> dict:
    return row(minutes, "event_msg", {"type": ptype, **payload})


def item(minutes: float, ptype: str, **payload) -> dict:
    return row(minutes, "response_item", {"type": ptype, **payload})


def plan_call(minutes: float, call_id: str, steps: list[tuple[str, str]], explanation: str = "") -> dict:
    args = {"plan": [{"step": s, "status": st} for s, st in steps]}
    if explanation:
        args["explanation"] = explanation
    return item(minutes, "function_call", name="update_plan", arguments=json.dumps(args), call_id=call_id)


def plan_ok(minutes: float, call_id: str) -> dict:
    return item(minutes, "function_call_output", call_id=call_id, output="Plan updated")


def patch_call(minutes: float, call_id: str, files: list[str]) -> dict:
    body = "*** Begin Patch\n" + "".join(f"*** Update File: {f}\n@@\n-a\n+b\n" for f in files) + "*** End Patch\n"
    return item(minutes, "custom_tool_call", name="apply_patch", input=body, call_id=call_id, status="completed")


def patch_end(minutes: float, call_id: str, files: list[str], success: bool) -> dict:
    return event(minutes, "patch_apply_end", call_id=call_id, turn_id="t1", success=success, status="completed" if success else "failed", changes={f: {"type": "update"} for f in files}, stdout="", stderr="")


def write(root: Path, day: str, sid: str, rows: list[dict], *, mtime: datetime | None = None) -> Path:
    """Write a rollout under sessions/YYYY/MM/DD/, optionally back-dating it."""
    folder = root / day
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"rollout-{day.replace('/', '-')}T09-00-00-{sid}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    if mtime is not None:
        os.utime(path, (mtime.timestamp(), mtime.timestamp()))
    return path
