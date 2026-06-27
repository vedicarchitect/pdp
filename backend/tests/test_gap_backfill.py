"""Offline tests for the reusable Dhan gap-fill core (pdp.options.gap_backfill).

Covers band/trade-day enumeration, the option_bars gap-detection aggregation contract, and that
backfill_gaps only targets under-covered days. No Mongo or Dhan creds required.
"""
from __future__ import annotations

from datetime import date, datetime

import pdp.options.gap_backfill as gb
from pdp.options.gap_backfill import (
    backfill_gaps,
    days_missing,
    expected_contracts,
    labels,
    trading_days,
)


def test_labels_and_expected_contracts():
    labs = labels(10)
    assert labs[0] == ("ATM", 0)
    assert len(labs) == 21  # ATM + 10 above + 10 below
    assert ("ATM+10", 10) in labs and ("ATM-10", -10) in labs
    # codes 1,2 × 21 strikes × CE/PE
    assert expected_contracts([1, 2], 10) == 84


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

    def aggregate(self, pipeline):  # noqa: ARG002 - signature parity only
        return [{"_id": datetime(d.year, d.month, d.day), "contracts": n}
                for d, n in self._per_day.items()]


def test_days_missing_flags_absent_and_thin_days():
    days = [date(2026, 4, 6), date(2026, 4, 8), date(2026, 4, 9)]
    # full=84 expected; 4/8 is fully covered, 4/9 is thin (10 < 42 threshold), 4/6 absent entirely.
    col = _FakeAggCol({date(2026, 4, 8): 84, date(2026, 4, 9): 10})
    missing = days_missing(col, days, codes=[1, 2], band=10, min_fraction=0.5)
    assert date(2026, 4, 6) in missing   # absent
    assert date(2026, 4, 9) in missing   # thin
    assert date(2026, 4, 8) not in missing  # fully covered


def test_backfill_gaps_only_targets_missing_days(monkeypatch):
    days = [date(2026, 4, 6), date(2026, 4, 8), date(2026, 4, 9)]
    col = _FakeAggCol({date(2026, 4, 8): 84})  # only 4/8 covered

    filled: list[str] = []

    def _fake_fill_day(dhan, c, cal, ds, codes, label_offsets, **_):  # noqa: ARG001
        filled.append(ds)
        return 5  # pretend 5 bars inserted per day

    monkeypatch.setattr(gb, "fill_day", _fake_fill_day)

    summary = backfill_gaps(dhan=object(), col=col, cal=object(), days=days,
                            codes=[1, 2], band=10)
    assert set(filled) == {"2026-04-06", "2026-04-09"}  # 4/8 skipped (covered)
    assert summary["scanned"] == 3
    assert summary["gaps"] == 2
    assert summary["days_filled"] == 2
    assert summary["total_inserted"] == 10


def test_backfill_gaps_only_missing_false_scans_all(monkeypatch):
    days = [date(2026, 4, 6), date(2026, 4, 8)]
    col = _FakeAggCol({date(2026, 4, 8): 84})

    filled: list[str] = []
    monkeypatch.setattr(gb, "fill_day",
                        lambda *a, **k: filled.append(a[3]) or 0)

    backfill_gaps(dhan=object(), col=col, cal=object(), days=days,
                  codes=[1, 2], band=10, only_missing=False)
    assert set(filled) == {"2026-04-06", "2026-04-08"}  # both fetched
