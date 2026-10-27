"""Eval results for Settings -> Evals (spec 009 Slice 0, FR-077).

`make eval` writes one JSON result per suite run to `<repo>/eval/results/`
(or EVAL_RESULTS_DIR), local and gitignored; the accepted real-model baseline
is the tracked `backend/tests/eval/baseline.json`. This router only READS
them: the score history and one run's per-task results. Owner only, like the
run history's settings.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.gateway.authz import require_permission

router = APIRouter(prefix="/api/evals", tags=["evals"])

_BACKEND = Path(__file__).resolve().parents[3]
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
_SUMMARY_KEYS = ("id", "created_at", "mode", "git_sha", "model", "trials", "passed", "total", "strict_passed", "cost_usd", "seconds", "regressions")


def results_dir() -> Path:
    return Path(os.environ.get("EVAL_RESULTS_DIR") or (_BACKEND.parent / "eval" / "results"))


def _baseline() -> dict | None:
    path = _BACKEND / "tests" / "eval" / "baseline.json"
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    tasks = raw.get("tasks") or {}
    total = len(tasks)
    return {
        "id": raw.get("id"),
        "created_at": raw.get("date"),
        "mode": "real",
        "git_sha": raw.get("code"),
        "model": raw.get("model"),
        "trials": 1,
        "passed": sum(1 for t in tasks.values() if t.get("core")),
        "strict_passed": sum(1 for t in tasks.values() if t.get("strict")),
        "total": total,
        "cost_usd": raw.get("cost_usd"),
        "seconds": None,
        "regressions": [],
        "tasks": [
            {
                "id": k,
                "title": "",
                "pass": bool(v.get("core")),
                "strict_pass": bool(v.get("strict")),
                "live_only": False,
                "baseline_pass": None,
                "checks": [{"name": "baseline", "pass": bool(v.get("core")), "reason": v.get("note") or ""}],
                "seconds": None,
                "tokens": None,
                "cost_usd": None,
                "thread_id": None,
            }
            for k, v in tasks.items()
        ],
    }


def _load(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("id") else None


async def _owner_only(request: Request) -> None:
    from app.gateway.ownership import require_access
    from omniharness.runtime.user_context import DEFAULT_USER_ID

    await require_access(request, DEFAULT_USER_ID, what="eval results")


@router.get("")
@require_permission("threads", "read")
async def list_evals(request: Request) -> dict[str, Any]:
    await _owner_only(request)
    folder = results_dir()
    runs = []
    if folder.is_dir():
        for path in folder.glob("*.json"):
            data = _load(path)
            if data is not None:
                runs.append({k: data.get(k) for k in _SUMMARY_KEYS})
    runs.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return {"baseline": _baseline(), "runs": runs[:200], "results_dir": str(folder)}


@router.get("/{eval_id}")
@require_permission("threads", "read")
async def get_eval(eval_id: str, request: Request) -> dict[str, Any]:
    await _owner_only(request)
    if eval_id == "baseline":
        base = _baseline()
        if base is None:
            raise HTTPException(status_code=404, detail="No baseline is recorded.")
        return base
    if not _SAFE_ID.match(eval_id):
        raise HTTPException(status_code=404, detail="No such eval run.")
    data = _load(results_dir() / f"{eval_id}.json")
    if data is None:
        raise HTTPException(status_code=404, detail="No such eval run.")
    keep = ("id", "title", "pass", "strict_pass", "live_only", "baseline_pass", "checks", "seconds", "tokens", "cost_usd", "thread_id", "trials", "trial_passes")
    return {**{k: data.get(k) for k in _SUMMARY_KEYS}, "tasks": [{k: t.get(k) for k in keep} for t in data.get("tasks") or []]}
