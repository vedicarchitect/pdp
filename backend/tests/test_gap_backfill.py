"""Offline tests for the reusable Dhan gap-fill core (pdp.options.gap_backfill).

Covers band/trade-day enumeration, the option_bars gap-detection aggregation contract, and that
backfill_gaps only targets under-covered days. No Mongo or Dhan creds required.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

import pdp.options.gap_backfill as gb
from pdp.options.gap_backfill import (
    DEFAULT_LADDER,
    backfill_gaps,
    build_ladder,
    collapse_date_ranges,
    days_missing,
    expected_contracts,
    labels,
    trading_days,
)

_WEEK12 = [("WEEK", 1), ("WEEK", 2)]


def _as_date(v):
    """option_bars stores expiry_date as a tz-aware datetime; normalise to date for comparison."""
    return v.date() if hasattr(v, "date") else v


def test_labels_and_expected_contracts():
    labs = labels(10)
    assert labs[0] == ("ATM", 0)
    assert len(labs) == 21  # ATM + 10 above + 10 below
    assert ("ATM+10", 10) in labs and ("ATM-10", -10) in labs
    # 2-entry ladder x 21 strikes x CE/PE
    assert expected_contracts(_WEEK12, 10) == 84
    # full ladder is 5 entries (WEEK 1,2,3 + MONTH 1,2)
    assert expected_contracts(DEFAULT_LADDER, 10) == 5 * 21 * 2


def test_build_ladder_composes_week_then_month():
    assert build_ladder([1, 2, 3], [1, 2]) == DEFAULT_LADDER
    assert build_ladder([1], []) == [("WEEK", 1)]
    assert build_ladder([], [1]) == [("MONTH", 1)]


def test_trading_days_excludes_weekends_and_holidays():
    # 2026-04-06 is a Monday; 2026-04-07 a Tuesday we mark as a holiday.
    days = trading_days(date(2026, 4, 4), date(2026, 4, 10), {date(2026, 4, 7)})
    assert date(2026, 4, 4) not in days  # Saturday
    assert date(2026, 4, 5) not in days  # Sunday
    assert date(2026, 4, 7) not in days  # holiday
    assert days == [date(2026, 4, 6), date(2026, 4, 8), date(2026, 4, 9), date(2026, 4, 10)]


class _FakeAggCol:
    """Stub collection returning a fixed per-IST-day distinct-contract count."""

    def __init__(self, per_day: dict[date, int]) -> None:
        self._per_day = per_day

    def aggregate(self, pipeline):
        return [{"_id": datetime(d.year, d.month, d.day), "contracts": n}
                for d, n in self._per_day.items()]


def test_days_missing_flags_absent_and_thin_days():
    days = [date(2026, 4, 6), date(2026, 4, 8), date(2026, 4, 9)]
    # full=84 expected; 4/8 is fully covered, 4/9 is thin (10 < 42 threshold), 4/6 absent entirely.
    col = _FakeAggCol({date(2026, 4, 8): 84, date(2026, 4, 9): 10})
    missing = days_missing(col, days, _WEEK12, band=10, min_fraction=0.5)
    assert date(2026, 4, 6) in missing   # absent
    assert date(2026, 4, 9) in missing   # thin
    assert date(2026, 4, 8) not in missing  # fully covered


def test_backfill_gaps_only_targets_missing_days(monkeypatch):
    days = [date(2026, 4, 6), date(2026, 4, 8), date(2026, 4, 9)]
    col = _FakeAggCol({date(2026, 4, 8): 84})  # only 4/8 covered

    filled: list[str] = []

    def _fake_fill_day(dhan, c, cal, ds, ladder, label_offsets, **_):
        filled.append(ds)
        return 5  # pretend 5 bars inserted per day

    monkeypatch.setattr(gb, "fill_day", _fake_fill_day)

    summary = backfill_gaps(dhan=object(), col=col, cal=object(), days=days,
                            ladder=_WEEK12, band=10)
    assert set(filled) == {"2026-04-06", "2026-04-09"}  # 4/8 skipped (covered)
    assert summary["scanned"] == 3
    assert summary["gaps"] == 2
    assert summary["days_filled"] == 2
    assert summary["total_inserted"] == 10


class _FakeCal:
    """Resolves (day, flag, code) to a fixed expiry per flag, ignoring the day."""

    def __init__(self, by_flag: dict[str, date]) -> None:
        self._by_flag = by_flag

    def resolve_expiry(self, _day, flag, _code):
        return self._by_flag.get(flag.upper())


class _FakeDhan:
    """Minimal Dhan double: one spot bar + one option bar per side, recording option calls."""

    def __init__(self, ts_epoch: float) -> None:
        self._ts = ts_epoch
        self.option_calls: list[dict] = []

    def intraday_minute_data(self, **_kwargs):
        return {"status": "success",
                "data": {"close": [100.0], "timestamp": [self._ts]}}

    def expired_options_data(self, **kwargs):
        self.option_calls.append(kwargs)
        side = "ce" if kwargs["drv_option_type"] == "CALL" else "pe"
        return {"status": "success", "data": {side: {
            "open": [10.0], "high": [11.0], "low": [9.0], "close": [10.5],
            "volume": [100], "oi": [200], "iv": [15.0], "timestamp": [self._ts],
        }}}


def test_fill_day_ladder_threads_week_and_month_flags(monkeypatch):
    e_week, e_month = date(2023, 3, 16), date(2023, 3, 30)
    ts = datetime(2023, 3, 16, 4, 0, tzinfo=UTC).timestamp()
    dhan = _FakeDhan(ts)
    cal = _FakeCal({"WEEK": e_week, "MONTH": e_month})

    captured: list[dict] = []
    monkeypatch.setattr(gb, "upsert_option_bars_sync",
                        lambda _col, docs: captured.extend(docs) or len(docs))

    n = gb.fill_day(dhan, object(), cal, "2023-03-16",
                    [("WEEK", 1), ("MONTH", 1)], labels(0))  # band 0 -> ATM only

    # 2 ladder entries x 1 label x CE/PE = 4 docs
    assert n == 4
    # Each fetch carried its own flag through to Dhan…
    assert {c["expiry_flag"] for c in dhan.option_calls} == {"WEEK", "MONTH"}
    # …and the resulting docs are labelled with the matching expiry date + flag.
    by_flag = {(d["expiry_flag"], _as_date(d["expiry_date"])) for d in captured}
    assert (("WEEK", e_week) in by_flag) and (("MONTH", e_month) in by_flag)


def test_fill_day_expiry_override_labels_single_entry(monkeypatch):
    target = date(2023, 3, 23)
    ts = datetime(2023, 3, 16, 4, 0, tzinfo=UTC).timestamp()
    dhan = _FakeDhan(ts)

    captured: list[dict] = []
    monkeypatch.setattr(gb, "upsert_option_bars_sync",
                        lambda _col, docs: captured.extend(docs) or len(docs))

    # cal=None is allowed under an override; single-entry ladder keeps the labelling honest.
    n = gb.fill_day(dhan, object(), None, "2023-03-16",
                    [("WEEK", 1)], labels(0), expiry_override=target)

    assert n == 2  # CE + PE
    assert {_as_date(d["expiry_date"]) for d in captured} == {target}


def test_collapse_date_ranges_merges_consecutive_and_near_gaps():
    days = [
        date(2026, 4, 6), date(2026, 4, 7),  # consecutive -> one range
        date(2026, 4, 20),                    # isolated
        date(2026, 4, 22), date(2026, 4, 23),  # within 3 days of 4/20 and each other -> merges in
    ]
    ranges = collapse_date_ranges(days)
    assert ranges == ["2026-04-06..2026-04-07", "2026-04-20..2026-04-23"]


def test_collapse_date_ranges_empty():
    assert collapse_date_ranges([]) == []


def test_backfill_gaps_only_missing_false_scans_all(monkeypatch):
    days = [date(2026, 4, 6), date(2026, 4, 8)]
    col = _FakeAggCol({date(2026, 4, 8): 84})

    filled: list[str] = []
    monkeypatch.setattr(gb, "fill_day",
                        lambda *a, **k: filled.append(a[3]) or 0)

    backfill_gaps(dhan=object(), col=col, cal=object(), days=days,
                  ladder=_WEEK12, band=10, only_missing=False)
    assert set(filled) == {"2026-04-06", "2026-04-08"}  # both fetched
