"""T051-T054 — User Story 2: the blocked session, and how it is worded.

Waiting-on-user is a PURE INFERENCE. The T055 spike established that nothing in
the observed format distinguishes a session paused on a permission prompt from
one merely between turns: no unmatched tool_use exists in a 25k-line corpus, and
permission-mode records carry the user's configured policy rather than runtime
state, with no timestamp.

So these tests assert two things in equal measure: that the inference fires when
it should, and that the sentence it produces sounds like an inference.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from session_watcher.adapters.base import ParsedRecord, SessionRef
from session_watcher.models import EventKind, IdleReason, SessionState
from session_watcher.reply import compose_rollup, observe_only_notice
from session_watcher.state import StateConfig, resolve

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
CFG = StateConfig(inactivity=timedelta(minutes=5), waiting_after=timedelta(seconds=45))


def _rec(minutes_ago, *, raw_type="assistant", stop_reason=None, text="working"):
    return ParsedRecord(
        session_id="s1",
        at=NOW - timedelta(minutes=minutes_ago),
        kind=EventKind.PROGRESS,
        project="darcy-repo",
        text=text,
        raw_type=raw_type,
        stop_reason=stop_reason,
    )


def _ref(records, project="darcy-repo"):
    return SessionRef(session_id="s1", project=project, path=None, records=records)


def _rollup(session):
    return compose_rollup(
        {
            "observable": True,
            "observability": "live",
            "staleness_seconds": 0,
            "sessions": [
                {
                    "session_id": session.session_id,
                    "project": session.project,
                    "state": session.state.value,
                    "idle_reason": session.idle_reason.value if session.idle_reason else None,
                    "quiet_seconds": int((NOW - session.last_activity_at).total_seconds()),
                    "elapsed_seconds": 3600,
                    "summary": "",
                    "summary_provenance": "mechanical",
                    "relay_suppressed": False,
                }
            ],
        }
    )


# --- detection ---------------------------------------------------------------


def test_unanswered_question_after_a_completed_turn_is_blocked() -> None:
    s = resolve(
        _ref(
            [
                _rec(20, raw_type="user", text="fix the tests"),
                _rec(2, stop_reason="end_turn", text="Two options here. Should I roll it back?"),
            ]
        ),
        now=NOW,
        config=CFG,
    )
    assert s.state is SessionState.WAITING_ON_USER


def test_a_reply_clears_the_waiting_state() -> None:
    """SC-002 — answered at the machine, so it must stop being reported."""
    s = resolve(
        _ref(
            [
                _rec(3, stop_reason="end_turn", text="Should I roll it back?"),
                _rec(1, raw_type="user", text="yes please"),
            ]
        ),
        now=NOW,
        config=CFG,
    )
    assert s.state is not SessionState.WAITING_ON_USER


def test_completed_turn_without_a_question_is_just_finished() -> None:
    s = resolve(_ref([_rec(2, stop_reason="end_turn", text="All 41 tests passed.")]), now=NOW, config=CFG)
    assert s.state is SessionState.IDLE
    assert s.idle_reason is IdleReason.COMPLETED


def test_a_long_build_is_not_reported_as_waiting_on_you() -> None:
    """THE false positive this design avoids.

    A running tool and a permission prompt produce an identical trace (spike
    R2b). Flagging that shape would announce "waiting on you" during every
    multi-minute build — constantly, and usually wrong.
    """
    s = resolve(_ref([_rec(3, stop_reason="tool_use", text="Running the suite.")]), now=NOW, config=CFG)
    assert s.state is SessionState.WORKING


def test_a_blocked_permission_prompt_still_surfaces_eventually() -> None:
    """...and NOT flagging it is not silence, which is the point.

    The pending-tool case is indistinguishable from a build, so it is not flagged
    early. It is not dropped either: past the inactivity period it becomes
    STALLED, whose wording sends the user to look. The expensive failure — a
    blocked session sitting unnoticed all evening — is covered by that path.
    """
    s = resolve(_ref([_rec(30, stop_reason="tool_use", text="Waiting on approval.")]), now=NOW, config=CFG)
    assert s.state is SessionState.IDLE
    assert s.idle_reason is IdleReason.STALLED
    assert "may have stalled" in _rollup(s)


def test_old_finished_session_ending_in_a_question_reads_as_finished() -> None:
    """Bounded by inactivity, or "Anything else?" would mean waiting forever."""
    s = resolve(_ref([_rec(600, stop_reason="end_turn", text="Anything else?")]), now=NOW, config=CFG)
    assert s.state is SessionState.IDLE
    assert s.idle_reason is IdleReason.COMPLETED


def test_question_detection_tolerates_trailing_markup() -> None:
    s = resolve(_ref([_rec(2, stop_reason="end_turn", text="Should I proceed?**")]), now=NOW, config=CFG)
    assert s.state is SessionState.WAITING_ON_USER


# --- error direction ---------------------------------------------------------


def test_uncertain_inference_surfaces_rather_than_staying_silent() -> None:
    """plan.md ruling: err toward possible-blocked, never toward silence.

    The evidence here is thin — a trailing question mark, nothing more. It is
    still surfaced, because a false "waiting on you" costs one wasted walk to the
    machine while a false "working" leaves a blocked session all evening.
    """
    s = resolve(_ref([_rec(1, stop_reason="end_turn", text="ok?")]), now=NOW, config=CFG)
    assert s.state is SessionState.WAITING_ON_USER
    text = _rollup(s)
    assert "looks like it's waiting on you" in text


def test_no_state_is_ever_silently_dropped() -> None:
    """Every shape resolves to something reportable — nothing vanishes."""
    cases = [
        [_rec(2, stop_reason="end_turn", text="Proceed?")],
        [_rec(2, stop_reason="tool_use")],
        [_rec(30, stop_reason="tool_use")],
        [_rec(2, stop_reason="end_turn", text="Done.")],
        [],
    ]
    for recs in cases:
        s = resolve(_ref(recs), now=NOW, config=CFG)
        assert s.state in set(SessionState), s.state
        assert _rollup(s).strip()


# --- wording as an acceptance criterion (T053) -------------------------------


def test_wording_leads_with_the_hedge_and_carries_the_evidence() -> None:
    """FR-016a. Required shape, asserted rather than described."""
    s = resolve(_ref([_rec(8, stop_reason="end_turn", text="Which branch should I target?")]), now=NOW, config=StateConfig(inactivity=timedelta(hours=1), waiting_after=timedelta(seconds=45)))
    text = _rollup(s)
    assert "looks like it's waiting on you" in text  # hedge
    assert "last activity was 8 minutes ago" in text  # observable evidence
    assert "nothing since" in text


@pytest.mark.parametrize(
    "forbidden",
    [
        "It's waiting for your input",
        "is waiting for your input",
        "It is waiting on you.",
    ],
)
def test_bare_assertion_shape_is_never_produced(forbidden) -> None:
    """The forbidden shape states an inference as an observation."""
    s = resolve(_ref([_rec(2, stop_reason="end_turn", text="Proceed?")]), now=NOW, config=CFG)
    assert forbidden not in _rollup(s)


def test_hedge_precedes_the_evidence_in_the_sentence() -> None:
    """Ordering, not just presence — a trailing hedge can be acted on first."""
    s = resolve(_ref([_rec(2, stop_reason="end_turn", text="Proceed?")]), now=NOW, config=CFG)
    text = _rollup(s)
    assert text.index("looks like") < text.index("last activity was")


# --- observe-only (T054) -----------------------------------------------------


def test_observe_only_notice_is_plain_and_offers_no_workaround() -> None:
    """FR-015, SC-010."""
    n = observe_only_notice()
    assert "can't" in n
    assert "at the machine" in n
    for weasel in ("try", "attempt", "might be able", "workaround"):
        assert weasel not in n.lower()


def test_no_tool_exists_to_act_on_a_session() -> None:
    """The limit is enforced by absence, not by policy (Article IV)."""
    import asyncio

    from session_watcher.server import WatcherService, build_server

    server = build_server(WatcherService(root=None))  # type: ignore[arg-type]
    handler = server.request_handlers
    assert handler, "server exposes no handlers"
    # The only tools are the two read-only ones; nothing to answer or intervene with.
    from mcp import types as t

    tools = asyncio.run(server.request_handlers[t.ListToolsRequest](t.ListToolsRequest(method="tools/list")))
    names = {x.name for x in tools.root.tools}
    assert names == {"list_coding_sessions", "get_session_status"}


# --- the event (T050) --------------------------------------------------------


def test_waiting_state_emits_an_event_nothing_consumes_yet() -> None:
    """FR-010 emits it; FR-025 forbids anything acting on it this phase."""
    s = resolve(_ref([_rec(2, stop_reason="end_turn", text="Proceed?")]), now=NOW, config=CFG)
    kinds = [e.kind for e in s.events]
    assert EventKind.QUESTION in kinds
