## ADDED Requirements

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
