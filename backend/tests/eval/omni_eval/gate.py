"""`make eval-gate EVAL_FILES="full.json rerun.json"`: the owner's Slice 0 gate
over one or more real-mode result files.

The gate (baseline.json `gate`): beat the baseline's core and strict scores,
and every `must_pass` task passes. A task run with k > 1 trials passes on a
majority. When a task appears in several files, the file with the most trials
of it is used (a full single run plus a 3-trial rerun of the flaky tasks).

Exits 0 when the gate passes, 1 when it fails or is incomplete.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .harness import REPO
from .report import evaluate_gate, load_baseline


def _path(name: str) -> Path:
    path = Path(name)
    return path if path.is_absolute() or path.exists() else REPO / name


def combine(results: list[dict]) -> list[dict]:
    """Per task, the entry with the most trials (the latest file on a tie)."""
    best: dict[str, dict] = {}
    for result in results:
        for task in result.get("tasks") or []:
            if task.get("not_run"):
                continue
            task = {
                **task,
                "majority_pass": task.get("majority_pass", (task.get("trial_passes", int(bool(task.get("core_pass")))) * 2 > task.get("trials", 1))),
                "strict_majority_pass": task.get("strict_majority_pass", bool(task.get("strict_pass"))),
            }
            current = best.get(task["id"])
            if current is None or task.get("trials", 1) >= current.get("trials", 1):
                best[task["id"]] = task
    return list(best.values())


def main(argv: list[str] | None = None) -> int:
    names = list(sys.argv[1:] if argv is None else argv)
    if not names:
        print('usage: make eval-gate EVAL_FILES="eval/results/<full>.json eval/results/<rerun>.json"', file=sys.stderr)
        return 2
    results = [json.loads(_path(n).read_text()) for n in names]
    if any(r.get("mode") != "real" for r in results):
        print("the gate reads real-mode results only", file=sys.stderr)
        return 2
    baseline = load_baseline() or {}
    tasks = combine(results)
    gate = evaluate_gate(tasks, baseline.get("gate"))
    if not gate:
        print("baseline.json has no gate", file=sys.stderr)
        return 2
    print(f"baseline {baseline.get('id')}: {baseline.get('score')}")
    for task in sorted(tasks, key=lambda t: t["id"]):
        mark = "must" if task["id"] in gate["must_pass"] else "    "
        trials = f" ({task.get('trial_passes')}/{task.get('trials')})" if task.get("trials", 1) > 1 else ""
        print(f"  {task['id']:<5} {mark} {'PASS' if task['majority_pass'] else 'FAIL'}{trials}")
    beat = gate["beat"]
    print(f"core {gate['core']} (must be > {beat.get('core')}), strict {gate['strict']} (must be > {beat.get('strict')})")
    print(f"must pass failed: {', '.join(gate['failed_tasks']) or 'none'}" + (f"; not run: {', '.join(gate['not_run'])}" if gate["not_run"] else ""))
    verdict = "PASS" if gate["passed"] else ("INCOMPLETE" if not gate["complete"] else "FAIL")
    print(f"gate: {verdict}")
    return 0 if gate["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
