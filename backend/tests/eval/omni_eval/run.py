"""`make eval`: run the suite and print a score (spec 009 FR-070, FR-078).

    EVAL_MODEL=mock  (default, CI)  scripted models, recorded web, no network, no secrets
    EVAL_MODEL=real                 the configured default model, against an isolated gateway per trial
    EVAL_TASKS=T01,T09              select tasks (default: all; real mode skips mock-only tasks)
    EVAL_TRIALS=k                   repeat each task k times: pass^k (all) and pass@k (any)
    EVAL_BUDGET_USD=5               real mode: refuse to start above it, and stop when spent
    EVAL_ENV_FILE=path              real mode: KEY=VALUE file the model key is read from, into the
                                    isolated gateway process only (never printed, never written)
    EVAL_MODEL_NAME=default         real mode: which configured model (default: the first)

Exits non-zero when any task fails (mock) or any baseline task regresses (real).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from . import harness, report

DEFAULT_TASK_COST_USD = 0.08


def _real_models(name: str | None) -> list[dict]:
    """The models section of the tracked example config (the configured
    default model); EVAL_MODEL_NAME picks one of its entries."""
    import yaml

    config = yaml.safe_load((harness.REPO / "config.example.yaml").read_text())
    models = config.get("models") or []
    if name:
        models = [m for m in models if m.get("name") == name] or models
    return models


def main(argv: list[str] | None = None) -> int:
    mode = (os.environ.get("EVAL_MODEL") or "mock").lower()
    if mode not in ("mock", "real"):
        print(f"EVAL_MODEL must be mock or real, not {mode!r}", file=sys.stderr)
        return 2
    selected = [t for t in (os.environ.get("EVAL_TASKS") or "").split(",") if t.strip()]
    trials = max(1, int(os.environ.get("EVAL_TRIALS") or 1))
    budget = float(os.environ.get("EVAL_BUDGET_USD") or 5)
    if mode == "mock":
        # A fresh clone has no key; the example config interpolates it eagerly.
        os.environ.setdefault("OPENAI_API_KEY", "placeholder-not-a-real-key")
    tasks = harness.load_tasks(selected or None)
    if mode == "real":
        tasks = [t for t in tasks if not t.get("mock_only")]
    if not tasks:
        print("no tasks selected", file=sys.stderr)
        return 2

    gateway_kwargs: dict = {}
    model = "scripted"
    if mode == "real":
        estimate = sum(float((t.get("budget") or {}).get("est_usd", DEFAULT_TASK_COST_USD)) for t in tasks) * trials
        if estimate > budget:
            print(f"refusing to start: the estimated cost ${estimate:.2f} is over EVAL_BUDGET_USD=${budget:.2f}", file=sys.stderr)
            return 3
        env_file = os.environ.get("EVAL_ENV_FILE")
        env_extra = harness.load_env_file(Path(env_file)) if env_file else {}
        models = _real_models(os.environ.get("EVAL_MODEL_NAME"))
        model = str(models[0].get("model") or models[0].get("name")) if models else "unknown"
        gateway_kwargs = {"model_config": models, "env_extra": env_extra}
        print(f"real mode: {len(tasks)} task(s) x {trials}, model {model}, estimate ${estimate:.2f} (cap ${budget:.2f})", flush=True)

    keep = os.environ.get("EVAL_KEEP_DIR")
    if keep:
        gateway_kwargs["keep"] = Path(keep)
    started = time.time()
    results: list[dict] = []
    spent = 0.0
    for task in tasks:
        for _trial in range(trials):
            if mode == "real" and spent >= budget:
                results.append(
                    {
                        "id": task["id"],
                        "title": task.get("title", ""),
                        "pass": False,
                        "core_pass": False,
                        "not_run": True,
                        "checks": [{"name": "budget", "pass": False, "reason": f"not run: ${spent:.2f} of ${budget:.2f} spent", "strict": False}],
                        "seconds": 0,
                        "tokens": None,
                        "cost_usd": 0.0,
                        "live_only": bool(task.get("live_only")),
                    }
                )
                continue
            try:
                result = harness.run_trial(task, mode, **gateway_kwargs)
            except Exception as exc:  # noqa: BLE001 - a trial that crashes fails, it never passes
                result = {
                    "id": task["id"],
                    "title": task.get("title", ""),
                    "pass": False,
                    "core_pass": False,
                    "checks": [{"name": "harness", "pass": False, "reason": f"{type(exc).__name__}: {exc}"[:300], "strict": False}],
                    "seconds": 0,
                    "tokens": None,
                    "cost_usd": None,
                    "live_only": bool(task.get("live_only")),
                }
            spent += float(result.get("cost_usd") or 0)
            results.append(result)
            failed = [c for c in result["checks"] if not c["pass"] and not c.get("strict")]
            print(
                f"{result['id']:<10} {'PASS' if result.get('core_pass', result['pass']) else 'FAIL'}  {result['seconds']:>6}s  ${float(result.get('cost_usd') or 0):.4f}  "
                + ("; ".join(f"{c['name']}: {c['reason']}" for c in failed)[:200] or "ok"),
                flush=True,
            )
    summary = report.summarise(results, mode=mode, model=model, trials=trials, seconds=time.time() - started)
    path = report.write(summary)
    print()
    print(report.table(summary))
    print(f"\nresult written to {path}")
    if os.environ.get("EVAL_JSON"):
        print(json.dumps({k: summary[k] for k in ("id", "passed", "strict_passed", "total", "regressions", "cost_usd")}))
    if mode == "mock":
        return 0 if summary["passed"] == summary["total"] and summary["strict_passed"] == summary["total"] else 1
    return 1 if summary["regressions"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
