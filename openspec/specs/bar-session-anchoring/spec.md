# bar-session-anchoring Specification

## Purpose
TBD - created by archiving change bar-session-anchoring. Update Purpose after archive.
## Requirements
### Requirement: Intraday bar buckets SHALL be anchored to the trading session open

For every intraday timeframe, the bucket boundary SHALL be computed as an offset from 09:15 IST on
the tick's trading day, not from the Unix epoch. The bucket containing the first tick of a session
SHALL begin exactly at the session open, for every configured timeframe and on every trading day.

#### Scenario: 30-minute bars align with the session open

- **WHEN** the first tick of the session arrives at 09:15:01 IST
- **THEN** its 30m bucket starts at 09:15 IST and closes at 09:45 IST

#### Scenario: 1-hour bars align with the session open

- **WHEN** the first tick of the session arrives at 09:15:01 IST
- **THEN** its 1H bucket starts at 09:15 IST and closes at 10:15 IST

#### Scenario: 25-minute bars do not drift across days

- **WHEN** the session-open tick is bucketed on four consecutive trading days at the 25m timeframe
- **THEN** every bucket starts at 09:15 IST

#### Scenario: 5m and 15m bars are unchanged

- **WHEN** ticks are bucketed at 5m and 15m under the new anchoring
- **THEN** every bucket boundary equals the boundary produced by the previous epoch-anchored implementation

#### Scenario: Day and week bars keep their IST calendar anchoring

- **WHEN** a tick is bucketed at the 1D or 1w timeframe
- **THEN** the boundary is the IST calendar-day start, or Monday 00:00 IST, as before

### Requirement: Ticks outside the trading session SHALL NOT form bars

`BarAggregator` SHALL discard any tick whose IST timestamp falls outside `[09:15:00, 15:30:00)` on a
trading day. No pre-open, post-close or out-of-hours print SHALL contribute to any bar's open, high,
low, close, volume or open interest.

#### Scenario: Pre-open tick is discarded

- **WHEN** a tick arrives at 09:05 IST
- **THEN** no bar is created or updated for any timeframe

#### Scenario: Post-close tick is discarded

- **WHEN** a tick arrives at 15:31 IST
- **THEN** no bar is created or updated for any timeframe

#### Scenario: The final bar of the session is closed by a flush

- **WHEN** the session ends at 15:30 IST with an open 15:00–15:30 bucket
- **THEN** that bar is emitted as closed at 15:30 IST without waiting for a subsequent tick

#### Scenario: Boundary instants

- **WHEN** ticks arrive at exactly 09:15:00 and exactly 15:30:00 IST
- **THEN** the 09:15:00 tick is included in the first bucket and the 15:30:00 tick is discarded

### Requirement: Stored 15m/30m/1H bars SHALL be rebuilt from the 1-minute series

A one-off rebuild SHALL re-derive the 15m, 30m and 1H `market_bars` series for every warehoused
underlying by aggregating the stored 1-minute bars under the corrected anchoring. The rebuild SHALL
be idempotent, SHALL delete then insert per `(security_id, timeframe)` because `market_bars` is a
Mongo timeseries collection, and SHALL NOT modify the 1-minute series.

#### Scenario: Rebuild is idempotent

- **WHEN** the rebuild script runs twice for the same underlying and timeframe
- **THEN** the resulting document set is identical after each run

#### Scenario: Rebuilt bars match live aggregation

- **WHEN** a session's 1-minute bars are replayed through `BarAggregator` and separately rebuilt by the script
- **THEN** the resulting 30m OHLCV bars are identical

#### Scenario: The 1-minute series is preserved

- **WHEN** the rebuild completes
- **THEN** the count and content of 1m documents for that security are unchanged

#### Scenario: Warmup reads corrected bars

- **WHEN** `warm_up_indicator_engine()` runs after the rebuild
- **THEN** the 30m EMA seeded from `market_bars` equals the EMA computed from Kite's 30m candles for the same window

