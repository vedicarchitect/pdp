## MODIFIED Requirements

### Requirement: Signal-aligned option selling
The strategy SHALL, on each closed signal-timeframe bar, sell an out-of-the-money option of
the nearest weekly expiry aligned with the current SuperTrend direction: short PE when the
trend is up (green), short CE when the trend is down (red). On process restart during the
same trading day, the strategy SHALL recover any open leg from the positions table before
processing bars, so recovered state is treated identically to state built up from live fills.

#### Scenario: Open short PE on uptrend
- **WHEN** there is no open leg and SuperTrend direction is up
- **THEN** the strategy sells the configured OTM PE at the starting lot size

#### Scenario: Open short CE on downtrend
- **WHEN** there is no open leg and SuperTrend direction is down
- **THEN** the strategy sells the configured OTM CE at the starting lot size

#### Scenario: Restart recovers open leg before first bar
- **WHEN** the strategy starts and a non-zero short position tagged to it exists in the positions table for today
- **THEN** `_current` is populated from that position before `on_bar()` is called for the first time, and the strategy does not re-enter the same instrument
