"""Tests for the input-family completeness gate + gap-radar (pdp.backtest.completeness)."""
from __future__ import annotations

from datetime import UTC, date, datetime

from pdp.backtest.completeness import (
    FAMILY_LABELS,
    RADAR_FAMILIES,
    FamilyGaps,
    radar_for_date,
    radar_window,
    spot_completeness,
    weekly_camarilla_gap_days,
)


def _bar(ts: datetime) -> dict:
    return {"ts": ts}


def _session_bars(n: int, *, start=datetime(2026, 1, 5, 3, 45, tzinfo=UTC)):
    from datetime import timedelta

    return [_bar(start + timedelta(minutes=i)) for i in range(n)]


def test_spot_completeness_ok_when_full_session():
    bars = _session_bars(375)
    result = spot_completeness(bars)
    assert result["ok"] is True
    assert result["bars"] == 375
    assert result["reason"] == ""


def test_spot_completeness_flags_thin_day():
    bars = _session_bars(50)
    result = spot_completeness(bars)
    assert result["ok"] is False
    assert "bars" in result["reason"]


def test_spot_completeness_flags_interior_gap():
    times = [datetime(2026, 1, 5, 3, 45, tzinfo=UTC)]
    times += [datetime(2026, 1, 5, 4, 30, tzinfo=UTC)]  # 45-min jump
    bars = [_bar(t) for t in times] * 200  # pad bar count so the gap, not bar count, fails
    result = spot_completeness(bars, expected_bars=2)
    assert result["ok"] is False
    assert "gap" in result["reason"]


def test_weekly_camarilla_gap_only_when_both_sources_missing():
    days = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
    spot_gaps = {date(2026, 1, 5), date(2026, 1, 6)}
    levels_gaps = {date(2026, 1, 6), date(2026, 1, 7)}
    gaps = weekly_camarilla_gap_days(spot_gaps, levels_gaps, days)
    # 1/6 missing in both -> gap. 1/5 (spot only) and 1/7 (levels only) are each covered
    # by the other source, so they are NOT gaps.
    assert gaps == {date(2026, 1, 6)}


def test_radar_for_date_reports_ready_and_missing_labels():
    day = date(2026, 1, 6)
    gaps = FamilyGaps(
        spot=set(),
        options={day},
        vix=set(),
        levels_weekly=set(),
    )
    status = radar_for_date(gaps, day)
    assert status["spot"] == "ready"
    assert status["options"] == FAMILY_LABELS["options"]
    assert set(status) == set(RADAR_FAMILIES)


def test_radar_for_date_all_families_ready_when_no_gaps():
    """Spec scenario: a trade-date with complete spot, options, VIX, and levels reports every
    family ready — no missing-family label leaks through when nothing is actually missing."""
    day = date(2026, 1, 6)
    other_day = date(2026, 1, 7)  # gaps exist, but on a different date — must not affect `day`
    gaps = FamilyGaps(
        spot={other_day},
        options={other_day},
        vix={other_day},
        levels_weekly={other_day},
    )
    status = radar_for_date(gaps, day)
    assert set(status) == set(RADAR_FAMILIES)
    assert all(v == "ready" for v in status.values())


def test_radar_window_keys_by_iso_date():
    days = [date(2026, 1, 6), date(2026, 1, 7)]
    gaps = FamilyGaps(spot=set(), options=set(), vix=set(), levels_weekly=set(days))
    window = radar_window(gaps, days)
    assert set(window) == {"2026-01-06", "2026-01-07"}
    assert window["2026-01-06"]["levels_weekly"] == FAMILY_LABELS["levels_weekly"]
    assert window["2026-01-06"]["spot"] == "ready"
