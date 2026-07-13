# indicator-warmup Specification

## Purpose
TBD - created by archiving change live-supertrend-session-warmup. Update Purpose after archive.
## Requirements
### Requirement: Seed IndicatorEngine from historical bars on startup
The system SHALL provide a warmup path that loads the last N bars for a given
`(security_id, timeframe)` from the MongoDB `market_bars` collection and feeds them through the
`IndicatorEngine` in chronological order, so the tracker's ATR and direction are consistent with a
fully-warmed backtest simulation before the first live bar arrives. To keep the engine
DB-agnostic, the I/O orchestration lives in `pdp.indicators.warmup.warm_up_indicator_engine()`
(reads MongoDB, with an optional Dhan API top-up when fewer than `MIN_BARS` rows exist) and the
pure feeding lives in `IndicatorEngine.seed_from_bars()`, which processes an ascending-by-`ts`
list of bars through `on_bar()`. Warmup SHALL be callable after engine construction and before any
live bar is dispatched. If MongoDB returns no bars, warmup SHALL log a warning and return without
error (cold start is acceptable as a fallback).

#### Scenario: Warmup seeded before first live bar
- **WHEN** `warm_up_indicator_engine()` is invoked for `("13", "5m")` with prior bars in `market_bars`
- **THEN** the engine processes the prior bars through `on_bar()` and `get("13", "5m")` returns a non-None `SuperTrendState`

#### Scenario: No prior bars in MongoDB
- **WHEN** warmup finds no bars in the lookback window (and no Dhan top-up is available)
- **THEN** a warning is logged with `indicator_warmup_no_bars` and the engine remains in cold state (no crash)

#### Scenario: Warmup does not affect live bar timestamps
- **WHEN** seed bars with timestamps before `session_start` are processed during warmup
- **THEN** those bars do NOT produce any strategy signals; they only prime the indicator state

#### Scenario: Warmup bars ordered chronologically
- **WHEN** MongoDB returns bars in any order
- **THEN** warmup sorts them ascending by `ts` before feeding into `IndicatorEngine.seed_from_bars()`

### Requirement: Prior-session continuity on startup

The live indicator engine SHALL be seeded on startup such that each `SuperTrendTracker` carries the
direction established by the most recent prior trading session, so SuperTrend is continuous with the
chart (and the backtest) regardless of the time at which the process starts. The startup seed
lookback SHALL be **session-aware** — derived by walking back to the most recent prior trading day
over weekend and holiday (non-trading) gaps — rather than a fixed wall-clock window that the
overnight session gap can exceed. A continuously-running process SHALL NOT reset its trackers at the
day boundary.

#### Scenario: Mid-day restart inherits the prior-session direction

- **WHEN** the process starts during the trading session and the prior trading session closed in an
  established uptrend
- **THEN** the seeded SuperTrend direction is up (carried over), not a fresh cold-start seed

#### Scenario: Lookback walks back over a weekend or holiday

- **WHEN** the most recent prior trading day is separated from today by a weekend or holiday cluster
- **THEN** the warmup seeds from that prior trading session's bars, not from an empty or same-day-only
  window

#### Scenario: Continuously-running process stays continuous

- **WHEN** the process runs uninterrupted across a day boundary
- **THEN** the SuperTrend tracker is not reset and remains continuous, unaffected by the startup
  warmup path

### Requirement: Sufficient warmup history before the first live bar

The startup warmup SHALL ensure enough historical bars are seeded to establish a stable SuperTrend
direction — at least a full prior trading session — before the first live bar is processed. When the
local store holds too few bars to cover the prior session and a data provider is configured, the
warmup SHALL fetch the missing prior-session history from the provider and persist it; when no
provider is available, the tracker MAY cold-start, and this fallback SHALL be logged.

#### Scenario: Thin local store triggers a provider fetch

- **WHEN** the local store holds fewer bars than a full prior session and provider credentials are set
- **THEN** the warmup fetches the prior-session history from the provider, persists it, and seeds the
  tracker with it

#### Scenario: No provider falls back to cold start with a log

- **WHEN** the prior session is absent locally and no provider is available
- **THEN** the tracker cold-starts and the warmup logs that prior-session history was unavailable

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

