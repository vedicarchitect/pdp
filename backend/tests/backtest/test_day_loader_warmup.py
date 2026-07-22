"""Unit test for day_loader.load_window's spot-only warmup prefix (bias-ranking-hardening).

A warmup window should load prior-day *spot* into ``spot_1m_by_day`` (so the bias engine's
higher-TF EMAs can converge for the first traded day) without ever trading those days: they must
not appear in ``valid_days`` and need no chain/expiry.

Uses fake Mongo-like collections (no MongoDB needed).
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from pdp.backtest.day_loader import load_window, warmup_prefix

_IST = timedelta(hours=5, minutes=30)


def _session_bars(d: date) -> list[dict]:
    """A full 09:15–15:29 IST session of 1m bars (375 bars → passes the completeness gate)."""
    start = datetime(d.year, d.month, d.day, 9, 15) - _IST  # store ts in UTC
    bars = []
    for i in range(375):
        px = 19_000.0 + i * 0.05
        ts = (start + timedelta(minutes=i)).replace(tzinfo=UTC)
        bars.append({"ts": ts, "open": px, "high": px + 1, "low": px - 1, "close": px, "volume": 1000})
    return bars


class _FakeSortedFind(list):
    def sort(self, *_a, **_k):
        return self


class _FakeMarketBarsCol:
    def __init__(self, by_day: dict[date, list[dict]]) -> None:
        self._by_day = by_day

    def find(self, query):
        lo = query["ts"]["$gte"]
        hi = query["ts"]["$lte"]
        out = [b for bars in self._by_day.values() for b in bars if lo <= b["ts"] <= hi]
        return _FakeSortedFind(out)


class _FakeOptionBarsCol:
    def __init__(self, expiries: list[date]) -> None:
        self._expiries = expiries

    def distinct(self, _field, _query):
        return list(self._expiries)

    def find(self, _query, _projection=None):
        return []


def _mdb(spot_by_day: dict[date, list[dict]], expiries: list[date]) -> dict:
    return {"market_bars": _FakeMarketBarsCol(spot_by_day), "option_bars": _FakeOptionBarsCol(expiries)}


def _weekdays_before(end: date, n: int) -> list[date]:
    days, d = [], end - timedelta(days=1)
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return list(reversed(days))


def test_warmup_days_load_spot_but_are_not_traded():
    trade_date = date(2026, 6, 2)  # a Tuesday
    warmup = _weekdays_before(trade_date, 10)
    spot_by_day = {d: _session_bars(d) for d in [*warmup, trade_date]}
    mdb = _mdb(spot_by_day, expiries=[trade_date])

    window = load_window(mdb, cal=None, days=[trade_date], underlying="NIFTY", warmup_days=warmup)

    # Warmup days' spot is loaded (so _prior_days_1m can warm the EMAs)...
    for d in warmup:
        assert d in window.spot_1m_by_day
    assert trade_date in window.spot_1m_by_day
    # ...but they are never traded.
    assert window.valid_days == [trade_date]
    for d in warmup:
        assert d not in window.valid_days
        assert d not in window.expiry_by_day


def test_no_warmup_days_is_backwards_compatible():
    trade_date = date(2026, 6, 2)
    spot_by_day = {trade_date: _session_bars(trade_date)}
    mdb = _mdb(spot_by_day, expiries=[trade_date])

    window = load_window(mdb, cal=None, days=[trade_date], underlying="NIFTY")  # no warmup_days

    assert window.valid_days == [trade_date]
    assert set(window.spot_1m_by_day) == {trade_date}


def test_warmup_prefix_is_business_days_before_first_day():
    """Shared helper every strangle backtest entry point uses (run/sweep/walk-forward) so they
    warm identically. Returns n weekdays strictly before days[0], oldest-first."""
    days = [date(2026, 6, 2), date(2026, 6, 3)]  # Tue, Wed
    pre = warmup_prefix(days, n=5)
    assert len(pre) == 5
    assert all(d.weekday() < 5 for d in pre)
    assert all(d < days[0] for d in pre)
    assert pre == sorted(pre)  # oldest-first
    assert pre[-1] == date(2026, 6, 1)  # Monday, the biz day immediately before the Tue window start


def test_warmup_prefix_empty_days_returns_empty():
    assert warmup_prefix([]) == []
