"""SC-014 — a plan stated by one worker, confirmed through another, executed once.

**PRODUCTION SHAPE (Article XI).** The structural difference this defends
against: every other policy test runs in one process, where the claim, the store
and the audit log are trivially consistent. Production runs `uvicorn --workers
N` behind one socket, and the kernel decides which worker answers. A plan will
usually be stated by one worker and confirmed through another.

**WHY THE STORAGE-LAYER PROOF IS NOT ENOUGH.** `test_pending_actions.py` already
shows `claim()` admits exactly one of four processes. That is the claim working.
It is not the FLOW working — the flow also needs the confirmation to reach the
pending action across workers, the recognition to find it, the execution to
happen once, and the audit to name who did it. The gap between "the primitive is
correct" and "the path that uses it works" has hidden something every time it
has appeared in this project.

**THIS ALSO EXERCISES THE SHARED INTERNAL-AUTH SECRET UNDER CONCURRENCY** for
the first time. Tokens used to be minted per process; a confirmation landing on
a worker other than the one that minted it would 401. The `/confirm` endpoint
checks internal auth explicitly and reports the rejection separately from a
policy decision, so an auth failure cannot be misread as a claim failure.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
COMPOSE = REPO / "docker" / "docker-compose.yaml"
PORT = 8877

RULES = """
policy:
  rules:
    - pattern: "calendar_read"
      tier: 1
    - pattern: "calendar_decline"
      tier: 3
  confirmation:
    expires_after_seconds: 3600
    threshold_targets: 3
"""


def gateway_worker_count() -> int:
    """The count production runs, read from the compose file — not a literal.

    A hardcoded number keeps passing after someone raises the real one, which is
    exactly when this test stops being true.
    """
    if not COMPOSE.exists():  # pragma: no cover
        pytest.skip("compose file not found; cannot determine the real worker count")
    text = COMPOSE.read_text()
    match = re.search(r"--workers\s+\$\{GATEWAY_WORKERS:-(\d+)\}", text) or re.search(r"--workers\s+(\d+)", text)
    if not match:  # pragma: no cover
        pytest.skip("no --workers directive in the compose file")
    return int(os.environ.get("GATEWAY_WORKERS", match.group(1)))


@pytest.fixture(scope="module")
def gateway(tmp_path_factory):
    """A real multi-worker uvicorn, not a TestClient.

    TestClient runs in-process and would make every assertion here vacuous.
    """
    workers = gateway_worker_count()
    if workers < 2:  # pragma: no cover
        pytest.skip("production runs a single worker; cross-worker confirmation is moot")

    state = tmp_path_factory.mktemp("policy-multiworker")
    rules = state / "policy.yaml"
    rules.write_text(RULES)

    # The app module is copied next to the state dir and served with
    # --app-dir. `tests/` has no __init__.py (repo convention), so
    # `tests.policy_multiworker._policy_app` is not an importable path — and
    # adding one would change the convention for every other suite. The source
    # stays checked in for review; only its location at run time moves.
    app_module = state / "_policy_app.py"
    app_module.write_text((Path(__file__).parent / "_policy_app.py").read_text())

    env = {
        **os.environ,
        "PYTHONPATH": str(BACKEND),
        "POLICY_TEST_STATE_DIR": str(state),
        "POLICY_TEST_RULES": str(rules),
        # The shared secret. Without it each worker mints its own and the
        # confirmation 401s whenever it lands elsewhere.
        "OMNI_HARNESS_INTERNAL_AUTH_TOKEN": "cross-worker-test-token",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "_policy_app:app", "--app-dir", str(state), "--host", "127.0.0.1", "--port", str(PORT), "--workers", str(workers)],
        cwd=str(BACKEND),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    deadline = time.monotonic() + 90
    served = set()
    while time.monotonic() < deadline:
        try:
            for _ in range(workers * 6):
                served.add(httpx.get(f"http://127.0.0.1:{PORT}/health", timeout=2).json()["pid"])
            if len(served) >= 2:
                break
        except Exception:
            time.sleep(1)
    else:  # pragma: no cover
        proc.send_signal(signal.SIGTERM)
        pytest.fail(f"gateway did not come up with several workers; saw pids {served}")

    def worker_pids() -> set[int]:
        """The worker set from the process tree, read FRESH on every call.

        THIS IS NOT `served`. `served` is a SAMPLE — whichever workers happened
        to answer a /health probe before the loop hit its "at least 2 distinct"
        exit. It is the right evidence for "several workers really are serving"
        and the WRONG evidence for "pid X is a worker": an unsampled worker is
        still a worker. Asserting a claimant's membership in `served` failed in
        CI against a claimant that was a perfectly real worker, and passed twice
        before that only because round-robin happened to cover it. The kernel
        decides who answers a socket; a test must not encode a guess about that.

        Read fresh rather than snapshotted at setup because the tree is only
        complete once every worker has forked, and this fixture returns as soon
        as TWO are serving. A snapshot taken then can undercount — an early
        probe here saw one child where four were coming.

        The resource_tracker exclusion is MEASURED, not assumed. Classifying
        each child of the master by command line gave, at workers=4:
            RESOURCE_TRACKER x1, SPAWN_MAIN x4
        Excluding the tracker rather than matching `spawn_main` keeps this true
        under fork (Linux), where workers inherit the master's command line and
        no tracker is started at all.
        """
        listed = subprocess.run(["pgrep", "-P", str(proc.pid)], capture_output=True, text=True)
        found = set()
        for entry in listed.stdout.split():
            if not entry.strip():
                continue
            cmd = subprocess.run(["ps", "-ww", "-o", "command=", "-p", entry], capture_output=True, text=True).stdout
            if "resource_tracker" not in cmd:
                found.add(int(entry))
        return found

    yield {
        "state": state,
        "workers": workers,
        "worker_pids": worker_pids,
        "served": served,
        "token": env["OMNI_HARNESS_INTERNAL_AUTH_TOKEN"],
    }

    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:  # pragma: no cover
        proc.kill()


def _headers(gateway):
    from app.gateway.internal_auth import INTERNAL_AUTH_HEADER_NAME

    return {INTERNAL_AUTH_HEADER_NAME: gateway["token"]}


def _executions(gateway) -> list[str]:
    directory = gateway["state"] / "executions"
    return sorted(p.name for p in directory.glob("*")) if directory.exists() else []


def _audit(gateway) -> list[dict]:
    path = gateway["state"] / "audit.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------


def test_the_gateway_really_is_running_several_workers(gateway):
    """The premise. Without it every assertion below is about one process.

    Both halves are load-bearing. `served` proves workers OBSERVED answering
    requests — forked children that never accept a connection would satisfy the
    process tree and not the premise. The tree then proves the count is the one
    production runs, which `served` alone cannot show: sampling two distinct
    responders is equally consistent with two workers and with forty.
    """
    assert len(gateway["served"]) >= 2, f"only one worker answered: {gateway['served']}"
    running = gateway["worker_pids"]()
    assert len(running) == gateway["workers"], f"expected {gateway['workers']} workers, the master has {sorted(running)}"
    assert gateway["served"] <= running, f"a worker answered /health but is not a child of the master: served={sorted(gateway['served'])} children={sorted(running)}"


def test_a_plan_stated_on_one_worker_is_confirmable_through_another(gateway):
    """SC-014, end to end.

    Confirmation attempts run CONCURRENTLY so the kernel spreads them: that is
    both how the cross-worker case arises and how a claim race would.
    """
    targets = ["Standup 9am", "Review 2pm"]
    stated = httpx.post(
        f"http://127.0.0.1:{PORT}/state",
        json={"tool": "calendar_decline", "args": {"targets": targets}},
        headers=_headers(gateway),
        timeout=30,
    ).json()

    assert stated["pending"], "no pending action was recorded"
    assert not _executions(gateway), "nothing may run before confirmation"
    stating_worker = stated["pid"]
    action_id = stated["pending"][0]

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        replies = [
            pool.submit(
                lambda: httpx.post(
                    f"http://127.0.0.1:{PORT}/confirm",
                    json={"reply": f"yes {action_id}"},
                    headers=_headers(gateway),
                    timeout=30,
                ).json()
            )
            for _ in range(8)
        ]
        results = [future.result() for future in replies]

    # Internal auth must not be the thing that failed — check it first, because
    # a 401 here would otherwise read as a claim failure.
    auth_failures = [r for r in results if r.get("error") == "internal auth rejected"]
    assert not auth_failures, f"{len(auth_failures)} confirmations were rejected by internal auth. The token is per-worker again, and nothing about the claim logic can be concluded from this run."

    executed = [r for r in results if r.get("executed")]
    answering_workers = {r["pid"] for r in results}

    assert len(executed) == 1, f"{len(executed)} of 8 confirmations executed; exactly 1 must"
    assert len(_executions(gateway)) == 1, f"the action ran {len(_executions(gateway))} times on disk"
    assert answering_workers - {stating_worker}, "every confirmation landed on the worker that stated the plan; the cross-worker case was not exercised"


def test_the_audit_entry_names_the_worker_that_claimed_it(gateway):
    """Not merely that it was audited — WHO did it.

    A reviewer asking "which process acted, and on whose authorisation" needs
    both, and the claimant is the only evidence that the atomic claim was what
    admitted this execution rather than a race that happened to resolve.
    """
    entries = _audit(gateway)

    assert len(entries) == 1, f"expected exactly 1 audit entry, got {len(entries)}"
    entry = entries[0]

    assert entry["outcome"] == "executed"
    assert entry["actor"] == "default"
    assert entry["authorised_by"], "the audit entry does not say which worker claimed the action"
    assert entry["authorised_by"].startswith("worker-")
    claimant_pid = int(entry["authorised_by"].split("-")[1])
    running = gateway["worker_pids"]()
    assert claimant_pid in running, f"claimant {claimant_pid} is not one of the running workers {sorted(running)}"
    assert entry["targets"] == ["Standup 9am", "Review 2pm"]
    assert "Standup 9am" in entry["plan_as_stated"]


def test_a_second_confirmation_after_execution_does_nothing(gateway):
    """The action is resolved; re-confirming must not run it again."""
    before = len(_executions(gateway))

    result = httpx.post(
        f"http://127.0.0.1:{PORT}/confirm",
        json={"reply": "yes"},
        headers=_headers(gateway),
        timeout=30,
    ).json()

    assert not result.get("executed")
    assert len(_executions(gateway)) == before
    assert len(_audit(gateway)) == 1, "a second audit entry appeared for one authorisation"


# ---------------------------------------------------------------------------
# FR-009 — the scope threshold, against a RUNNING SERVER at the production
# worker count. Unit tests already cover the branch; this asserts the rule
# survives the whole path — HTTP, a different process, the durable store, the
# real config file — because that is where a rule enforced in one route and not
# another would show up.
# ---------------------------------------------------------------------------


def test_the_threshold_refuses_a_bare_yes_and_accepts_the_count(gateway):
    """Four targets against a threshold of three, over HTTP, cross-process.

    Both halves in one test on purpose: the second confirmation succeeding is
    what proves the first refusal did NOT consume the action. A separate test
    would have to re-state the plan, and would then be asserting about a
    different action than the one it refused.
    """
    stated = httpx.post(
        f"http://127.0.0.1:{PORT}/state",
        json={"tool": "calendar_decline", "args": {"targets": ["A", "B", "C", "D"]}},
        timeout=10,
    ).json()
    assert stated["pending"], "no action was recorded to confirm"

    refused = httpx.post(
        f"http://127.0.0.1:{PORT}/confirm",
        json={"reply": "yes"},
        headers=_headers(gateway),
        timeout=10,
    ).json()
    assert refused["executed"] is False
    assert refused["verdict"] == "threshold_not_met", refused
    assert "4" in refused["reason"], "the user is not told what to type"

    accepted = httpx.post(
        f"http://127.0.0.1:{PORT}/confirm",
        json={"reply": "yes 4"},
        headers=_headers(gateway),
        timeout=10,
    ).json()
    assert accepted["executed"] is True, accepted
    assert accepted["claimant"].startswith("worker-")


def test_below_the_threshold_a_bare_yes_still_confirms(gateway):
    """The gate must not make ordinary confirmations harder. Two targets
    against a threshold of three: 'yes' is enough, as it always was."""
    httpx.post(
        f"http://127.0.0.1:{PORT}/state",
        json={"tool": "calendar_decline", "args": {"targets": ["A", "B"]}},
        timeout=10,
    )
    done = httpx.post(
        f"http://127.0.0.1:{PORT}/confirm",
        json={"reply": "yes"},
        headers=_headers(gateway),
        timeout=10,
    ).json()
    assert done["executed"] is True, done
