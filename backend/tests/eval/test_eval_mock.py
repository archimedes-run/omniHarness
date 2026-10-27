"""`make eval` in mock mode, as part of the backend suite (spec 009 FR-070, SC-010).

Every task (18+ T-tasks with their scripted turns, and the mock-only harness
tasks) runs in a fresh, isolated gateway through `create_app()` with the
scripted model and recorded web results: no network, no secrets. A task
passes only if every check passes, the behaviour checks included.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from omni_eval import harness  # noqa: E402

TASKS = harness.load_tasks()


@pytest.mark.parametrize("task", TASKS, ids=[t["id"] for t in TASKS])
def test_task_passes_in_mock_mode(task) -> None:
    result = harness.run_trial(task, "mock")
    failed = [f"{c['name']}: {c['reason']}" for c in result["checks"] if not c["pass"]]
    assert not failed, f"{task['id']} failed: {failed}"


def test_the_suite_has_the_specified_tasks() -> None:
    """FR-075: the 18 spec tasks (plus the owner's dogfooding ones) and the
    five mock-only harness tasks of FR-073."""
    ids = {t["id"] for t in TASKS}
    assert {f"T{n:02d}" for n in range(1, 19)} <= ids
    assert {"M-RETRY", "M-SUMMARY", "M-DECLINE", "M-MIXED", "M-VERIFY"} <= ids
    for task in TASKS:
        assert task.get("checks"), task["id"]
        assert task.get("mock"), f"{task['id']} has no mock script"
        assert task.get("source"), f"{task['id']} does not say which real use it comes from"
