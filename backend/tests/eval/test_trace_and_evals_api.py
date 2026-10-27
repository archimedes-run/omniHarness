"""The per-run trace (spec 009 FR-080 to FR-082) and the evals API (FR-077),
through a real gateway (`create_app()`, the eval harness's isolated trial)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from omni_eval import harness, scripted  # noqa: E402

SECRET = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ab"


def _task(mock: dict, **extra) -> dict:
    return {"id": "TRACE", "title": "trace", "mode": "pro", "prompt": "x", "tools": [], "mock": mock, **extra}


def _run(client, thread_id: str, text: str) -> None:
    body = {"assistant_id": "lead_agent", "input": {"messages": [{"type": "human", "content": [{"type": "text", "text": text}]}]}, "context": {**harness.MODES["pro"], "thread_id": thread_id}}
    assert client.post(f"/api/threads/{thread_id}/runs/wait", json=body).status_code == 200


def _traces(client, thread_id: str) -> list[dict]:
    for _ in range(20):
        listing = client.get("/api/run-history/runs", params={"kind": "chat", "thread_id": thread_id}).json()
        if listing:
            return listing
        time.sleep(0.2)
    return []


def test_a_run_leaves_a_redacted_trace_with_steps_from_events() -> None:
    mock = {
        "lead": [
            {"tool_calls": [{"name": "web_fetch", "args": {"url": "https://notes.example/leaky"}}]},
            {"tool_calls": [{"name": "web_fetch", "args": {"url": "https://pypi.org/pypi/httpx/jsonx"}}]},
            {"tool_calls": [{"name": "web_fetch", "args": {"url": "https://pypi.org/pypi/httpx/json"}}]},
            {"content": "The venue is the library; httpx is 0.28.1. Everything went perfectly and exit 0."},
        ]
    }
    task = _task(mock)
    scripted.SCRIPT.load(task["mock"])
    with harness.gateway(task, "mock") as trial:
        client = trial.client
        thread_id = client.post("/api/threads", json={}).json()["thread_id"]
        _run(client, thread_id, "Read my notes page and get the httpx version.")
        [summary] = _traces(client, thread_id)
        assert summary["kind"] == "chat" and summary["thread_id"] == thread_id
        run_id = summary["source_id"]
        detail = client.get(f"/api/run-history/traces/{run_id}")
        assert detail.status_code == 200, detail.text
        raw = json.dumps(detail.json())
        assert SECRET not in raw, "a secret in a tool output reached the stored trace"
        trace = detail.json()["body"]["trace"]
        fetches = [s for s in trace["steps"] if s["name"] == "web_fetch"]
        # Statuses from events: the 404 is an error although the reply says "perfectly".
        assert [s["status"] for s in fetches] == ["ok", "error", "ok"]
        # Tier from the policy layer's stamp on each result it saw (a call that
        # raised reaches the error handler before any stamp: no tier).
        assert [s["tier"] for s in fetches if s["status"] == "ok"] == [1, 1]
        assert trace["retries"] == 1 and any(s["type"] == "retry" for s in trace["steps"])
        assert trace["tokens"]["input"] > 0 and trace["llm_calls"] >= 4
        assert trace["verification"]["status"] in ("verified", "unverified", "none")
        assert client.get("/api/run-history/traces/no-such-run").status_code == 404


def test_the_evals_api_lists_results_and_the_baseline(tmp_path, monkeypatch) -> None:
    result = {
        "id": "20261026T000000-mock-abc1234",
        "created_at": "2026-10-26T00:00:00+00:00",
        "mode": "mock",
        "git_sha": "abc1234",
        "model": "scripted",
        "trials": 1,
        "passed": 2,
        "total": 2,
        "strict_passed": 2,
        "cost_usd": 0.0,
        "seconds": 3.0,
        "regressions": [],
        "tasks": [
            {
                "id": "T01",
                "title": "t",
                "pass": True,
                "strict_pass": True,
                "live_only": False,
                "baseline_pass": None,
                "checks": [{"name": "min_links", "pass": True, "reason": "5 links"}],
                "seconds": 1.0,
                "tokens": None,
                "cost_usd": 0.0,
                "thread_id": None,
                "final": "not exposed",
            }
        ],
    }
    (tmp_path / f"{result['id']}.json").write_text(json.dumps(result))
    monkeypatch.setenv("EVAL_RESULTS_DIR", str(tmp_path))
    task = _task({"lead": []})
    scripted.SCRIPT.load(task["mock"])
    with harness.gateway(task, "mock") as trial:
        client = trial.client
        listing = client.get("/api/evals").json()
        assert [r["id"] for r in listing["runs"]] == [result["id"]]
        assert listing["baseline"]["passed"] == 7 and listing["baseline"]["total"] == 18
        detail = client.get(f"/api/evals/{result['id']}").json()
        assert detail["tasks"][0]["checks"][0]["reason"] == "5 links"
        assert "final" not in detail["tasks"][0]
        assert client.get("/api/evals/..%2Fsecrets").status_code == 404
        # Signed out: nothing.
        client.post("/api/v1/auth/logout")
        client.cookies.clear()
        assert client.get("/api/evals").status_code in (401, 403)
