# Design: backtest-1m-resample

## Approach

Eliminate the divergent native-5m fetch path; all backtest bar data is now 1m→resample.

**Decision: shared resample helper in `src/pdp/backtest/resample.py`**

Three functions cover all call sites:
- `resample_ohlcv(bars, tf_minutes)` — tuples (ts, o, h, l, c, v)
- `resample_data_dict(data, tf_minutes)` — Dhan array-dict format (includes oi/iv)
- `resample_mongo_bars(docs, tf_minutes)` — MongoDB bar documents

All use aligned UTC-boundary grouping: open=first, high=max, low=min, close=last, volume=sum,
oi/iv=last. This matches `BarAggregator` semantics.

**Decision: MongoDB-first read at 1m; fall back gracefully**

NIFTY fetch order: 1m Mongo bars → resample → native 5m Mongo bars → Dhan API.
The warehouse stores 1m where available; resampled results are reused from cache.
The expired-options API fallback requests interval=1 and persists resampled 5m bars.

**Decision: `--native5m` escape hatch for parity testing**

A `--native5m` flag on `backtest_multiday.py` forces native 5m Mongo bars (skips 1m resample)
so a single day can be re-run to confirm bit-for-bit parity between the two paths.

## Validation

2026-06-10 run confirmed identical results: 37 trades, +42,692.00 net premium, same trade
sequence — whether using 1m-resampled (306 bars) or native 5m (62 bars).
