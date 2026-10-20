"""Every repository puts row times on the wire WITH their UTC offset.

SQLite drops the zone of a DateTime(timezone=True) column on read, so rows come
back naive. A zone-less ISO string is parsed by a browser as local time (a chat
updated now read "in about 4 hours" in New York). Each converter is fed a row
with naive datetimes, exactly as SQLite returns it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from omniharness.persistence.timestamps import utc_iso

NAIVE = datetime(2026, 10, 19, 16, 0, 0, 123456)  # UTC, zone dropped
EXPECTED = "2026-10-19T16:00:00.123456+00:00"


def _thread_meta():
    from omniharness.persistence.thread_meta.model import ThreadMetaRow
    from omniharness.persistence.thread_meta.sql import ThreadMetaRepository

    return ThreadMetaRepository._row_to_dict(ThreadMetaRow(thread_id="t", created_at=NAIVE, updated_at=NAIVE)), ("created_at", "updated_at")


def _run():
    from omniharness.persistence.run.model import RunRow
    from omniharness.persistence.run.sql import RunRepository

    return RunRepository._row_to_dict(RunRow(run_id="r", thread_id="t", created_at=NAIVE, updated_at=NAIVE)), ("created_at", "updated_at")


def _feedback():
    from omniharness.persistence.feedback.model import FeedbackRow
    from omniharness.persistence.feedback.sql import FeedbackRepository

    return FeedbackRepository._row_to_dict(FeedbackRow(feedback_id="f", run_id="r", thread_id="t", rating=1, created_at=NAIVE)), ("created_at",)


def _composio():
    from omniharness.persistence.composio_connections.model import ComposioConnectionRow
    from omniharness.persistence.composio_connections.sql import ComposioConnectionRepository

    return ComposioConnectionRepository._row_to_dict(ComposioConnectionRow(id="c", user_id="u", toolkit="k", status="active", created_at=NAIVE, updated_at=NAIVE)), ("created_at", "updated_at")


def _mcp_server():
    from omniharness.persistence.mcp_server.model import McpServerRow
    from omniharness.persistence.mcp_server.sql import McpServerRepository

    return McpServerRepository._row_to_dict(McpServerRow(id="m", owner_id="u", name="n", created_at=NAIVE, updated_at=NAIVE)), ("created_at", "updated_at")


def _ledger():
    from omniharness.persistence.ledger.model import LedgerTaskRow
    from omniharness.persistence.ledger.sql import to_dict

    return to_dict(LedgerTaskRow(id="t", created_at=NAIVE, updated_at=NAIVE, done_at=NAIVE)), ("created_at", "updated_at", "done_at")


def _workflows():
    from app.gateway.routers.workflows import _dt, _dt_opt

    return {"a": _dt(NAIVE), "b": _dt_opt(NAIVE)}, ("a", "b")


@pytest.mark.parametrize("convert", [_thread_meta, _run, _feedback, _composio, _mcp_server, _ledger, _workflows], ids=lambda f: f.__name__.strip("_"))
def test_a_naive_row_time_is_sent_as_utc_with_its_offset(convert) -> None:
    out, keys = convert()
    for key in keys:
        assert out[key] == EXPECTED, f"{key}={out[key]!r}"


def test_utc_iso_normalises_an_aware_time_to_utc() -> None:
    assert utc_iso(NAIVE.replace(tzinfo=UTC)) == EXPECTED
    assert utc_iso((NAIVE - timedelta(hours=4)).replace(tzinfo=timezone(timedelta(hours=-4)))) == EXPECTED
