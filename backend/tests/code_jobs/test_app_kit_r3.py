"""App kit round 3 (Spec 011): sample data in the app's time zone around a
fixed sample now, the checks that the data is shown right, and the version
card's own check screenshots."""

from __future__ import annotations

import json
import re

from app.gateway.code_jobs import app_checks, app_kit

from .test_app_mode import app_result

TODAY = ["calendar", "gh_review", "gh_failing", "gh_merged", "ledger", "sessions", "automations", "inbox"]
COUNTS = {"calendar": 6, "inbox": 5, "gh_review": 3}


def manifest(tz="America/New_York"):
    return app_kit.manifest_from_spec({"name": "Today", "sources": TODAY, "timezone": tz})


def test_sample_data_is_written_for_a_fixed_now_in_the_apps_time_zone():
    data = app_kit.fixtures(manifest())
    assert data["now"] == "2026-01-14T10:20:00-05:00" and data["time_zone"] == "America/New_York"
    cal = data["sources"]["calendar"]["fresh"]["items"]
    assert cal[0] == {"title": "Release week", "start": "2026-01-14", "end": "2026-01-15", "all_day": True}
    assert [i["start"][11:16] for i in cal[1:]] == ["09:30", "11:00", "12:30", "14:00", "16:00"] and all(i["start"].endswith("-05:00") for i in cal[1:])
    ledger = data["sources"]["ledger"]["fresh"]["items"]
    assert ledger[0]["bucket"] == "overdue" and ledger[0]["due_date"] == "2026-01-13"
    runs = data["sources"]["automations"]["fresh"]["items"]
    assert runs[0]["next_run"] == "2026-01-14T12:00:00-05:00" and runs[2]["last_run"].startswith("2026-01-12")
    berlin = app_kit.fixtures(manifest("Europe/Berlin"))["sources"]["calendar"]["fresh"]["items"][1]["start"]
    assert berlin == "2026-01-14T09:30:00+01:00"


def test_expected_times_accept_both_clock_styles_and_know_the_utc_ones():
    times = app_kit.expected_times(app_kit.fixtures(manifest()))
    events = times["events"]
    assert times["time_zone"] == "America/New_York"
    assert [e["local_label"] for e in events] == ["9:30 AM", "11:00 AM", "12:30 PM", "2:00 PM", "4:00 PM"]
    assert events[3]["title"] == "Roadmap planning" and events[3]["iso"] == "2026-01-14T14:00:00-05:00"
    first = re.compile(events[0]["local_re"])
    assert first.search("Team standup 9:30 AM") and first.search("09:30") and not first.search("19:30")
    two = re.compile(events[3]["local_re"])
    assert two.search("14:00") and two.search("2:00 PM")
    assert events[0]["shifted_label"] == "2:30 PM" and events[3]["shifted_label"] == "7:00 PM"
    assert all(e["shifted_re"] is None for e in app_kit.expected_times(app_kit.fixtures(manifest("UTC")))["events"])


def test_the_kit_carries_the_time_zone_and_the_components():
    files = app_kit.kit_files(manifest())
    assert files["omni-kit/app-config.ts"].endswith('export const TIME_ZONE = "America/New_York";\n')
    react = files["omni-kit/omni-react.tsx"]
    for name in ("export function zoned(", "export function Row(", "export function Stat(", "export function Timeline(", "export function Sparkline("):
        assert name in react
    starter = files["omni-kit/starter/App.tsx"]
    assert "<Timeline events={data.items} tz={TIME_ZONE} now={omni.now()} />" in starter and "<Row " in starter and "getHours" not in starter
    rules = files["omni-kit/APP_RULES.md"]
    assert "omni.now()" in rules and "zoned(TIME_ZONE)" in rules and "never with `getHours()`" in rules
    assert "now(): Date;" in files["omni-kit/omni.d.ts"]


def _fresh(change_1280: dict) -> str:
    return app_result({(t, "fresh"): {1280: change_1280} for t in ("light", "dark")})


def parse(raw, **kw):
    return app_checks.parse(raw, exit_code=0, data_sources=["calendar", "inbox", "gh_review"], item_counts=COUNTS, **kw)


def _times(marked=(), near=()) -> dict:
    return {"times": {"marked": list(marked), "near": list(near)}}


def test_times_in_another_zone_fail_naming_the_event_and_the_right_ones_pass():
    expected = app_kit.expected_times(app_kit.fixtures(manifest()))
    wrong = _fresh(_times(near=[{"kind": "near", "title": "Roadmap planning", "found": True, "ok": False, "wrong": True}]))
    r = parse(wrong, time_events=expected)
    assert r["outcome"] == "fail" and "the event 'Roadmap planning' shows 7:00 PM; expected 2:00 PM (America/New_York; light)" in r["failures"]
    right = _fresh(_times(marked=[{"kind": "marked", "title": "Roadmap planning", "shown": "2:00 PM", "ok": True, "wrong": False}]))
    assert parse(right, time_events=expected)["outcome"] == "pass"


def test_text_cut_to_nothing_and_spilling_chart_labels_fail():
    r = parse(_fresh({"cut": ["span.omni-row-title in li.omni-row"]}))
    assert "a row's title is cut to almost nothing: span.omni-row-title in li.omni-row" in r["failures"]
    r = parse(app_result({("light", "fresh"): {"all": {"spill": ["svg.omni-chart in div.omni-timeline"]}}}))
    assert any(f.startswith("chart label overflows its block: svg.omni-chart in div.omni-timeline") for f in r["failures"])


def test_a_tile_must_show_half_its_sample_items_or_say_how_many_more():
    few = _fresh({"sentinels": {"calendar": 6, "inbox": 4, "gh_review": 1}})
    assert "a tile shows fewer than half of its sample items (source gh_review) and no 'N more' line" in parse(few)["failures"]
    assert parse(_fresh({"sentinels": {"calendar": 6, "inbox": 4, "gh_review": 1}, "more": True}))["outcome"] == "pass"


def test_a_mostly_empty_card_is_a_design_finding_only():
    r = parse(_fresh({"empty_cards": ["section.omni-tile in div.omni-grid"]}))
    assert r["outcome"] == "pass" and r["design"] == ["card is mostly empty next to a fuller card in its row: section.omni-tile in div.omni-grid"]


def test_the_check_config_carries_the_times(tmp_path):
    data = app_kit.fixtures(manifest())
    assert json.loads(json.dumps(app_kit.expected_times(data)))["events"][0]["local_label"] == "9:30 AM"


def test_times_pass_when_the_shown_ones_are_local_and_fail_on_a_shifted_or_none():
    expected = app_kit.expected_times(app_kit.fixtures(manifest()))
    ok = {"kind": "near", "title": "Team standup", "found": True, "ok": True, "wrong": False}
    some = _fresh(_times(near=[ok, {"kind": "near", "title": "Lunch with Sam", "found": False, "ok": False, "wrong": False}]))
    assert parse(some, time_events=expected)["outcome"] == "pass"  # a "next 2 meetings" design
    none = _fresh(_times(near=[{**ok, "ok": False}]))
    r = parse(none, time_events=expected)
    assert r["outcome"] == "fail" and any(f.startswith("the calendar's sample times are not shown in the app's time zone (expected 9:30 AM for 'Team standup'") for f in r["failures"])
    mixed = _fresh(_times(near=[ok, {"kind": "near", "title": "Lunch with Sam", "found": True, "ok": False, "wrong": True}]))
    assert "the event 'Lunch with Sam' shows 5:30 PM; expected 12:30 PM (America/New_York; light)" in parse(mixed, time_events=expected)["failures"]
    # A kit-marked time is compared with that event's local time, whatever it shows.
    off = _fresh(_times(marked=[{"kind": "marked", "title": "Team standup", "shown": "10:30 AM", "ok": False, "wrong": False}]))
    assert "the event 'Team standup' shows 10:30 AM; expected 9:30 AM (America/New_York; light)" in parse(off, time_events=expected)["failures"]


def test_a_utc_time_equal_to_a_local_one_is_never_counted_as_shifted():
    shifted = [e["shifted_label"] for e in app_kit.expected_times(app_kit.fixtures(manifest()))["events"]]
    assert "4:00 PM" not in shifted and "2:30 PM" in shifted


def test_two_rows_and_the_total_are_a_summary_not_missing_items():
    summary = _fresh({"sentinels": {"calendar": 6, "inbox": 2, "gh_review": 3}, "totals": {"inbox": True}})
    assert parse(summary)["outcome"] == "pass"
    one = _fresh({"sentinels": {"calendar": 6, "inbox": 1, "gh_review": 3}, "totals": {"inbox": True}})
    assert any("(source inbox)" in f for f in parse(one)["failures"])


def test_malformed_measurements_are_unreadable_not_an_exception():
    for bad in ({"spill": 5}, {"cut": {"a": 1}}, {"empty_cards": "x"}, {"times": [1]}, {"sentinels": {"inbox": "3"}}):
        r = parse(_fresh(bad))
        assert r["outcome"] in ("pass", "fail", "error")
    data = json.loads(_fresh({}))
    data["runs"][0]["violations"] = 5  # not a list
    assert parse(json.dumps(data))["error_code"] == "unreadable"


def _png(width=1280, height=900, depth=8, colour=6) -> bytes:
    import struct
    import zlib

    ihdr = struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, 0)
    chunk = struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))
    return b"\x89PNG\r\n\x1a\n" + chunk


def test_only_the_checks_own_screenshots_are_stored(tmp_path, monkeypatch):
    import pytest

    from omniharness.config import config_versions as cv

    monkeypatch.setattr(cv, "_app_root", lambda user_id: tmp_path)
    digest = cv.write_app_shot("u", _png())
    assert cv.read_app_shot("u", digest).startswith(b"\x89PNG")
    for bad in (_png(width=800), _png(height=5000), _png(depth=3), _png(colour=5), b"\x89PNG\r\n\x1a\n" + b"x" * 40):
        with pytest.raises(ValueError):
            cv.write_app_shot("u", bad)
