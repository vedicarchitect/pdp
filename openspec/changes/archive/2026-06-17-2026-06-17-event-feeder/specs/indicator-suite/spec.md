## ADDED Requirements

### Requirement: period_levels indicator family

The universal `IndicatorEngine` SHALL provide a `period_levels` family producing previous-period high/low levels — previous-day (PDH/PDL), previous-week (PWH/PWL), and previous-month (PMH/PML) — as a `PeriodLevelsState`. The tracker SHALL follow the standard family protocol `update(high, low, close, volume, bar_time) -> PeriodLevelsState | None`, freeze each completed period's high/low at the corresponding day/ISO-week/calendar-month boundary, and be seedable from MongoDB `market_bars` during warmup. The family SHALL be reachable via `IndicatorEngine.get_period_levels(sid, tf)`, included in `Snapshot.period_levels`, registered in `registry.py`, and accessible from strategies via `IndicatorReader.period_levels(sid, tf)`.

#### Scenario: Previous-week high/low frozen at week boundary
- **WHEN** the first bar of a new ISO week is processed
- **THEN** `PeriodLevelsState.pwh` / `pwl` reflect the prior week's accumulated high/low and remain constant for the duration of the new week

#### Scenario: Previous-month high/low frozen at month boundary
- **WHEN** the first bar of a new calendar month is processed
- **THEN** `PeriodLevelsState.pmh` / `pml` reflect the prior month's high/low

#### Scenario: Seeded from warmup
- **WHEN** the engine warms up from MongoDB `market_bars` for a security/timeframe with at least one prior week and month of data
- **THEN** `get_period_levels` returns populated PWH/PWL/PMH/PML before the first live bar

#### Scenario: Available in snapshot
- **WHEN** `get_snapshot(sid, tf)` is called after `period_levels` is configured
- **THEN** the returned `Snapshot.period_levels` is a populated `PeriodLevelsState` (or `None` if not yet seeded)

#### Scenario: Strategies can read period levels
- **WHEN** a strategy calls `ctx.indicators.period_levels(sid, tf)`
- **THEN** the `PeriodLevelsState` is returned without error
