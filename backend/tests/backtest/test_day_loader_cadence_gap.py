"""Unit tests for day_loader.load_window's expiry-cadence-gap wiring.

Uses fake Mongo-like collections (no MongoDB needed) so the test only exercises the pure
expiry-resolution logic in ``load_window`` — chain/spot loading is stubbed to empty.
"""
from __future__ import annotations

from datetime import date

from pdp.backtest.day_loader import load_window


class _FakeSortedFind(list):
    def sort(self, *_args, **_kwargs):
        return self


class _FakeMarketBarsCol:
    def find(self, _query):
        return _FakeSortedFind([])


class _FakeOptionBarsCol:
    def __init__(self, expiries: list[date]) -> None:
        self._expiries = expiries

    def distinct(self, _field, _query):
        return list(self._expiries)

    def find(self, _query, _projection=None):
        return []


class _FakeMdb(dict):
    pass


def _mdb(expiries: list[date]) -> _FakeMdb:
    mdb = _FakeMdb()
    mdb["market_bars"] = _FakeMarketBarsCol()
    mdb["option_bars"] = _FakeOptionBarsCol(expiries)
    return mdb


def test_days_inside_a_cadence_gap_are_flagged():
    # NIFTY real expiries with a missing 2023-02-16 weekly (the exact NSE-confirmed gap from the
    # proposal's spot-check) — 2023-02-02 -> 2023-02-23 is a 21-day cadence gap.
    real_expiries = [date(2023, 2, 2), date(2023, 2, 23), date(2023, 3, 2)]
    mdb = _mdb(real_expiries)
    days = [date(2023, 2, 3), date(2023, 2, 9), date(2023, 2, 16), date(2023, 2, 23)]

    window = load_window(mdb, cal=None, days=days, underlying="NIFTY")

    # Days strictly inside the gap resolve to the far-side expiry and are flagged.
    assert window.cadence_gap_days == {date(2023, 2, 3), date(2023, 2, 9), date(2023, 2, 16)}
    for d in (date(2023, 2, 3), date(2023, 2, 9), date(2023, 2, 16)):
        assert window.expiry_by_day[d] == date(2023, 2, 23)
    # The real expiry day itself is a legitimate trade day, not a gap artifact.
    assert date(2023, 2, 23) not in window.cadence_gap_days
    assert window.expiry_by_day[date(2023, 2, 23)] == date(2023, 2, 23)


def test_normal_weekly_cadence_flags_nothing():
    real_expiries = [date(2023, 2, 2), date(2023, 2, 9), date(2023, 2, 16)]
    mdb = _mdb(real_expiries)
    days = [date(2023, 2, 3), date(2023, 2, 9)]

    window = load_window(mdb, cal=None, days=days, underlying="NIFTY")

    assert window.cadence_gap_days == set()
