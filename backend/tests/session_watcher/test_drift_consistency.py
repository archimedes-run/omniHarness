"""Both adapters report format drift by the same rule, and /health shows it.

`drift` counts damaged lines, untyped records, record types never seen before
(whether the record was skipped for lacking a timestamp or parsed because it
had one) and named shape changes (`diagnostics`). Before this, a Claude Code
record of a new type WITH a timestamp reached `unknown_types` but not `drift`,
while Codex counted the same case as drift.
"""

from __future__ import annotations

import json
from datetime import timedelta

from codex_records import T0, event, meta, row, write
from session_watcher.server import build_service

NOW = T0 + timedelta(minutes=10)


def _claude(root, extra: list[dict]) -> None:
    folder = root / "-Users-dev-projects-darcy-repo"
    folder.mkdir(parents=True)
    first = {"type": "user", "sessionId": "c1", "timestamp": (T0 + timedelta(minutes=1)).isoformat(), "cwd": "/Users/dev/projects/darcy-repo", "message": {"role": "user", "content": "go"}}
    (folder / "c1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in [first, *extra]))


def _health(service) -> dict:
    return {a["agent"]: a for a in service.agents()}


def test_a_parsed_and_a_skipped_unknown_type_are_drift_for_both_agents(tmp_path) -> None:
    ts = (T0 + timedelta(minutes=2)).isoformat()
    _claude(tmp_path / "claude", [{"type": "claude-new-parsed", "sessionId": "c1", "timestamp": ts}, {"type": "claude-new-skipped", "sessionId": "c1"}])
    write(tmp_path / "codex", "2026/10/19", "x1", [meta(0, "x1"), row(1, "codex_new_type", {"type": "whatever"}), event(2, "task_started", turn_id="t")])
    service = build_service(tmp_path / "claude", tmp_path / "codex")
    service.refresh(now=NOW)
    health = _health(service)

    assert health["claude"]["unknown_types"] == {"claude-new-parsed": 1, "claude-new-skipped": 1}
    assert health["claude"]["drift"] == 2
    assert health["codex"]["unknown_types"] == {"codex_new_type:whatever": 1}
    assert health["codex"]["drift"] == 1
    assert health["claude"]["diagnostics"] == {} and health["codex"]["diagnostics"] == {}


def test_a_named_shape_change_is_drift_but_not_a_record_type(tmp_path) -> None:
    (tmp_path / "claude").mkdir()
    write(tmp_path / "codex", "2026/10/19", "orphan", [meta(0, "orphan", thread_source="subagent", source={"subagent": {"other": "x"}})])
    service = build_service(tmp_path / "claude", tmp_path / "codex")
    service.refresh(now=NOW)
    codex = _health(service)["codex"]
    assert codex["diagnostics"] == {"session_meta:subagent-without-parent": 1}
    assert codex["unknown_types"] == {}
    assert codex["drift"] == 1


def test_known_types_alone_are_no_drift(tmp_path) -> None:
    _claude(tmp_path / "claude", [{"type": "cost-state", "sessionId": "c1", "totalCostUSD": 0.0}])
    (tmp_path / "codex").mkdir()
    service = build_service(tmp_path / "claude", tmp_path / "codex")
    service.refresh(now=NOW)
    assert {a: h["drift"] for a, h in _health(service).items()} == {"claude": 0, "codex": 0}
