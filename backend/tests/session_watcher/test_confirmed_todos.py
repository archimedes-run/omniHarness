"""Native todo lists change only on a confirmed tool result (Feature 005 FR-031).

The reference implementation (sodiumsun/agenttrail) applied TodoWrite and
Codex update_plan lists at call time; a failed or interrupted update then
showed as the agent's plan. These cover Claude's three tools through the real
adapter.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from session_watcher.adapters.base import ToolCall, ToolResult
from session_watcher.adapters.claude_code import ClaudeCodeAdapter
from session_watcher.record_source import RecordSource
from session_watcher.todos import ConfirmedActivity

T0 = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
NOW = T0 + timedelta(minutes=30)


def _ts(m: float) -> str:
    return (T0 + timedelta(minutes=m)).isoformat().replace("+00:00", "Z")


def call(m: float, cid: str, name: str, args: dict, *, sidechain: bool = False) -> dict:
    return {
        "type": "assistant",
        "sessionId": "s1",
        "timestamp": _ts(m),
        "cwd": "/w/repo",
        "isSidechain": sidechain,
        "message": {"role": "assistant", "stop_reason": "tool_use", "content": [{"type": "tool_use", "id": cid, "name": name, "input": args}]},
    }


def result(m: float, cid: str, text: str = "ok", *, error: bool = False, structured: dict | None = None) -> dict:
    rec = {"type": "user", "sessionId": "s1", "timestamp": _ts(m), "cwd": "/w/repo", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": cid, "content": text, **({"is_error": True} if error else {})}]}}
    if structured is not None:
        rec["toolUseResult"] = structured
    return rec


def session(tmp_path: Path, records: list[dict]):
    folder = tmp_path / "-w-repo"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "s1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    refs = ClaudeCodeAdapter(RecordSource(root=tmp_path)).discover(timedelta(hours=24), now=NOW)
    return refs[0]


def test_a_todowrite_that_errored_leaves_the_last_confirmed_list(tmp_path) -> None:
    ref = session(
        tmp_path,
        [
            call(1, "a", "TodoWrite", {"todos": [{"content": "Plan", "status": "in_progress", "activeForm": "Planning"}]}),
            result(1.1, "a"),
            call(2, "b", "TodoWrite", {"todos": [{"content": "Plan", "status": "completed", "activeForm": "x"}]}),
            result(2.1, "b", "<tool_use_error>nope</tool_use_error>", error=True),
        ],
    )
    assert ref.todos == [("Plan", "in_progress")]


def test_task_create_by_receipt_then_update_by_id(tmp_path) -> None:
    ref = session(
        tmp_path,
        [
            call(1, "a", "TaskCreate", {"subject": "Write the parser", "description": "LONG PRIVATE DESCRIPTION", "activeForm": "Writing"}),
            result(1.1, "a", "Task #1 created successfully: Write the parser"),
            call(2, "b", "TaskCreate", {"subject": "Ship it", "description": "x", "activeForm": "y"}),
            result(2.1, "b", "Task #2 created successfully: Ship it", structured={"task": {"id": "2", "subject": "Ship it"}}),
            call(3, "c", "TaskUpdate", {"taskId": "1", "status": "completed"}),
            result(3.1, "c", "Updated task #1 status"),
            # Never answered: must not apply.
            call(4, "d", "TaskUpdate", {"taskId": "2", "status": "completed"}),
        ],
    )
    assert ref.todos == [("Write the parser", "completed"), ("Ship it", "pending")]
    assert "LONG PRIVATE DESCRIPTION" not in repr(ref.todos)


def test_a_task_update_reporting_failure_is_not_applied(tmp_path) -> None:
    ref = session(
        tmp_path,
        [
            call(1, "a", "TaskCreate", {"subject": "One"}),
            result(1.1, "a", "Task #1 created successfully: One"),
            call(2, "b", "TaskUpdate", {"taskId": "1", "status": "completed"}),
            result(2.1, "b", "Updated task #1", structured={"taskId": "1", "success": False}),
        ],
    )
    assert ref.todos == [("One", "pending")]


def test_a_subagents_todos_are_not_the_sessions(tmp_path) -> None:
    ref = session(tmp_path, [call(1, "a", "TodoWrite", {"todos": [{"content": "Sub plan", "status": "pending"}]}, sidechain=True), result(1.1, "a")])
    assert ref.todos is None


def test_files_change_only_on_success(tmp_path) -> None:
    ref = session(
        tmp_path,
        [
            call(1, "a", "Edit", {"file_path": "/w/repo/a.py", "old_string": "x", "new_string": "y"}),
            result(1.1, "a", "error", error=True),
            call(2, "b", "Write", {"file_path": "/w/repo/b.py", "content": "z"}),
            result(2.1, "b", "File created"),
        ],
    )
    assert ref.files_changed == ["/w/repo/b.py"]


def test_ten_updates_with_three_failing_or_unanswered_show_the_last_confirmed(tmp_path) -> None:
    """SC-004: the displayed list matches the last confirmed state, 10 of 10."""
    activity = ConfirmedActivity()
    confirmed = None
    outcomes = [True, True, False, True, None, True, True, False, True, True]  # None: no result
    for i, ok in enumerate(outcomes):
        items = [(f"step {j}", "completed" if j < i else "pending") for j in range(5)]
        activity.call(ToolCall(call_id=f"c{i}", tool="TodoWrite", todo=("replace", items)))
        if ok is not None:
            activity.result(ToolResult(call_id=f"c{i}", ok=ok))
        if ok:
            confirmed = items
        assert activity.visible_todos() == confirmed, f"after update {i}"
