# strategy-config

## ADDED Requirements

### Requirement: Per-instrument indicator selection
The strategy configuration SHALL allow a watchlist entry to declare an optional `indicators`
list naming which indicator-suite families to compute for that entry's `security_id` and
timeframes, with optional per-family parameters (for example EMA periods or volume-profile
bucket size). When the list is absent or empty, no indicator-suite families SHALL be computed
for that entry. The indicator engine SHALL compute, per `(security_id, timeframe)`, the union
of families requested across all loaded strategies.

#### Scenario: Watchlist declares indicators
- **WHEN** a watchlist entry declares `indicators: [ema, rsi, vwap]` with periods for EMA
- **THEN** the engine computes EMA (for the given periods), RSI, and VWAP for that entry's
  `(security_id, timeframe)` and no other families

#### Scenario: No indicators declared
- **WHEN** a watchlist entry omits the `indicators` list
- **THEN** the engine computes no indicator-suite families for that entry
