## ADDED Requirements

### Requirement: Weekly bar aggregation

The bar aggregator SHALL produce `1w` (weekly) bars using ISO-week boundaries, and the bar writer SHALL
persist them to `market_bars` alongside the existing timeframes. Weekly bar open SHALL be the first
trade of the ISO week, high/low the week extremes, close the last trade, with volume summed.

#### Scenario: Weekly bar rolls at ISO-week boundary

- **WHEN** bars cross from one ISO week into the next
- **THEN** the prior week's `1w` bar is emitted with that week's open/high/low/close and persisted to `market_bars`

### Requirement: Weekly Camarilla pivots

The indicator engine SHALL compute pivot levels on the `1w` timeframe so `get_pivots(security_id, "1w")`
returns standard, Camarilla, and Fibonacci levels derived from the prior ISO-week HLC. Warmup SHALL seed
weekly pivots from `market_bars` so values are available on day one.

#### Scenario: Weekly Camarilla available after warmup

- **WHEN** the engine is warmed up with at least two ISO weeks of bars for an index
- **THEN** `get_pivots(sid, "1w")` returns non-null `cam_pp`, `cam_r3`, `cam_r4`, `cam_s3`, `cam_s4`

#### Scenario: Strangle weekly Camarilla no longer missing

- **WHEN** the directional strangle reads weekly Camarilla via `pivots(sid, "1w")`
- **THEN** it receives populated values and does not log `cam_weekly_missing`
