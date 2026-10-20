"""The Codex adapter (Feature 005 US3, FR-021 to FR-025, FR-031).

Fixtures are shaped like the user's real ~/.codex (codex_records.py); the
adapter was also run read-only over the real files (research.md section 2b)
before these fixtures were trusted (Article XII).
"""

from __future__ import annotations

from datetime import timedelta

from codex_records import T0, event, item, meta, patch_call, patch_end, plan_call, plan_ok, row, write
from session_watcher.adapters.codex import CodexAdapter
from session_watcher.models import EventKind
from session_watcher.record_source import RecordSource

NOW = T0 + timedelta(minutes=30)
WINDOW = timedelta(hours=24)


def discover(root):
    source = RecordSource(root=root)
    adapter = CodexAdapter(source)
    return adapter, source, {r.session_id: r for r in adapter.discover(WINDOW, now=NOW)}


def test_a_session_has_its_id_project_agent_and_an_observed_completed_turn(tmp_path) -> None:
    write(tmp_path, "2026/10/19", "s1", [meta(0, "s1"), event(1, "task_started", turn_id="t1"), event(2, "user_message", message="hi"), event(5, "task_complete", turn_id="t1", last_agent_message="Done.")])
    _, source, refs = discover(tmp_path)
    ref = refs["s1"]
    assert (ref.agent, ref.project) == ("codex", "beta-site")
    assert ref.records[0].kind is EventKind.STARTED
    assert ref.records[-1].is_end_of_turn and ref.records[-1].kind is EventKind.COMPLETED
    assert source.stats.drift_signals == 0


def test_a_plan_applies_only_once_its_result_confirms_it(tmp_path) -> None:
    write(
        tmp_path,
        "2026/10/19",
        "s1",
        [
            meta(0, "s1"),
            plan_call(1, "c1", [("Write tests", "in_progress"), ("Ship", "pending")], explanation="SECRET reasoning"),
            plan_ok(1.1, "c1"),
            # A later update that never got its acknowledgement (interrupted).
            plan_call(2, "c2", [("Write tests", "completed"), ("Ship", "completed")]),
        ],
    )
    _, _, refs = discover(tmp_path)
    assert refs["s1"].todos == [("Write tests", "in_progress"), ("Ship", "pending")], "an unconfirmed plan was applied"


def test_a_failed_patch_changes_no_files_and_a_successful_one_does(tmp_path) -> None:
    write(
        tmp_path,
        "2026/10/19",
        "s1",
        [
            meta(0, "s1"),
            patch_call(1, "p1", ["src/a.py"]),
            patch_end(1.1, "p1", ["src/a.py"], success=False),
            item(1.2, "custom_tool_call_output", call_id="p1", output="Exit code: 1\nerror"),
            patch_call(2, "p2", ["src/b.py"]),
            patch_end(2.1, "p2", ["src/b.py"], success=True),
            item(2.2, "custom_tool_call_output", call_id="p2", output="Exit code: 0\nSuccess."),
        ],
    )
    _, _, refs = discover(tmp_path)
    assert refs["s1"].files_changed == ["src/b.py"]


def test_a_resumed_session_is_found_by_mtime_in_its_old_folder_and_is_not_drift(tmp_path) -> None:
    """A resume appends a repeated session_meta to the ORIGINAL file (FR-022)."""
    write(tmp_path, "2026/06/07", "old", [meta(0, "old"), event(1, "task_complete", turn_id="t1", last_agent_message=""), meta(20, "old"), event(21, "user_message", message="again")], mtime=NOW)
    _, source, refs = discover(tmp_path)
    assert list(refs) == ["old"], "a resume read as a new session, or the old folder was skipped"
    assert source.stats.drift_signals == 0, "a repeated session_meta counted as drift"


def test_a_file_untouched_for_longer_than_the_window_is_not_read(tmp_path) -> None:
    write(tmp_path, "2026/10/19", "stale", [meta(0, "stale")], mtime=NOW - timedelta(days=3))
    _, source, refs = discover(tmp_path)
    assert refs == {} and source.stats.records_opened == 0


def test_subagents_attach_to_their_parent_in_both_link_shapes(tmp_path) -> None:
    """This machine links by top-level parent_thread_id; the reference
    implementation reads only the nested thread_spawn shape (FR-023)."""
    write(tmp_path, "2026/10/19", "parent", [meta(0, "parent"), event(1, "task_started", turn_id="t1")])
    write(
        tmp_path,
        "2026/10/19",
        "child1",
        [meta(2, "child1", thread_source="subagent", parent_thread_id="parent", session_id="parent", source={"subagent": {"other": "x"}}), patch_call(3, "p", ["src/c.py"]), patch_end(3.1, "p", ["src/c.py"], success=True)],
    )
    write(tmp_path, "2026/10/19", "child2", [meta(4, "child2", source={"subagent": {"thread_spawn": {"parent_thread_id": "parent"}}}), event(5, "task_complete", turn_id="t9", last_agent_message="child done")])
    _, source, refs = discover(tmp_path)
    assert list(refs) == ["parent"], "a subagent was listed as its own session"
    assert refs["parent"].files_changed == ["src/c.py"]
    # The child's turn ending does not end the parent's turn.
    assert not any(r.is_end_of_turn for r in refs["parent"].records)
    assert source.stats.drift_signals == 0


def test_a_subagent_naming_no_parent_is_drift(tmp_path) -> None:
    write(tmp_path, "2026/10/19", "orphan", [meta(0, "orphan", thread_source="subagent", source={"subagent": {"other": "x"}})])
    _, source, _ = discover(tmp_path)
    assert source.stats.unknown_types["session_meta:subagent-without-parent"] == 1


def test_known_inert_types_are_not_drift_and_a_new_type_is(tmp_path) -> None:
    write(
        tmp_path,
        "2026/10/19",
        "s1",
        [meta(0, "s1"), row(1, "turn_context", {"cwd": "/x"}), event(1, "token_count"), item(1, "reasoning"), event(2, "brand_new_event"), row(3, "brand_new_type", {})],
    )
    _, source, _ = discover(tmp_path)
    assert dict(source.stats.unknown_types) == {"event_msg:brand_new_event": 1, "brand_new_type": 1}


def test_archived_sessions_are_never_read(tmp_path) -> None:
    sessions = tmp_path / "sessions"
    write(sessions, "2026/10/19", "live", [meta(0, "live")])
    archived = tmp_path / "archived_sessions"
    archived.mkdir()
    (archived / "rollout-x.jsonl").write_text((sessions / "2026/10/19").glob("*.jsonl").__next__().read_text().replace("live", "gone"))
    _, _, refs = discover(sessions)
    assert list(refs) == ["live"]


def test_a_half_written_last_line_waits_for_its_newline(tmp_path) -> None:
    path = write(tmp_path, "2026/10/19", "s1", [meta(0, "s1")])
    with path.open("a") as fh:
        fh.write('{"timestamp": "2026-10-19T09:05:00Z", "type": "event_msg", "payload": {"type": "task_comp')
    _, source, refs = discover(tmp_path)
    assert source.stats.skips["malformed-json"] == 0
    assert len(refs["s1"].records) == 1
