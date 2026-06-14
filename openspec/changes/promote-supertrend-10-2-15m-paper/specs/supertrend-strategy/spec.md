## ADDED Requirements

### Requirement: Settings-driven SuperTrend parameters

The universal `IndicatorEngine` SHALL read its SuperTrend period and multiplier from settings
(`SUPERTREND_PERIOD`, `SUPERTREND_MULTIPLIER`) rather than hardcoded constants, so the signal can be
retuned without code edits, defaulting to period 10 / multiplier 2.

#### Scenario: Engine uses configured SuperTrend parameters
- **WHEN** the application starts and constructs the `IndicatorEngine`
- **THEN** the engine's SuperTrend trackers use `SUPERTREND_PERIOD` and `SUPERTREND_MULTIPLIER` from settings
- **AND** with defaults unset the engine computes SuperTrend(10, 2)

### Requirement: Promoted default signal configuration

The `supertrend_short` paper strategy SHALL run on the 15-minute signal timeframe with OTM-1 strike
selection and per-leg / day stops of 3,000 / 20,000, this being the backtest-promoted configuration.

#### Scenario: Strategy subscribes and signals on 15m
- **WHEN** the strategy is loaded from `strategies/supertrend_short.yaml`
- **THEN** its watchlist and `params.timeframe` are `15m`
- **AND** `on_bar` only acts on closed 15-minute NIFTY bars

#### Scenario: Promoted risk limits applied
- **WHEN** the strategy evaluates its per-leg and day stops
- **THEN** the per-leg stop is 3,000 per current lot and the day stop is 20,000 of today's realized P&L
