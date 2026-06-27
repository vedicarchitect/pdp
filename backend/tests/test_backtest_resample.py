"""Tests for 1-minute -> signal-timeframe resampling used by the backtest."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pdp.backtest.resample import (
    resample_data_dict,
    resample_mongo_bars,
    resample_ohlcv,
)


def _minutes_ist(n: int) -> datetime:
    # IST-naive 1-minute timestamps starting 09:30.
    return datetime(2026, 6, 10, 9, 30) + timedelta(minutes=n)


def test_resample_ohlcv_aggregates_one_bucket():
    # Five 1-minute bars 09:30..09:34 -> a single 5m bar at 09:30.
    bars = [
        (_minutes_ist(0), 100.0, 101.0, 99.0, 100.5),
        (_minutes_ist(1), 100.5, 103.0, 100.0, 102.0),
        (_minutes_ist(2), 102.0, 102.5, 98.0, 99.0),
        (_minutes_ist(3), 99.0, 100.0, 97.0, 98.5),
        (_minutes_ist(4), 98.5, 99.5, 98.0, 99.2),
    ]
    out = resample_ohlcv(bars, 5)
    assert len(out) == 1
    dt, o, h, lo, c = out[0]
    assert dt == _minutes_ist(0)        # boundary = first bar's bucket start
    assert o == 100.0                   # open = first
    assert h == 103.0                   # high = max
    assert lo == 97.0                   # low = min
    assert c == 99.2                    # close = last


def test_resample_ohlcv_splits_on_boundary():
    # 09:34 and 09:35 fall in different 5m buckets.
    bars = [
        (_minutes_ist(4), 10.0, 12.0, 9.0, 11.0),
        (_minutes_ist(5), 11.0, 13.0, 10.5, 12.5),
    ]
    out = resample_ohlcv(bars, 5)
    assert [b[0] for b in out] == [_minutes_ist(0), _minutes_ist(5)]
    assert out[0][1] == 10.0 and out[0][4] == 11.0
    assert out[1][1] == 11.0 and out[1][4] == 12.5


def test_resample_ohlcv_passthrough_for_1m():
    bars = [(_minutes_ist(0), 1.0, 1.0, 1.0, 1.0)]
    assert resample_ohlcv(bars, 1) == bars


def test_resample_data_dict_sums_volume_and_keeps_last_oi_iv():
    base = int(datetime(2026, 6, 10, 4, 0, tzinfo=UTC).timestamp())  # 09:30 IST
    data = {
        "timestamp": [base + 60 * i for i in range(6)],          # 6 one-minute bars
        "open":   [100, 101, 102, 103, 104, 200],
        "high":   [110, 111, 112, 113, 114, 210],
        "low":    [90, 91, 92, 93, 94, 190],
        "close":  [101, 102, 103, 104, 105, 201],
        "volume": [10, 10, 10, 10, 10, 7],
        "oi":     [1, 2, 3, 4, 5, 9],
        "iv":     [0.1, 0.2, 0.3, 0.4, 0.5, 0.9],
    }
    out = resample_data_dict(data, 5)
    # First five minutes -> bucket 1; sixth minute -> bucket 2.
    assert out["open"] == [100, 200]
    assert out["high"] == [114, 210]
    assert out["low"] == [90, 190]
    assert out["close"] == [105, 201]
    assert out["volume"] == [50, 7]      # summed within the bucket
    assert out["oi"] == [5, 9]           # last in bucket
    assert out["iv"] == [0.5, 0.9]       # last in bucket
    assert out["timestamp"][0] == base   # aligned to bucket start


def test_resample_mongo_bars_aggregates():
    base = datetime(2026, 6, 10, 4, 0, tzinfo=UTC)
    docs = [
        {"ts": base + timedelta(minutes=i), "open": 100 + i, "high": 110 + i,
         "low": 90 - i, "close": 101 + i}
        for i in range(5)
    ]
    out = resample_mongo_bars(docs, 5)
    assert len(out) == 1
    bar = out[0]
    assert bar["ts"] == base            # bucket start
    assert bar["open"] == 100           # first
    assert bar["high"] == 114           # max (110+4)
    assert bar["low"] == 86             # min (90-4)
    assert bar["close"] == 105          # last (101+4)


def test_resample_matches_bar_builder_semantics():
    """The resampled OHLCV must equal what the live BarBuilder yields from the same ticks.

    Feed 1-minute closes as ticks into a 5m BarBuilder and compare against resampling the
    equivalent 1-minute bars.
    """
    from decimal import Decimal

    from pdp.market.bars import BarBuilder
    from pdp.market.models import Tick

    builder = BarBuilder("13", "5m")
    bars_1m = []
    closed = None
    # Six 1-minute ticks 09:30..09:35; the 09:35 tick closes the 09:30 5m bar.
    for i in range(6):
        ltt = datetime(2026, 6, 10, 4, 0, tzinfo=UTC) + timedelta(minutes=i)
        price = Decimal(str(100 + i))
        result = builder.push(Tick(security_id="13", exchange_segment="IDX_I",
                                   ltp=price, ltt=ltt, volume=1, oi=0))
        if result is not None:
            closed = result
        # One synthetic 1-minute bar per tick (o=h=l=c=price) for the resampler.
        bars_1m.append(((ltt + timedelta(hours=5, minutes=30)).replace(tzinfo=None),
                        float(price), float(price), float(price), float(price)))

    assert closed is not None
    resampled = resample_ohlcv(bars_1m[:5], 5)[0]  # first five minutes form the closed 5m bar
    _, o, h, lo, c = resampled
    assert (o, h, lo, c) == (
        float(closed.open), float(closed.high), float(closed.low), float(closed.close)
    )
