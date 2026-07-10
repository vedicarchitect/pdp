# bar-session-anchoring

## Why

The 30-minute and 1-hour bars the strategy trades on do not start when the market opens. They are
anchored to the Unix epoch, not to the 09:15 IST session open, so every multi-timeframe indicator
built on them is computed over the wrong candles.

`pdp/market/bars.py:49` truncates by minutes-since-epoch:

```python
def _bar_boundary(dt: datetime, tf_minutes: int) -> datetime:
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    total_minutes = int((dt - epoch).total_seconds() // 60)
    return epoch + timedelta(minutes=(total_minutes // tf_minutes) * tf_minutes)
```

The session opens at 09:15 IST = 03:45 UTC = 225 minutes past midnight. Bucketing the session-open
tick for each configured timeframe gives:

| TF | Bucket containing the 09:15 IST tick | Aligned? |
|----|--------------------------------------|----------|
| 5m | 09:15 | yes |
| 15m | 09:15 | yes |
| 25m | 09:15 / 09:00 / 09:10 / 08:55 on consecutive days | **no — drifts daily** |
| 30m | 09:00 | **no — off by 15 min** |
| 1H | 08:30 | **no — off by 45 min** |

(1440 minutes per day is divisible by 30 and 60, so those two are stably wrong; it is not divisible
by 25, so 25m walks by 15 minutes each calendar day.)

The consequences are exactly the discrepancies observed against Kite:

- Kite completes the first 30m candle at 09:45 (bucket 09:15–09:45). We complete ours at 09:30
  (bucket 09:00–09:30) — a bucket whose first 15 minutes are **pre-open** and whose last 15 minutes
  are the opening drive. Every subsequent 30m bar is offset by 15 minutes for the whole session.
- The 30m EMA(20/50) values reported in the app (24010 / 24073 / 24204) differ from Kite
  (24017 / 24063 / 24158) not because the EMA maths is wrong but because the OHLC inputs are
  different candles.
- The 1H series is worse: its first bucket, 08:30–09:30 IST, is 45 minutes of nothing followed by
  15 minutes of trading. Its open is the first tick after 09:15, its high/low cover a quarter of a
  real hourly bar.

Second, independent defect: **there is no session-window filter**. `BarAggregator.on_tick` buckets
whatever it is given. Pre-open ticks (Dhan streams from ~09:00 IST) and any post-close prints are
folded into the first and last bars. Even with correct anchoring, a 09:00 tick would open a
09:15-anchored bar 15 minutes early, and a `_bar_boundary_1d` day bar would carry pre-open prints in
its open.

Because these bars are persisted, the damage is in `market_bars` too. Warmup
(`pdp/indicators/warmup.py`) seeds `IndicatorEngine` from that collection, so a corrected aggregator
still boots into indicators computed over historically mis-anchored candles. The stored 15m/30m/1H
series has to be rebuilt.

## What Changes

- **Anchor intraday buckets to the session open.** `_bar_boundary` takes the session-open instant
  for the tick's IST trading day and truncates `(dt - session_open)` into `tf_minutes` buckets. 5m
  and 15m results are unchanged (they already coincide); 25m, 30m and 1H move onto Kite's grid.
  `_bar_boundary_1d` and `_bar_boundary_1w` already anchor on IST calendar boundaries and are left
  alone.

- **Filter to the session window.** `BarAggregator.on_tick` drops ticks outside
  `[09:15:00, 15:30:00)` IST for the tick's trading day. A tick at 09:14:59 never forms a bar; a
  tick at 15:30:00 belongs to no bucket. The final bucket of the day is closed by a session-end
  flush rather than by the arrival of a later tick, so the 15:00–15:30 bar exists even when the
  first tick of the next session is a day away.

- **Rebuild the stored series.** A one-off script re-derives 15m/30m/1H `market_bars` for every
  warehoused underlying by aggregating the **1-minute** series, which is dense and — being
  1-minute — already session-aligned by construction. This costs no Dhan API quota and is
  reproducible. 25m is rebuilt if any config uses it. The rebuild is delete-then-insert per
  `(security_id, timeframe)` because `market_bars` is a Mongo timeseries collection and cannot be
  updated in place.

- **Prove alignment with a test, not an eyeball.** A parametrised test asserts, for each configured
  timeframe, that the bucket containing the session-open tick *is* the session open, on several
  consecutive trading days including a Monday after a holiday.

## Impact

- **Affected specs:** `bar-session-anchoring` (new). Amends the behaviour described in
  `openspec/specs/market-feed/spec.md`.
- **Affected code:** `backend/pdp/market/bars.py` (`_bar_boundary`, `BarAggregator.on_tick`,
  session-end flush), `backend/pdp/market/CLAUDE.md`, new
  `backend/scripts/oneoff/rebuild_market_bars.py`.
- **Data migration required, and it is not reversible in place.** 15m/30m/1H (and 25m if used)
  rows for all warehoused underlyings are deleted and re-derived. Take a Mongo dump of `market_bars`
  first. The 1m series is the source of truth and is not touched.
- **Backtest results will move.** Any backtest that reads 30m/1H `market_bars` has been reading
  mis-anchored candles. Re-run the three strangle configs after the rebuild and compare against the
  archived baselines (NIFTY: +Rs 85.6L, PF 5.72) before trusting any subsequent strategy change.
  A materially different result is expected and is not, by itself, a regression.
- **Blocks `indicator-history-depth`.** Backfilling more history is pointless until the bars being
  backfilled are anchored correctly. Ties into [[execution_console_accuracy]] and
  [[live_backtest_parity]].
- **`market_bars` doc is stale.** `backend/pdp/market/CLAUDE.md` documents a top-level
  `security_id`; the collection is a timeseries keyed on `metadata.security_id` /
  `metadata.timeframe`. Correct it while here.
