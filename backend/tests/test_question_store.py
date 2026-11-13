"""The question record's limits and its one terminal claim (009 question-card.md)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from app.gateway.questions.store import QuestionError, QuestionStore, build_question


def _q(**kwargs):
    base = {"thread_id": "t1", "owner_id": "o1", "asker": {"kind": "lead", "ref": {"run_id": "r"}}, "origin": "content", "question": "Which city?", "options": ["Philadelphia", "Boston"], "timeout_seconds": 60}
    return build_question(**{**base, **kwargs})


@pytest.mark.parametrize(
    "kwargs, reason",
    [
        ({"options": ["Only one"]}, "2 to 4 options"),
        ({"options": ["A", "B", "C", "D", "E"]}, "2 to 4 options"),
        ({"options": ["A", ""]}, "label must be 1 to 60"),
        ({"options": ["A", "x" * 61]}, "label must be 1 to 60"),
        ({"options": ["Same", "same"]}, "distinct"),
        ({"options": [{"label": "A", "description": "d" * 201}, "B"]}, "description"),
        ({"question": ""}, "1 to 500"),
        ({"question": "q" * 501}, "1 to 500"),
        ({"recommended": 2}, "recommended"),
        ({"on_expiry": "option:0"}, "always expires to stop"),
        ({"origin": "server", "on_expiry": "option:5"}, "names no option"),
        ({"origin": "server", "on_expiry": "maybe"}, "stop or option"),
        ({"timeout_seconds": 8 * 24 * 3600}, "7 days"),
        ({"origin": "user"}, "server or content"),
        ({"asker": {"ref": {}}}, "asker.kind"),
    ],
)
def test_the_contract_refuses_a_bad_question(kwargs, reason):
    with pytest.raises(QuestionError, match=reason):
        _q(**kwargs)


def test_a_good_question_has_a_free_text_box_and_a_safe_default():
    q = _q(options=[{"label": "Philadelphia", "description": "where you live"}, "Boston"], recommended=0)
    assert q.state == "open" and q.on_expiry == "stop" and q.default_option() is None
    assert q.options[0] == {"label": "Philadelphia", "description": "where you live"}


def test_one_answer_wins_and_terminal_states_never_change(tmp_path):
    store = QuestionStore(tmp_path)
    q = store.save(_q())
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda i: store.answer(q.id, option=i % 2, text=None, via="button"), range(8)))
    winners = [r for r in results if r is not None]
    assert len(winners) == 1
    assert store.expire(q.id, "timeout") is None
    assert store.get(q.id).state == "answered" and store.get(q.id).answer["option"] == winners[0].answer["option"]


def test_an_answer_after_the_deadline_expires_the_question(tmp_path):
    store = QuestionStore(tmp_path)
    q = _q()
    q.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    store.save(q)
    assert store.answer(q.id, option=0, text=None, via="button") is None
    assert store.get(q.id).state == "expired" and store.get(q.id).expired_reason == "timeout"
    assert store.get(q.id).outcome_text().endswith("; stopped this path.")


def test_one_shot_locks_and_unsafe_ids(tmp_path):
    store = QuestionStore(tmp_path)
    q = store.save(_q())
    assert store.take_once(q.id, "dispatched") is True
    assert store.take_once(q.id, "dispatched") is False
    assert store.get("../etc/passwd") is None and store.answer("../x", option=0, text=None, via="button") is None
