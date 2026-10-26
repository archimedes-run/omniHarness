"""Coding jobs (spec 009, Slice 1): tokens, the store's money rules, prices,
the status decision, the shipped rules and OpenCode's managed config.

Each safety rule here has a sabotage recorded in the PR (Article XII): the
test was seen failing for its own reason when the rule was removed.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("OMNI_HARNESS_INTERNAL_AUTH_TOKEN", "unit-test-gateway-secret-0123456789")


# -- tokens -------------------------------------------------------------------


def test_a_token_names_its_job_and_container_and_verifies_in_any_worker():
    from app.gateway.code_jobs import tokens

    tok = tokens.mint(job_id="j1", container="omni-harness-sandbox-aaaa0000", thread_id="t1", ttl_seconds=60)
    claims = tokens.verify(tok)
    assert (claims.job_id, claims.container, claims.thread_id) == ("j1", "omni-harness-sandbox-aaaa0000", "t1")


def test_a_tampered_or_expired_or_foreign_token_is_refused(monkeypatch):
    from app.gateway.code_jobs import tokens

    tok = tokens.mint(job_id="j1", container="c1", thread_id="t1", ttl_seconds=60)
    head, payload, sig = tok.split(".")
    forged = json.dumps({"j": "j1", "c": "c2", "t": "t1", "e": int(time.time()) + 60}, separators=(",", ":"), sort_keys=True).encode()
    import base64

    swapped = f"{head}.{base64.urlsafe_b64encode(forged).decode().rstrip('=')}.{sig}"
    with pytest.raises(tokens.TokenError, match="signature"):
        tokens.verify(swapped)
    with pytest.raises(tokens.TokenError, match="expired"):
        tokens.verify(tokens.mint(job_id="j", container="c", thread_id="t", ttl_seconds=10, now=time.time() - 100))
    with pytest.raises(tokens.TokenError):
        tokens.verify("sk-not-a-job-token")
    # Another gateway's secret: a different key, so its tokens never verify here.
    monkeypatch.setenv("OMNI_HARNESS_INTERNAL_AUTH_TOKEN", "some-other-gateway-secret-000000")
    with pytest.raises(tokens.TokenError, match="signature"):
        tokens.verify(tok)


def test_the_token_is_registered_for_redaction():
    from app.gateway.code_jobs import tokens
    from omniharness.utils.known_secrets import KNOWN_SECRETS

    tok = tokens.mint(job_id="j9", container="c9", thread_id="t9", ttl_seconds=60)
    redacted, hits = KNOWN_SECRETS.redact(f"Authorization: Bearer {tok}")
    assert hits >= 1 and tok not in redacted


# -- store: budget, cap, stop ------------------------------------------------


def _store(tmp_path):
    from app.gateway.code_jobs.store import CodeJobStore

    return CodeJobStore(tmp_path / "jobs.db")


def _reserve(store, job="j", cap=20.0, inp=0.0, per_token=10.0 / 1e6, want=32000, inflight=3, rate=60, container="c"):
    return store.reserve_call(job_id=job, container=container, model="m", monthly_cap_usd=cap, rate_per_minute=rate, max_inflight=inflight, input_cost_usd=inp, output_usd_per_token=per_token, requested_output_tokens=want)


def test_a_call_is_refused_once_the_job_budget_is_spent(tmp_path):
    store = _store(tmp_path)
    store.create(job_id="j", thread_id="t", user_id="u", tool_call_id="c", title="x", project_dir="p", budget_usd=0.10, model="m")
    call, reason, out = _reserve(store)
    assert call and reason is None
    # The reservation is pessimistic: output cut to what $0.10 buys (10k tokens at $10/M).
    assert out == 10_000
    store.settle_call(call, status="ok", usage=(1, 0, 1), cost_usd=0.10)
    assert "budget" in (_reserve(store)[1] or "")


def test_a_reservation_counts_until_it_settles_and_no_usage_charges_the_estimate(tmp_path):
    store = _store(tmp_path)
    store.create(job_id="j", thread_id="t", user_id="u", tool_call_id="c", title="x", project_dir="p", budget_usd=1.0, model="m")
    first, _, out = _reserve(store, inp=0.02)
    assert out == 32_000  # $0.02 + 32k x $10/M = $0.34 reserved
    second, _, _ = _reserve(store, inp=0.02)
    third, _, out3 = _reserve(store, inp=0.02)
    assert 29_990 <= out3 <= 30_000, "the third call gets only what the first two left"
    assert store.settle_call(first, status="ok", usage=None, cost_usd=None) == pytest.approx(0.34), "no usage: the estimate is charged"
    assert store.get("j").spent_usd == pytest.approx(0.34)


def test_concurrent_calls_and_the_rate_are_capped_including_calls_in_flight(tmp_path):
    store = _store(tmp_path)
    store.create(job_id="j", thread_id="t", user_id="u", tool_call_id="c", title="x", project_dir="p", budget_usd=50.0, model="m")
    results = [_reserve(store, want=1000) for _ in range(5)]
    assert [r[0] is not None for r in results] == [True, True, True, False, False]
    assert "at once" in results[3][1]
    store.settle_call(results[0][0], status="ok", usage=(1, 0, 1), cost_usd=0.0)
    assert _reserve(store, want=1000, rate=3)[1].startswith("rate limit"), "in-flight calls count toward the rate"


def test_a_call_is_refused_once_the_month_cap_is_reached(tmp_path):
    store = _store(tmp_path)
    store.create(job_id="a", thread_id="t", user_id="u", tool_call_id="c1", title="x", project_dir="p", budget_usd=5, model="m")
    store.record_call(job_id="a", container="c", model="m", status="ok", cost_usd=2.0)
    store.finish("a", status="verified", reason=None, result={})
    store.create(job_id="b", thread_id="t", user_id="u", tool_call_id="c2", title="x", project_dir="p", budget_usd=5, model="m")
    assert "cap" in (_reserve(store, job="b", cap=2.0)[1] or "")
    assert _reserve(store, job="b", cap=2.5)[1] is None


def test_a_stopped_or_finished_job_gets_no_more_model_calls(tmp_path):
    store = _store(tmp_path)
    store.create(job_id="j", thread_id="t", user_id="u", tool_call_id="c", title="x", project_dir="p", budget_usd=1, model="m")
    assert store.request_stop("j")
    assert _reserve(store)[1] == "the job is not running"
    store.create(job_id="k", thread_id="t", user_id="u", tool_call_id="d", title="x", project_dir="p", budget_usd=1, model="m")
    assert store.finish("k", status="unverified", reason="r", result={})
    assert not store.finish("k", status="verified", reason=None, result={}), "a terminal status is set once"
    assert _reserve(store, job="k")[1] == "the job is not running"


def test_month_spend_is_per_user_and_a_deleted_thread_forgets_its_jobs(tmp_path):
    store = _store(tmp_path)
    store.create(job_id="a", thread_id="t1", user_id="alice", tool_call_id="c", title="x", project_dir="p", budget_usd=5, model="m")
    store.create(job_id="b", thread_id="t2", user_id="bob", tool_call_id="c", title="x", project_dir="p", budget_usd=5, model="m")
    store.record_call(job_id="a", container="c", model="m", status="ok", cost_usd=1.0)
    store.record_call(job_id="b", container="c", model="m", status="ok", cost_usd=2.0)
    assert store.month_spend(user_id="alice") == pytest.approx(1.0) and store.month_spend() == pytest.approx(3.0)
    store.add_step("a", "message", {"text": "secret plan"})
    assert store.delete_thread("t1") == ["a"]
    assert store.get("a") is None and store.steps("a") == []
    assert store.month_spend() == pytest.approx(3.0), "spent money still counts toward the cap"


def test_a_job_whose_runner_stopped_beating_is_reported_interrupted(tmp_path):
    store = _store(tmp_path)
    store.create(job_id="old", thread_id="t", user_id="u", tool_call_id="c", title="x", project_dir="p", budget_usd=1, model="m")
    store.create(job_id="live", thread_id="t2", user_id="u", tool_call_id="c", title="x", project_dir="p", budget_usd=1, model="m")
    store._conn().execute("UPDATE jobs SET updated_at = ? WHERE id = 'old'", (time.time() - 600,))
    assert store.reap_stale() == ["old"]
    assert store.get("old").status == "blocked" and "restarted" in store.get("old").reason
    assert store.get("live").status == "running", "another worker's live job is left alone"


# -- prices --------------------------------------------------------------------


def test_prices_cover_dated_ids_and_unknown_models_cost_the_most():
    from app.gateway.code_jobs.pricing import FALLBACK, cost_usd, price_for

    assert price_for("gpt-5-mini-2025-08-07").input == 0.25
    assert price_for("gpt-5").output == 10.0
    assert price_for("some-new-model") == FALLBACK
    assert cost_usd("gpt-5", input_tokens=1_000_000, cached_tokens=0, output_tokens=0) == pytest.approx(1.25)
    assert cost_usd("gpt-5", input_tokens=1_000_000, cached_tokens=1_000_000, output_tokens=0) == pytest.approx(0.125)


# -- the status decision -----------------------------------------------------


def test_verified_needs_the_systems_own_check_and_every_expected_file():
    from app.gateway.code_jobs.runner import decide_status

    ok = {"command": "npm run build", "exit_code": 0}
    present = [{"path": "dist/index.html", "exists": True}]
    assert decide_status(stopped=False, blocked=None, worker_error=None, verify=ok, expected=present) == ("verified", None)
    # No check run: never verified, whatever the worker said.
    assert decide_status(stopped=False, blocked=None, worker_error=None, verify=None, expected=present)[0] == "unverified"
    assert decide_status(stopped=False, blocked=None, worker_error=None, verify=None, expected=[])[0] == "unverified"
    assert decide_status(stopped=False, blocked=None, worker_error=None, verify={"command": "npm run build", "exit_code": 1}, expected=present)[0] == "failed"
    assert decide_status(stopped=False, blocked=None, worker_error=None, verify=ok, expected=[{"path": "dist/index.html", "exists": False}]) == ("failed", "missing: dist/index.html")
    assert decide_status(stopped=False, blocked=None, worker_error=None, verify={"command": "x", "exit_code": None, "timed_out": True, "limit_s": 600}, expected=[])[0] == "failed"
    assert decide_status(stopped=True, blocked=None, worker_error=None, verify=ok, expected=present)[0] == "stopped"
    assert decide_status(stopped=False, blocked="budget", worker_error=None, verify=ok, expected=present)[0] == "blocked"


def test_the_report_never_calls_an_unverified_job_done(tmp_path):
    from app.gateway.code_jobs.runner import CodeJobManager

    store = _store(tmp_path)
    store.create(job_id="j", thread_id="t", user_id="u", tool_call_id="c", title="x", project_dir="app", budget_usd=1, model="m")
    store.finish("j", status="unverified", reason="no verification command", result={"worker": {"summary": "Done! Everything built and all tests passed."}})
    manager = CodeJobManager(store=store, settings=lambda: None, unavailable=lambda: None, sandbox_for=lambda t, u: None, relay_dir=tmp_path)
    report = manager.report("j")
    assert "STATUS UNVERIFIED" in report and "Do NOT say done" in report
    assert "untrusted data" in report  # the worker's "Done!" is quoted as its words only


# -- the shipped rules and config (Article XIV) --------------------------------


def test_the_rules_baked_into_the_image_are_the_tracked_rules():
    from omniharness.code_jobs import rules_text

    assert (ROOT / "docker/sandbox/opencode/AGENTS.md").read_text() == rules_text()
    text = rules_text()
    for rule in ("/mnt/user-data", "non-interactive", "Never print", "Build before you claim", "Never claim an outcome"):
        assert rule.lower() in text.lower(), rule


def test_the_managed_opencode_config_has_one_provider_no_key_and_never_prompts():
    cfg = json.loads((ROOT / "docker/sandbox/opencode/opencode.json").read_text())
    assert cfg["enabled_providers"] == ["omni"] and list(cfg["provider"]) == ["omni"]
    opts = cfg["provider"]["omni"]["options"]
    assert opts == {"baseURL": "{env:OMNI_LLM_BASE_URL}", "apiKey": "{env:OMNI_LLM_TOKEN}"}, "no literal key or URL"
    assert cfg["share"] == "disabled" and cfg["autoupdate"] is False
    perm = cfg["permission"]
    assert all(perm[k] == "deny" for k in ("webfetch", "websearch", "question"))
    # Outside the workspace only the thread's own folders (uploads, outputs).
    assert perm["external_directory"] == {"*": "deny", "/mnt/user-data/*": "allow"}
    assert "ask" not in perm.values(), "D6: nothing may prompt"
    assert cfg["instructions"] == ["/etc/opencode/AGENTS.md"]


def test_the_sandbox_image_pins_opencode_by_checksum_and_drops_sudo():
    dockerfile = (ROOT / "docker/sandbox/Dockerfile").read_text()
    assert "ARG OPENCODE_VERSION=1.19.3" in dockerfile
    assert re.search(r"OPENCODE_SHA256_ARM64=[0-9a-f]{64}", dockerfile) and re.search(r"OPENCODE_SHA256_AMD64=[0-9a-f]{64}", dockerfile)
    assert "sha256sum -c -" in dockerfile
    assert "/^# Add user to sudoers/,/^fi$/d" in dockerfile and "-perm /6000" in dockerfile
    assert "COPY --chown=root:root --chmod=0644 opencode/opencode.json /etc/opencode/opencode.json" in dockerfile


def test_opencode_runs_with_a_clean_environment_in_its_own_process_group(tmp_path):
    from app.gateway.code_jobs.runner import CodeJobManager, Settings
    from omniharness.code_jobs import CodeJobBrief

    manager = CodeJobManager(store=_store(tmp_path), settings=lambda: None, unavailable=lambda: None, sandbox_for=lambda t, u: None, relay_dir=tmp_path)
    settings = Settings(proxy_url="http://172.20.0.2:8790/v1", proxy_host="172.20.0.2", budget_usd=1, monthly_cap_usd=20, wall_seconds=600, verify_timeout_seconds=600)
    script = manager._run_script("job1", "/tmp/omni-jobs/job1", CodeJobBrief(goal="g", project_dir="p"), settings)
    assert "exec setsid env -i " in script, "own process group, empty environment"
    assert "SANDBOX_API_KEY" not in script, "the sandbox's API key never reaches the worker"
    assert 'OMNI_LLM_TOKEN="$TOKEN"' in script and "rm -f /tmp/omni-jobs/job1/token" in script
    assert "NO_PROXY=localhost,127.0.0.1,172.20.0.2" in script
    for flag in ("OPENCODE_DISABLE_AUTOUPDATE=1", "OPENCODE_DISABLE_MODELS_FETCH=1", "OPENCODE_DISABLE_DEFAULT_PLUGINS=1", "OPENCODE_DISABLE_CLAUDE_CODE=1"):
        assert flag in script
    assert "< /dev/null" in script


def test_code_job_is_tier_2_with_the_sandbox_floor():
    import yaml

    rules = yaml.safe_load((ROOT / "backend/app/policy/default_rules.yaml").read_text())["policy"]["rules"]
    rule = next(r for r in rules if r["pattern"] == "code_job")
    assert rule["tier"] == 2 and rule["reversible"] is False
    assert "reads_private" not in rule, "its result is the person's workspace: a private read"
    from app.policy import runtime_floors
    from app.policy.models import Tier

    assert runtime_floors.runtime_floor("code_job") in (None, Tier.TIER_3)


def test_the_brief_arguments_cannot_escape_the_workspace():
    from omniharness.tools.builtins.code_job_tool import normalize_project_dir, normalize_relative

    assert normalize_project_dir("/mnt/user-data/workspace/counter-app") == "counter-app"
    assert normalize_relative("./dist", "publish_dir") == "dist"
    for bad in ("../etc", "/etc", "a/../../b", "", "a b"):
        with pytest.raises(ValueError):
            normalize_project_dir(bad)
    for bad in ("../x", "/abs", "a/../b"):
        with pytest.raises(ValueError):
            normalize_relative(bad, "expect_files")


# -- offered only where it can run (FR-011) ------------------------------------


def test_code_job_is_offered_only_when_the_controller_says_it_can_run(monkeypatch):
    from omniharness.code_jobs import reset_code_job_controller, set_code_job_controller
    from omniharness.tools.tools import get_available_tools

    class Controller:
        reason: str | None = "they need the container sandbox"

        def unavailable_reason(self):
            return self.reason

        async def run(self, **_):  # pragma: no cover - not called here
            raise AssertionError

    controller = Controller()
    set_code_job_controller(controller)
    try:
        names = [t.name for t in get_available_tools(include_mcp=False)]
        assert "code_job" not in names, "offered without the container sandbox"
        controller.reason = None
        names = [t.name for t in get_available_tools(include_mcp=False)]
        assert "code_job" in names
    finally:
        reset_code_job_controller()
    assert "code_job" not in [t.name for t in get_available_tools(include_mcp=False)], "offered with no controller (daemon profile)"


def test_without_a_controller_the_tool_says_honestly_that_it_cannot_run():
    import asyncio
    from types import SimpleNamespace

    from omniharness.code_jobs import reset_code_job_controller
    from omniharness.tools.builtins.code_job_tool import code_job_tool

    reset_code_job_controller()
    runtime = SimpleNamespace(context={"thread_id": "t"}, config={}, state={})
    command = asyncio.run(code_job_tool.coroutine(runtime=runtime, goal="g", project_dir="p", tool_call_id="x"))
    text = command.update["messages"][0].content
    assert "need the container sandbox" in text and "do not pretend" in text


def test_the_lead_is_told_to_run_coding_jobs_only_where_they_can_run():
    from omniharness.agents.lead_agent.prompt import coding_jobs_section
    from omniharness.code_jobs import reset_code_job_controller, set_code_job_controller

    class Controller:
        reason: str | None = None

        def unavailable_reason(self):
            return self.reason

        async def run(self, **_):  # pragma: no cover
            raise AssertionError

    controller = Controller()
    set_code_job_controller(controller)
    try:
        section = coding_jobs_section()
        assert "call `code_job` right away" in section and "do not ask the person to choose" in section
        assert "Only a verified job may be called done" in section
        controller.reason = "no sandbox"
        assert coding_jobs_section() == ""
    finally:
        reset_code_job_controller()
    assert coding_jobs_section() == ""
