"""Continued sessions, and record types that are not drift (Feature 005 follow-up).

Fixtures are shaped like records found on a real ~/.claude (keys and nesting
only; every value here is synthetic):

  * the EARLIER session's file ends with
      {"type": "continued-in", "sessionId": <earlier>, "continuedInSessionId": <later>, "timestamp"}
  * the LATER session's file, in the same project folder, starts with a copy of
    the earlier history re-keyed to the later sessionId (the copies keep the
    earlier id in `session_id`), then carries its own records, which have
    `sessionKind: "bg"` and an `agentId`.

The pointer runs one way, earlier to later. The two are shown as one session.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import mcp.types as types
from session_watcher.adapters.claude_code import KNOWN_INERT_TYPES, ClaudeCodeAdapter
from session_watcher.record_source import RecordSource
from session_watcher.server import build_server, build_service

T0 = datetime(2026, 10, 14, 17, 0, tzinfo=UTC)
NOW = T0 + timedelta(hours=3)
EARLIER = "11111111-aaaa-4aaa-8aaa-000000000001"
LATER = "22222222-bbbb-4bbb-8bbb-000000000002"
SLUG = "-Users-dev-projects-darcy-repo"
CWD = "/Users/dev/projects/darcy-repo"


def _msg(kind: str, sid: str, alias: str, minute: float, text: str, uuid: str, *, stop: str | None = None, t0: datetime = T0, **extra) -> dict:
    rec = {
        "type": kind,
        "sessionId": sid,
        "session_id": alias,
        "uuid": uuid,
        "parentUuid": None,
        "timestamp": (t0 + timedelta(minutes=minute)).isoformat().replace("+00:00", "Z"),
        "cwd": CWD,
        "gitBranch": "main",
        "isSidechain": False,
        "entrypoint": "cli",
        "userType": "external",
        "version": "2.1.0",
        "message": {"role": kind, "content": [{"type": "text", "text": text}]},
        **extra,
    }
    if stop:
        rec["message"]["stop_reason"] = stop
    return rec


def _history(sid: str, alias: str, t0: datetime = T0) -> list[dict]:
    return [
        _msg("user", sid, alias, 0, "Synthetic request one.", "u-1", t0=t0),
        _msg("assistant", sid, alias, 1, "Synthetic reply one.", "u-2", stop="end_turn", t0=t0),
        _msg("user", sid, alias, 30, "Synthetic request two.", "u-3", t0=t0),
        _msg("assistant", sid, alias, 31, "Synthetic reply two.", "u-4", stop="end_turn", t0=t0),
    ]


def _continued_in(minute: float, t0: datetime = T0) -> dict:
    return {"type": "continued-in", "sessionId": EARLIER, "continuedInSessionId": LATER, "timestamp": (t0 + timedelta(minutes=minute)).isoformat().replace("+00:00", "Z")}


def _write(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def write_earlier(root: Path, *, linked: bool = True, t0: datetime = T0) -> None:
    _write(root / SLUG / f"{EARLIER}.jsonl", _history(EARLIER, EARLIER, t0) + ([_continued_in(31.1, t0)] if linked else []))


def write_later(root: Path, *, t0: datetime = T0) -> None:
    bg = {"sessionKind": "bg", "agentId": "a-bg-1"}
    copied = [{**r, **bg} for r in _history(LATER, EARLIER, t0)]
    own = [
        _msg("user", LATER, LATER, 32, "Synthetic request three.", "u-5", t0=t0, **bg),
        _msg("assistant", LATER, LATER, 33, "Synthetic reply three.", "u-6", stop="end_turn", t0=t0, **bg),
    ]
    _write(root / SLUG / f"{LATER}.jsonl", copied + own)


def _discover(root: Path):
    src = RecordSource(root=root)
    return ClaudeCodeAdapter(src).discover(timedelta(days=3650), now=NOW), src


def _call(server, name: str, args: dict) -> dict:
    req = types.CallToolRequest(method="tools/call", params=types.CallToolRequestParams(name=name, arguments=args))
    res = asyncio.run(server.request_handlers[types.CallToolRequest](req))
    return json.loads(res.root.content[0].text)


# ---- the adapter ---------------------------------------------------------


def test_a_continued_session_and_its_continuation_are_one_session(tmp_path) -> None:
    write_earlier(tmp_path)
    write_later(tmp_path)
    refs, _ = _discover(tmp_path)

    [ref] = refs
    assert ref.session_id == LATER
    assert ref.continued_from == EARLIER and ref.continued_in is None
    # The later file repeats the earlier history: each message appears once.
    texts = [r.text for r in ref.records if r.raw_type in ("user", "assistant")]
    assert len(texts) == len(set(texts)) == 6
    assert min(r.at for r in ref.records) == T0


def test_the_link_is_folded_even_when_the_continuation_does_not_repeat_history(tmp_path) -> None:
    """The fold must not depend on the copy: started_at is the earlier start."""
    write_earlier(tmp_path)
    _write(tmp_path / SLUG / f"{LATER}.jsonl", [_msg("user", LATER, LATER, 32, "Synthetic request three.", "u-5")])
    [ref] = _discover(tmp_path)[0]
    assert ref.session_id == LATER and ref.continued_from == EARLIER
    assert min(r.at for r in ref.records) == T0


def test_an_earlier_session_whose_continuation_is_not_in_view_says_where_it_went(tmp_path) -> None:
    write_earlier(tmp_path)
    [ref] = _discover(tmp_path)[0]
    assert ref.session_id == EARLIER
    assert ref.continued_in == LATER and ref.continued_from is None


def test_without_the_record_two_sessions_stay_two(tmp_path) -> None:
    """The link is read from the record, never guessed from the shared history."""
    write_earlier(tmp_path, linked=False)
    write_later(tmp_path)
    refs, _ = _discover(tmp_path)
    assert {r.session_id for r in refs} == {EARLIER, LATER}
    assert all(r.continued_from is None and r.continued_in is None for r in refs)


def test_continued_in_is_not_drift(tmp_path) -> None:
    write_earlier(tmp_path)
    write_later(tmp_path)
    _, src = _discover(tmp_path)
    assert "continued-in" not in src.stats.unknown_types
    assert src.stats.drift_signals == 0


# ---- record types that are not drift --------------------------------------

SID = "33333333-cccc-4ccc-8ccc-000000000003"
TS = (T0 + timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
#: One record per type, shaped like the real ones (synthetic values).
BOOKKEEPING = [
    {"type": "api-request-blob", "sessionId": SID, "hash": "h1", "message": {"role": "user", "content": [{"type": "text", "text": "x"}]}},
    {
        "type": "api-request",
        "sessionId": SID,
        "id": "44444444-dddd-4ddd-8ddd-000000000004",
        "base": "55555555-eeee-4eee-8eee-000000000005",
        "cacheControl": [],
        "keep": 1,
        "params": {"betas": [], "context_management": {}, "max_tokens": 1, "model": "m", "output_config": {}, "safeguards": [], "thinking": {}},
        "querySource": "q",
        "requestDigest": "d",
        "shapeHash": "s",
        "tail": [],
        "timestamp": TS,
        "version": "2.1.0",
    },
    {"type": "api-request-shape", "sessionId": SID, "shape": {"system": [], "tools": []}, "shapeHash": "s", "timestamp": TS, "version": "2.1.0"},
    {
        "type": "cost-state",
        "sessionId": SID,
        "hasUnknownModelCost": False,
        "modelUsage": {},
        "startTime": 0,
        "totalAPIDuration": 0,
        "totalAPIDurationWithoutRetries": 0,
        "totalCostUSD": 0.0,
        "totalDuration": 0,
        "totalLinesAdded": 0,
        "totalLinesRemoved": 0,
        "totalToolDuration": 0,
    },
    {"type": "artifact-comment-monitor", "sessionId": SID, "artifacts": {"66666666-ffff-4fff-8fff-000000000006": {}}, "v": 1},
    {"type": "artifact-autoreact-ledger", "sessionId": SID, "accountUuid": "77777777-aaaa-4aaa-8aaa-000000000007", "artifacts": {}, "v": 1},
]


def test_the_six_bookkeeping_types_are_known_and_not_drift(tmp_path) -> None:
    kinds = {r["type"] for r in BOOKKEEPING}
    assert kinds <= KNOWN_INERT_TYPES
    first = _msg("user", SID, SID, 1, "Synthetic.", "u-9")
    _write(tmp_path / SLUG / f"{SID}.jsonl", [first, *BOOKKEEPING])
    refs, src = _discover(tmp_path)
    assert [r.session_id for r in refs] == [SID]
    assert not kinds & set(src.stats.unknown_types), dict(src.stats.unknown_types)
    assert src.stats.drift_signals == 0


def test_a_truly_new_type_beside_them_is_still_drift(tmp_path) -> None:
    first = _msg("user", SID, SID, 1, "Synthetic.", "u-9")
    new = [{"type": "a-type-from-next-year", "sessionId": SID, "timestamp": TS}, {"type": "another-new-one", "sessionId": SID}]
    _write(tmp_path / SLUG / f"{SID}.jsonl", [first, *BOOKKEEPING, *new])
    _, src = _discover(tmp_path)
    assert src.stats.unknown_types["a-type-from-next-year"] == 1
    assert src.stats.unknown_types["another-new-one"] == 1
    # Only the timestamp-less one is a skip; `drift` counts skips (record_source).
    assert src.stats.drift_signals == 1
    assert set(src.stats.unknown_types) == {"a-type-from-next-year", "another-new-one"}


# ---- through the production composition root ------------------------------


def test_the_watcher_replies_with_one_session_and_says_it_was_continued(tmp_path) -> None:
    write_earlier(tmp_path)
    write_later(tmp_path)
    service = build_service(tmp_path, None)
    service.refresh(now=NOW)
    server = build_server(service)

    rollup = _call(server, "list_coding_sessions", {})
    [row] = rollup["sessions"]
    assert row["session_id"] == LATER and row["continued_from"] == EARLIER and row["continued_in"] is None
    assert rollup["reply"].startswith("1 session:")
    assert f"Continued from an earlier session ({EARLIER[:8]}); shown as one." in rollup["reply"]
    assert next(a for a in rollup["agents"] if a["agent"] == "claude")["drift"] == 0

    # Asked by the earlier id, the answer is the session it became.
    status = _call(server, "get_session_status", {"session_id": EARLIER})
    assert status["found"] is True and status["session"]["session_id"] == LATER
    assert f"in total. Continued from an earlier session ({EARLIER[:8]}); shown as one." in status["reply"]


def test_a_session_listed_before_it_was_continued_does_not_come_back_as_a_second_row(tmp_path) -> None:
    """The registry retains finished sessions that leave the sweep. One that
    was folded into its continuation has not left: it must not be retained."""
    write_earlier(tmp_path, linked=False)
    service = build_service(tmp_path, None)
    service.refresh(now=T0 + timedelta(minutes=31.5))
    assert [s.session_id for s in service.registry.all_sessions()] == [EARLIER]
    assert service.registry.sessions[EARLIER].is_terminal

    write_earlier(tmp_path)
    write_later(tmp_path)
    service.refresh(now=NOW)
    rows = service.list_sessions(now=NOW)["sessions"]
    assert [r["session_id"] for r in rows] == [LATER]


def test_the_reply_says_when_the_continuation_is_out_of_view(tmp_path) -> None:
    write_earlier(tmp_path)
    service = build_service(tmp_path, None)
    service.refresh(now=NOW)
    rollup = _call(build_server(service), "list_coding_sessions", {})
    [row] = rollup["sessions"]
    assert row["continued_in"] == LATER
    assert f"Continued in another session ({LATER[:8]}), which I can't see." in rollup["reply"]
