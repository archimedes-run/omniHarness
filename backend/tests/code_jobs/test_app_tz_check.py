"""The time-zone check reads each EVENT's shown time, never clock-like text
elsewhere on the page (Spec 011): the kit's own starter passes its own check
in every zone, a UTC-formatting app still fails, naming the event. The
browser half runs in the Docker end-to-end test (test_app_probe_docker.py);
this is the data and parser half, with the starter's shown times."""

from __future__ import annotations

import logging
import re
import zoneinfo
from datetime import datetime

import pytest

from app.gateway.code_jobs import app_checks, app_kit

from .test_app_mode import app_result

SOURCES = ["calendar", "gh_review", "inbox", "ledger"]
ZONES = ("America/New_York", "Europe/Berlin", "Asia/Kolkata", "UTC")


def _manifest(tz: str) -> dict:
    return app_kit.manifest_from_spec({"name": "Today", "sources": SOURCES, "timezone": tz})


def _clock(iso: str, tz: str) -> str:
    """What the kit's zoned(tz).formatTime prints (en-US, numeric hour)."""
    at = datetime.fromisoformat(iso).astimezone(zoneinfo.ZoneInfo(tz))
    return f"{at.hour % 12 or 12}:{at.minute:02d} {'AM' if at.hour < 12 else 'PM'}"


def _starter_page(tz: str) -> tuple[dict, list[tuple[str, str]]]:
    """The starter's calendar as the probe reads it: (expected, [(title, text of
    each kit-marked element)]). Rows show z.formatTime(start); the Timeline's
    <title> reads "title, time". Its hour axis (8a..7p) is never read."""
    data = app_kit.fixtures(_manifest(tz))
    items = [i for i in data["sources"]["calendar"]["fresh"]["items"] if not i["all_day"]]
    marked = [(i["title"], _clock(i["start"], tz)) for i in items]
    marked += [(i["title"], f"{i['title']}, {_clock(i['start'], tz)}") for i in items]
    return app_kit.expected_times(data), marked


def _measure(expected: dict, marked: list[tuple[str, str]]) -> dict:
    """The probe's reading of kit-marked elements (layout_probe.py APP_MEASURE)."""
    by_title = {e["title"]: e for e in expected["events"]}
    out = []
    for title, shown in marked:
        e = by_title[title]
        clock = (re.search(r"\d{1,2}:\d{2}(?:\s?[AaPp]\.?[Mm]\.?)?", shown) or [""])[0]
        out.append({"kind": "marked", "title": title, "shown": clock, "ok": bool(re.search(e["local_re"], shown)), "wrong": bool(e["shifted_re"] and re.search(e["shifted_re"], shown))})
    return {"marked": out, "near": []}


def _parse(times: dict, expected: dict) -> dict:
    raw = app_result({(t, "fresh"): {1280: {"times": times}} for t in ("light", "dark")})
    return app_checks.parse(raw, exit_code=0, data_sources=["calendar", "inbox", "gh_review"], time_events=expected)


@pytest.mark.parametrize("tz", ZONES)
def test_the_starter_passes_its_own_time_check_in_every_zone(tz):
    expected, marked = _starter_page(tz)
    r = _parse(_measure(expected, marked), expected)
    assert r["outcome"] == "pass", r["failures"]
    assert not any("time" in f for f in r["failures"])


def test_an_app_printing_utc_still_fails_naming_the_event():
    expected, marked = _starter_page("America/New_York")
    utc = [(t, _clock(next(e["iso"] for e in expected["events"] if e["title"] == t), "UTC")) for t, _ in marked]
    r = _parse(_measure(expected, utc), expected)
    assert r["outcome"] == "fail"
    assert "the event 'Team standup' shows 2:30 PM; expected 9:30 AM (America/New_York; light)" in r["failures"]


def test_the_message_names_roadmap_planning_when_only_it_is_shifted():
    expected, marked = _starter_page("America/New_York")
    shifted = [(t, "7:00 PM" if t == "Roadmap planning" else c) for t, c in marked]
    r = _parse(_measure(expected, shifted), expected)
    assert "the event 'Roadmap planning' shows 7:00 PM; expected 2:00 PM (America/New_York; light)" in r["failures"]


def test_the_kit_marks_event_times_and_its_hour_axis():
    files = app_kit.kit_files(_manifest("America/New_York"))
    react = files["omni-kit/omni-react.tsx"]
    assert "data-omni-time={time ?? undefined}" in react  # Row meta
    assert "<title data-omni-time={e.start!}>" in react  # Timeline event
    assert 'className="omni-timeline-hour" data-omni-axis=""' in react
    assert "time={item.start ?? null}" in files["omni-kit/starter/App.tsx"]


def test_heartbeat_lines_reach_the_console_and_the_daily_log_file(tmp_path, capsys):
    """Heartbeat lines show on the gateway's console capture
    (logs/gateway.console.log) and in GATEWAY_LOG_FILE's daily file, even
    with the configured level above INFO."""
    from app.gateway import log_files
    from app.gateway.code_jobs import runner
    from omniharness.config.app_config import apply_logging_level

    names = ("", "uvicorn", "uvicorn.error", "uvicorn.access")
    saved = {n: (list(logging.getLogger(n).handlers), logging.getLogger(n).propagate) for n in names}
    levels = (logging.getLogger().level, logging.getLogger("app").level)
    try:
        handler = log_files.install_log_file(str(tmp_path / "gateway.log"))
        apply_logging_level("warning")
        hb = runner.Heartbeat(None, "job-y")  # stopped before its first beat: no store call
        hb.start()
        hb.stop()
        handler.flush()
        written = "".join(p.read_text() for p in tmp_path.glob("gateway-*.log"))
        assert "code job job-y: heartbeat started" in written and "code job job-y: heartbeat stopped" in written
        console = capsys.readouterr().err
        assert "INFO - code job job-y: heartbeat started" in console and "heartbeat stopped" in console
    finally:
        for n, (handlers, propagate) in saved.items():
            target = logging.getLogger(n)
            for h in list(target.handlers):
                if h not in handlers:
                    target.removeHandler(h)
                    h.close()
            for h in handlers:
                if h not in target.handlers:
                    target.addHandler(h)
            target.propagate = propagate
        logging.getLogger().setLevel(levels[0])
        logging.getLogger("app").setLevel(levels[1])
