"""Unit tests for the session-anchored HLC helper in `pdp.indicators.levels_store`.

Regression coverage for the PMH bug (2026-07-14): the old per-period fetchers padded their
window and mixed `{"1D","1m"}` timeframes in one aggregate, letting an out-of-session pre-open
print (or an adjacent day's bar) inflate a period's high. `_session_window_hlc`/
`_session_anchored_hlc` replace that with a per-trading-day `[09:15,15:30)` IST window,
1-minute-only.

Uses a lightweight fake Motor collection (same pattern as `tests/test_warehouse_coverage.py`)
that actually evaluates the `$match`/`$group` semantics against in-memory 1m bars, rather than
returning canned output — so the test genuinely exercises the window-boundary math.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from pdp.indicators.levels_store import _fetch_month_hlc, _session_anchored_hlc, _session_window_hlc
from pdp.indicators.pivots import _compute_pivots


class _AsyncCursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for row in self._rows:
            yield row


class _FakeMarketBarsCollection:
    """Evaluates the real `$match`(ts range + tf)/`$group`(max/min/last) shape used by the
    session-anchored HLC helper against a fixed set of in-memory bar docs."""

    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def aggregate(self, pipeline: list[dict]):
        match = pipeline[0]["$match"]
        sid = match["metadata.security_id"]
        tf = match["metadata.timeframe"]
        lo = match["ts"]["$gte"]
        hi = match["ts"]["$lt"]
        rows = [
            d for d in self._docs
            if d["metadata"]["security_id"] == sid
            and d["metadata"]["timeframe"] == tf
            and lo <= d["ts"] < hi
        ]
        if not rows:
            return _AsyncCursor([])
        rows_sorted = sorted(rows, key=lambda d: d["ts"])
        agg = {
            "h": max(d["high"] for d in rows_sorted),
            "l": min(d["low"] for d in rows_sorted),
            "c": rows_sorted[-1]["close"],
        }
        return _AsyncCursor([agg])

    async def find_one(self, match: dict, sort=None):
        return None  # no 1D fallback docs in these tests


class _FakeDb:
    def __init__(self, market_bars: _FakeMarketBarsCollection) -> None:
        self._market_bars = market_bars

    def __getitem__(self, name: str) -> _FakeMarketBarsCollection:
        assert name == "market_bars"
        return self._market_bars


def _bar(day: date, hh: int, mm: int, high: float, low: float, close: float) -> dict:
    """A 1m NIFTY bar doc timestamped `hh:mm` UTC on `day`."""
    return {
        "ts": datetime(day.year, day.month, day.day, hh, mm, tzinfo=UTC),
        "metadata": {"security_id": "13", "timeframe": "1m"},
        "high": high,
        "low": low,
        "close": close,
    }


async def test_session_window_excludes_out_of_session_bad_tick() -> None:
    """A pre-open print (09:00 IST = 03:30 UTC) with a spuriously high value must not
    contribute to the day's high — regression test for the PMH=24361 bug."""
    day = date(2026, 6, 29)
    docs = [
        _bar(day, 3, 30, high=24361.1, low=24361.1, close=24361.1),  # 09:00 IST, pre-open
        _bar(day, 3, 45, high=24080.0, low=24070.0, close=24075.0),  # 09:15 IST, session open
        _bar(day, 4, 0, high=24090.0, low=24065.0, close=24085.0),
    ]
    db = _FakeDb(_FakeMarketBarsCollection(docs))

    h, lo, c = await _session_window_hlc(db, "13", day)

    assert h == 24090.0  # NOT 24361.1
    assert lo == 24065.0
    assert c == 24085.0


async def test_session_window_boundary_instants() -> None:
    """A tick at exactly 09:15:00 IST is included; a tick at exactly 15:30:00 IST is excluded —
    mirrors `bar-session-anchoring`'s own boundary-instant scenario."""
    day = date(2026, 6, 29)
    docs = [
        _bar(day, 3, 45, high=100.0, low=99.0, close=99.5),   # 09:15:00 IST exactly — included
        _bar(day, 10, 0, high=999.0, low=999.0, close=999.0),  # 15:30:00 IST exactly — excluded
    ]
    db = _FakeDb(_FakeMarketBarsCollection(docs))

    h, lo, c = await _session_window_hlc(db, "13", day)

    assert h == 100.0
    assert lo == 99.0
    assert c == 99.5


async def test_session_anchored_hlc_combines_multiple_days() -> None:
    """A multi-day (weekly/monthly) window takes max-of-highs, min-of-lows, and the latest
    day's close — combining independently-windowed per-day HLC, not one wide aggregate."""
    d1 = date(2026, 6, 25)
    d2 = date(2026, 6, 26)
    docs = [
        _bar(d1, 3, 45, high=24261.6, low=24000.0, close=24200.0),
        _bar(d2, 3, 45, high=24150.0, low=23900.0, close=24100.0),
    ]
    db = _FakeDb(_FakeMarketBarsCollection(docs))

    h, lo, c = await _session_anchored_hlc(db, "13", d1, d2)

    assert h == 24261.6
    assert lo == 23900.0
    assert c == 24100.0  # the later day's close


async def test_monthly_hlc_matches_true_session_high_not_pre_open_spike() -> None:
    """End-to-end regression for the PMH bug: a month containing both a legitimate high and
    an out-of-session pre-open spike resolves to the legitimate high."""
    legit_high_day = date(2026, 6, 25)
    spike_day = date(2026, 6, 29)
    docs = [
        _bar(legit_high_day, 3, 45, high=24261.6, low=24000.0, close=24200.0),
        _bar(spike_day, 3, 30, high=24361.1, low=24361.1, close=24361.1),  # pre-open, excluded
        _bar(spike_day, 3, 45, high=24080.0, low=24060.0, close=24070.0),  # in-session
    ]
    db = _FakeDb(_FakeMarketBarsCollection(docs))

    h, lo, _c = await _fetch_month_hlc(db, "13", date(2026, 6, 1), date(2026, 6, 30))

    assert h == 24261.6
    assert lo == 24000.0


def test_kite_camarilla_reading_is_internally_1_1_consistent() -> None:
    """Kite's real on-chart Camarilla Pivots, hand-confirmed by the user during Phase 0
    (R4=24266.36 / R3=24236.63 / S3=24177.17 / S4=24147.45), must satisfy the same fixed
    1.1-ratio spacing that `_compute_pivots`'s formula produces: R4-R3 == PP-S3 == S3-S4 ==
    rng*1.1/4 for a common rng, and R3+S3 == 2*PP. This doesn't require reconstructing the
    exact prior-session H/L/C (not recorded verbatim) — it independently confirms Kite's own
    numbers are self-consistent with the Camarilla formula `_compute_pivots` implements,
    which is what actually matters for validating the formula against a real chart."""
    r4, r3, s3, s4 = 24266.36, 24236.63, 24177.17, 24147.45

    step = r4 - r3  # rng*1.1/4
    assert s3 - s4 == pytest.approx(step, abs=0.05)
    pp = (r3 + s3) / 2.0
    assert pp - s3 == pytest.approx(step, abs=0.05)
    assert r4 - pp == pytest.approx(2 * step, abs=0.05)  # rng*1.1/2 == 2 * (rng*1.1/4)

    # Reconstruct the implied prior-session H/L/C from that consistent spacing and confirm
    # `_compute_pivots` reproduces the same four values (within Kite's own display rounding).
    rng = step * 4 / 1.1
    c = pp
    state = _compute_pivots(h=c + rng / 2, l=c - rng / 2, c=c, session_date=date(2026, 7, 13))

    assert state.cam_r4 == pytest.approx(r4, abs=0.05)
    assert state.cam_r3 == pytest.approx(r3, abs=0.05)
    assert state.cam_s3 == pytest.approx(s3, abs=0.05)
    assert state.cam_s4 == pytest.approx(s4, abs=0.05)


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
