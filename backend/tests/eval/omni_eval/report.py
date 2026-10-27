"""Scores, the result file and the baseline comparison (spec 009 FR-070, FR-077).

A result is written to `<repo>/eval/results/<date>-<mode>-<git sha>.json`
(gitignored, local only; `EVAL_RESULTS_DIR` moves it). The tracked baseline is
`backend/tests/eval/baseline.json`: the latest ACCEPTED real-model result, per
task, so a regression (a task that passed in the baseline and fails now) is
computable and blocks the merge (D10, FR-067).
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from .harness import EVAL_DIR, REPO

BASELINE = EVAL_DIR / "baseline.json"


def results_dir() -> Path:
    return Path(os.environ.get("EVAL_RESULTS_DIR") or (REPO / "eval" / "results"))


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True, timeout=10).stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def load_baseline() -> dict | None:
    try:
        return json.loads(BASELINE.read_text())
    except (OSError, ValueError):
        return None


def summarise(results: list[dict], *, mode: str, model: str, trials: int, seconds: float) -> dict:
    """The suite result: per task (merged over trials), the score, pass^k."""
    by_task: dict[str, list[dict]] = {}
    for r in results:
        by_task.setdefault(r["id"], []).append(r)
    baseline = load_baseline() if mode == "real" else None
    base_tasks = (baseline or {}).get("tasks") or {}
    tasks = []
    for task_id, runs in by_task.items():
        first = runs[0]
        passed = [r["pass"] for r in runs]
        core = [r.get("core_pass", r["pass"]) for r in runs]
        entry = {
            **first,
            # pass^k: every trial passed. "pass" is the core score (the
            # task's outcome checks and linters); "strict_pass" adds the
            # Slice 0 behaviour checks (as the 2026-10-24 baseline did).
            "pass": all(core),
            "core_pass": all(core),
            "strict_pass": all(passed),
            "pass_at_k": any(core),
            "trials": len(runs),
            "trial_passes": sum(core),
            "baseline_pass": (base_tasks.get(task_id) or {}).get("core") if task_id in base_tasks else None,
            "seconds": round(sum(r["seconds"] for r in runs), 1),
            "cost_usd": None if any(r.get("cost_usd") is None for r in runs) else round(sum(r.get("cost_usd") or 0 for r in runs), 6),
        }
        tasks.append(entry)
    scored = [t for t in tasks if not t.get("not_run")]
    regressions = [t["id"] for t in scored if t.get("baseline_pass") is True and not t["core_pass"]]
    costs = [t.get("cost_usd") for t in tasks]
    sha = git_sha()
    created = datetime.now(UTC)
    return {
        "id": f"{created:%Y%m%dT%H%M%S}-{mode}-{sha}",
        "created_at": created.isoformat(),
        "mode": mode,
        "git_sha": sha,
        "model": model,
        "trials": trials,
        "passed": sum(1 for t in scored if t["pass"]),
        "core_passed": sum(1 for t in scored if t["pass"]),
        "strict_passed": sum(1 for t in scored if t["strict_pass"]),
        "total": len(scored),
        "cost_usd": None if any(c is None for c in costs) else round(sum(c or 0 for c in costs), 4),
        "seconds": round(seconds, 1),
        "regressions": regressions,
        "baseline": {k: baseline.get(k) for k in ("id", "score", "model", "date")} if baseline else None,
        "tasks": tasks,
    }


def write(result: dict) -> Path:
    out = results_dir()
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{result['id']}.json"
    path.write_text(json.dumps(result, indent=1, default=str))
    return path


def table(result: dict) -> str:
    lines = [f"{'task':<10} {'core':<5} {'strict':<6} {'base':<5} {'secs':>6} {'tokens':>9} {'cost':>8}  reason"]
    for t in result["tasks"]:
        failed = [c for c in t["checks"] if not c["pass"]]
        reason = "; ".join(f"{c['name']}: {c['reason']}" for c in failed)[:150] or "ok"
        tokens = (t.get("tokens") or {}).get("input", 0) + (t.get("tokens") or {}).get("output", 0)
        base = {True: "pass", False: "fail", None: "-"}[t.get("baseline_pass")]
        cost = "-" if t.get("cost_usd") is None else f"{t['cost_usd']:.4f}"
        k = f" ({t['trial_passes']}/{t['trials']})" if t.get("trials", 1) > 1 else ""
        lines.append(f"{t['id']:<10} {'PASS' if t['pass'] else 'FAIL':<5} {'PASS' if t['strict_pass'] else 'FAIL':<6} {base:<5} {t['seconds']:>6} {tokens:>9} {cost:>8}  {reason}{k}")
    cost = "-" if result["cost_usd"] is None else f"${result['cost_usd']:.4f}"
    lines.append("")
    lines.append(f"score ({result['mode']}, {result['model']}): core {result['core_passed']}/{result['total']}, strict {result['strict_passed']}/{result['total']}; {result['seconds']} s; cost {cost}")
    if result.get("baseline"):
        lines.append(f"baseline: {result['baseline'].get('score')}; regressions: {', '.join(result['regressions']) or 'none'}")
    return "\n".join(lines)
