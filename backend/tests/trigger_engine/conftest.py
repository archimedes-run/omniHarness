"""Fixtures for the trigger-engine tests.

No `__init__.py` in this directory on purpose: `backend/tests/` has none, so
adding one puts `tests/` on sys.path where the directory would shadow a real
package. That cost a debugging cycle on feature 001.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


class FakeClock:
    """A clock the tests own. Real time makes schedule tests flaky and slow."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 8, 21, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, **kw) -> datetime:
        self._now += timedelta(**kw)
        return self._now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def rule_file(tmp_path: Path) -> Callable[..., Path]:
    """Write a rule file and return its path."""

    def _write(rules: list[dict], **top) -> Path:
        doc = {
            "quiet_hours": {"start": "22:00", "end": "07:30", "timezone": "UTC"},
            "defaults": {
                "coalesce_window_seconds": 60,
                "presence_threshold_seconds": 300,
                "queued_turn_max_wait_seconds": 300,
                "fingerprint_retention": "24h",
            },
            "rules": rules,
        }
        doc.update(top)
        f = tmp_path / "rules.json"
        f.write_text(json.dumps(doc, indent=2))
        return f

    return _write


@pytest.fixture
def a_rule() -> Callable[..., dict]:
    def _rule(rid: str = "r1", rtype: str = "watcher", **kw) -> dict:
        base = {
            "id": rid,
            "type": rtype,
            "match": {"event": "waiting-on-user"} if rtype == "watcher" else {"schedule": "0 7 * * *"},
            "prompt": "Session {project} needs you: {last_message}",
            "destination": "quiet",
        }
        base.update(kw)
        return base

    return _rule
