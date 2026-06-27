"""Unit tests for the batch option-chain pre-loader.

The loader is a pure function over a Mongo-like ``col.find(...)`` call, so these tests use a
fake collection (no MongoDB needed): they assert one query per expiry, IST trade-day bucketing,
1m→tf_min resampling, and the in-memory exact / nearest-strike lookup.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

from pdp.backtest.chain_loader import load_expiry_chain, lookup_strike


class _FakeCol:
    """Minimal stand-in: records the query and returns pre-canned docs."""

    def __init__(self, docs):
        self._docs = docs
        self.queries: list[dict] = []

    def find(self, query, projection=None):
        self.queries.append(query)
        return list(self._docs)


def _bar(ts_utc, strike, opt, o, h, lo, c):
    return {"ts": ts_utc, "strike": strike, "option_type": opt,
            "open": o, "high": h, "low": lo, "close": c}


def test_one_query_groups_and_resamples():
    # Two 1m bars in the same 5m bucket (IST 09:15, 09:16 = UTC 03:45, 03:46) for one contract.
    docs = [
        _bar(datetime(2026, 6, 9, 3, 45, tzinfo=UTC), 25000.0, "CE", 10, 12, 9, 11),
        _bar(datetime(2026, 6, 9, 3, 46, tzinfo=UTC), 25000.0, "CE", 11, 15, 8, 14),
    ]
    col = _FakeCol(docs)
    store, n = load_expiry_chain(col, date(2026, 6, 9), [date(2026, 6, 9)], tf_min=5)

    assert n == 1
    assert len(col.queries) == 1
    q = col.queries[0]
    assert q["underlying"] == "NIFTY" and q["timeframe"] == "1m"
    assert q["expiry_date"] == datetime(2026, 6, 9, tzinfo=UTC)

    bars = store[(date(2026, 6, 9), "CE")][25000.0]
    assert len(bars) == 1                     # both 1m bars collapse into one 5m bar
    dt, o, h, lo, c = bars[0]
    assert dt == datetime(2026, 6, 9, 9, 15)  # IST-naive bucket start
    assert (o, h, lo, c) == (10, 15, 8, 14)   # open=first, high=max, low=min, close=last


def test_buckets_by_ist_trade_date_and_strike():
    docs = [
        _bar(datetime(2026, 6, 9, 3, 45, tzinfo=UTC), 25000.0, "CE", 10, 10, 10, 10),
        _bar(datetime(2026, 6, 10, 3, 45, tzinfo=UTC), 25050.0, "PE", 20, 20, 20, 20),
    ]
    store, _ = load_expiry_chain(_FakeCol(docs), date(2026, 6, 10),
                                 [date(2026, 6, 9), date(2026, 6, 10)], tf_min=5)
    assert set(store) == {(date(2026, 6, 9), "CE"), (date(2026, 6, 10), "PE")}
    assert list(store[(date(2026, 6, 9), "CE")]) == [25000.0]
    assert list(store[(date(2026, 6, 10), "PE")]) == [25050.0]


def test_empty_trade_dates_issues_no_query():
    col = _FakeCol([])
    store, n = load_expiry_chain(col, date(2026, 6, 9), [], tf_min=5)
    assert store == {} and n == 0
    assert col.queries == []


def test_lookup_exact_then_nearest():
    store = {
        (date(2026, 6, 9), "CE"): {
            25000.0: [(datetime(2026, 6, 9, 9, 15), 1, 1, 1, 1)],
            25100.0: [(datetime(2026, 6, 9, 9, 15), 2, 2, 2, 2)],
        }
    }
    # Exact hit.
    s, bars = lookup_strike(store, date(2026, 6, 9), "CE", 25000.0, band=10, step=50)
    assert s == 25000.0 and bars[0][1] == 1
    # Missing 25050 -> nearest within band is 25100 (+1 step before -1 step).
    s, bars = lookup_strike(store, date(2026, 6, 9), "CE", 25050.0, band=10, step=50)
    assert s == 25100.0 and bars[0][1] == 2
    # Nothing for PE that day.
    assert lookup_strike(store, date(2026, 6, 9), "PE", 25000.0, band=10, step=50) == (None, [])
    # Outside band.
    assert lookup_strike(store, date(2026, 6, 9), "CE", 30000.0, band=2, step=50) == (None, [])
