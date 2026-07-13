## ADDED Requirements

### Requirement: Daily-timeframe and deep multi-timeframe warmup

The warmup path SHALL seed the `1D` timeframe for the index security ids so the monitor
matrix and the daily market-structure detectors have a populated 1D snapshot at startup,
even though a `1D` bar never closes during the trading session. Because the intraday
minute endpoint does not serve daily candles, warmup SHALL fetch 1D history from the data
provider's daily-candles API (`historical_daily_data`) and persist it to `market_bars` so
subsequent restarts read from the store. Weekly and monthly seeds MAY be synthesised from
the fetched 1D bars.

Warmup SHALL seed enough history per timeframe that EMA(100) is fully established before
the first live bar — at least 100 bars for the `15m`, `1H`, and `1D` timeframes — by
deepening the per-timeframe lookback window accordingly.

#### Scenario: 1D snapshot seeded at startup

- **WHEN** `warm_up_indicator_engine()` runs for `("13", "1D")` and the provider daily-candles API is available
- **THEN** warmup fetches and persists 1D bars and `get("13", "1D")` returns a non-None SuperTrend/EMA/PSAR snapshot

#### Scenario: EMA100 fully seeded on higher timeframes

- **WHEN** warmup completes for `("13", "15m")`, `("13", "1H")`, and `("13", "1D")`
- **THEN** at least 100 bars were fed for each and `get_ema` returns a non-null value for period 100

#### Scenario: 1D warmup no longer unsupported

- **WHEN** warmup runs for a `1D` timeframe
- **THEN** it does not log `indicator_warmup_unsupported_tf` for that timeframe
