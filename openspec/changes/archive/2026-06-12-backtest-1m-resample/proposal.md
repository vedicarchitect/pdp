## Why

The live platform builds every timeframe (1m/5m/15m/30m/1H) **simultaneously from the raw tick
stream** — there is no native 5m feed. The backtest, however, fetches 5m option/index bars
**directly** from Dhan (`intraday_minute_data(interval=5)`). This is a second, divergent data
path: a native-5m bar can differ from a 5m bar built by aggregating 1m bars (boundary handling,
gap-filling, last-tick semantics), so the backtest is not replaying the same series the live
engine would have produced. The user's stated intent is to **fetch 1-minute bars and resample**
to the required timeframe, so backtest and live share one bar-construction rule.

## What Changes

- Change the backtest data fetch to request **1-minute** bars from the source
  (`intraday_minute_data(interval=1)` / the expired-options 1m series) and **resample** them to
  the signal timeframe (5m and any other required timeframe) in code.
- Resampling SHALL use standard OHLCV aggregation on aligned UTC boundaries: open = first,
  high = max, low = min, close = last, volume = sum — matching `BarAggregator` semantics.
- Apply the same 1m→target resample to both the NIFTY index series and the option series.
- Preserve the MongoDB-first read path; the warehouse stores 1m where available and resampling
  happens after the read, so cached data is reused.

## Capabilities

### Modified Capabilities

- `backtest`: historical bar replay sources 1-minute bars and resamples to the signal timeframe.

## Impact

- Touches `backtest_multiday.py` (`fetch_bars`, `fetch_nifty`, and the per-day simulate read path).
- Aligns backtest bar construction with the live `BarAggregator`; results become directly
  comparable to paper trading.
- Slightly more data per request (1m vs 5m); acceptable for intraday windows.
