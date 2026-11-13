"""The eval harness's own limits and environment (owner rules, 2026-11-13).

* A trial stops with a reason instead of waiting: on the task's wall clock
  ("timeout"), when its runs write nothing for the stall window ("stalled"),
  and when the run waits on a question nobody will answer ("paused").
* The cost of a trial is recorded (it used to show "-").
* Real mode fetches through the fetch egress proxy the harness starts, which
  is always removed again; and only the model's key reaches the trial.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from omni_eval import fetch_egress, harness  # noqa: E402


def _task(task_id: str, lead: list[dict], *, seconds: float = 60, checks: list | None = None) -> dict:
    return {"id": task_id, "title": task_id, "source": "harness test", "mode": "pro", "prompt": "Find a museum.", "tools": [], "confirm": "none", "budget": {"seconds": seconds}, "checks": checks or ["no_menu"], "mock": {"lead": lead}}


def _reason(result: dict) -> str:
    return next((c["reason"] for c in result["checks"] if c["name"] == "run_ok"), "")


def test_a_run_past_the_tasks_wall_clock_is_stopped_as_a_timeout() -> None:
    task = _task("H-TIMEOUT", [{"sleep": 60, "content": "Too late."}], seconds=3)
    started = time.time()
    result = harness.run_trial(task, "mock")
    assert _reason(result).startswith("timeout"), result["checks"]
    assert result["stopped"].startswith("timeout")
    assert not result["pass"]
    assert time.time() - started < 30, "the harness waited past the task's limit"


def test_a_run_with_no_activity_is_stopped_as_stalled(monkeypatch) -> None:
    monkeypatch.setenv("EVAL_STALL_SECONDS", "2")
    task = _task("H-STALL", [{"sleep": 60, "content": "Too late."}], seconds=50)
    started = time.time()
    result = harness.run_trial(task, "mock")
    assert _reason(result).startswith("stalled: no activity"), result["checks"]
    assert time.time() - started < 30


def test_a_question_to_the_person_stops_the_trial_with_that_reason() -> None:
    # Asked before any work: it goes to the person, and nobody will answer.
    task = _task("H-ASK", [{"tool_calls": [{"name": "ask_clarification", "args": {"question": "Which city?", "clarification_type": "missing_info"}}]}])
    result = harness.run_trial(task, "mock")
    assert _reason(result) == "paused: waiting on clarification", result["checks"]


def test_a_task_may_declare_that_it_ends_on_a_question() -> None:
    task = {**_task("H-ASK-OK", [{"tool_calls": [{"name": "ask_clarification", "args": {"question": "Which city?", "clarification_type": "missing_info"}}]}]), "allow_pause": True}
    result = harness.run_trial(task, "mock")
    assert not _reason(result), result["checks"]


def test_the_limit_is_the_tasks_budget_capped_at_600_seconds() -> None:
    assert harness.task_seconds({}) == 300
    assert harness.task_seconds({"budget": {"seconds": 120}}) == 120
    assert harness.task_seconds({"budget": {"seconds": 900}}) == 600


def test_a_trial_records_its_cost_from_the_run_trace() -> None:
    task = _task("H-COST", [{"model": "gpt-5", "content": "The [museum](https://philamuseum.org/) is open on Saturdays.", "usage": {"input_tokens": 10000, "output_tokens": 1000, "total_tokens": 11000}}])
    result = harness.run_trial(task, "mock")
    # 10k input at $1.25/M + 1k output at $10/M = $0.0225
    assert result["cost_source"] == "trace"
    assert result["cost_usd"] == pytest.approx(0.0225, abs=1e-6)
    assert result["tokens"] == {"input": 10000, "output": 1000}


def test_without_a_trace_the_cost_comes_from_the_run_totals() -> None:
    client = SimpleNamespace(get=lambda path: SimpleNamespace(json=lambda: {"total_input_tokens": 20000, "total_output_tokens": 2000}))
    tokens, cost, source = harness.trial_cost(client, "t", [], mode="real", model_config=[{"model": "gpt-5"}])
    assert tokens == {"input": 20000, "output": 2000}
    assert cost == pytest.approx(0.045, abs=1e-6)
    assert source == "run totals at gpt-5 list price"


# ------------------------------------------------------------ environment


def test_only_the_model_key_reaches_a_real_trial() -> None:
    config = yaml.safe_load((harness.REPO / "config.example.yaml").read_text())
    needed = harness.needed_keys(config["models"], config["tools"])
    assert needed == {"OPENAI_API_KEY"}
    parent = {"PATH": "/bin", "JINA_API_KEY": "x", "GITHUB_TOKEN": "x", "OMNI_HARNESS_HOME": "/h", "OPENAI_API_KEY": "parent"}
    env, passed = harness.trial_process_env(parent, {"OPENAI_API_KEY": "file", "JINA_API_KEY": "file", "TAVILY_API_KEY": "file", "OPENAI_BASE_URL": "http://x"}, needed)
    assert env["OPENAI_API_KEY"] == "file"
    assert env["OPENAI_BASE_URL"] == "http://x"
    assert env["PATH"] == "/bin"
    for name in ("JINA_API_KEY", "GITHUB_TOKEN", "TAVILY_API_KEY", "OMNI_HARNESS_HOME"):
        assert name not in env
    assert passed == ["OPENAI_API_KEY"]


def test_a_jina_key_is_passed_only_when_the_config_selects_that_reader() -> None:
    assert "JINA_API_KEY" in harness.needed_keys([], [{"name": "web_fetch", "provider": "jina"}])
    assert "JINA_API_KEY" not in harness.needed_keys([], [{"name": "web_fetch", "use": "omniharness.community.builtin_fetch.tools:web_fetch_tool"}])


def test_a_real_trial_never_falls_back_to_another_reader(tmp_path) -> None:
    path = harness.build_config(tmp_path, {"id": "X", "tools": []}, "real", model_config=[{"name": "default", "use": "langchain_openai:ChatOpenAI", "model": "gpt-5"}])
    fetch = [t for t in yaml.safe_load(path.read_text())["tools"] if t["name"] == "web_fetch"]
    assert fetch and all(t.get("jina_fallback") is False for t in fetch)


def test_the_eval_proxy_is_the_compose_fetch_egress_service() -> None:
    compose = yaml.safe_load((harness.REPO / "docker" / "docker-compose.yaml").read_text())
    service = compose["services"]["fetch-egress"]
    assert service["image"] == fetch_egress.IMAGE
    assert service["entrypoint"] == ["/bin/sh", "/opt/fetch/entrypoint.sh"]
    assert "./fetch-egress:/opt/fetch:ro" in service["volumes"]


class _FakeDocker:
    """Records docker commands; `image inspect` succeeds."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv[1:])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def ran(self, *prefix: str) -> bool:
        return any(call[: len(prefix)] == list(prefix) for call in self.calls)


def _removed(docker: _FakeDocker) -> tuple[bool, bool]:
    name = next(call[call.index("--name") + 1] for call in docker.calls if call[0] == "run")
    return docker.ran("rm", "-f", name), docker.ran("network", "rm", name)


def test_the_proxy_container_is_removed_after_the_run() -> None:
    docker = _FakeDocker()
    with fetch_egress.proxy(harness.REPO, runner=docker, probe=lambda url, timeout: None) as url:
        assert url.startswith("http://127.0.0.1:")
        run = next(call for call in docker.calls if call[0] == "run")
        assert run[run.index("-p") + 1].startswith("127.0.0.1:"), "published beyond loopback"
    assert _removed(docker) == (True, True)


@pytest.mark.parametrize("error", [RuntimeError("a trial crashed"), KeyboardInterrupt()])
def test_the_proxy_container_is_removed_when_the_run_fails_or_is_interrupted(error) -> None:
    docker = _FakeDocker()
    with pytest.raises(type(error)), fetch_egress.proxy(harness.REPO, runner=docker, probe=lambda url, timeout: None):
        raise error
    assert _removed(docker) == (True, True)


def test_real_mode_refuses_when_the_proxy_does_not_fetch() -> None:
    docker = _FakeDocker()
    with pytest.raises(fetch_egress.EgressUnavailable, match="did not fetch"), fetch_egress.proxy(harness.REPO, runner=docker, probe=lambda url, timeout: "HTTP 403"):
        pass
    assert _removed(docker) == (True, True)


def test_real_mode_refuses_without_the_local_image() -> None:
    def runner(argv, **kwargs):
        return SimpleNamespace(returncode=1 if argv[1:3] == ["image", "inspect"] else 0, stdout="", stderr="")

    with pytest.raises(fetch_egress.EgressUnavailable, match="not built locally"), fetch_egress.proxy(harness.REPO, runner=runner):
        pass


def test_make_eval_real_refuses_to_run_without_the_proxy(monkeypatch, capsys) -> None:
    from omni_eval import run

    def unavailable(repo):
        raise fetch_egress.EgressUnavailable("no docker")

    monkeypatch.setattr(run.fetch_egress, "proxy", unavailable)
    monkeypatch.setattr(run.harness, "run_trial", lambda *a, **k: pytest.fail("a trial ran without the fetch proxy"))
    monkeypatch.setenv("EVAL_MODEL", "real")
    monkeypatch.setenv("EVAL_TASKS", "T09")
    monkeypatch.delenv("EVAL_ENV_FILE", raising=False)
    assert run.main() == 4
    assert "fetch egress proxy is not available" in capsys.readouterr().err
