# dhan-same-day-data Specification

## Purpose
TBD - created by archiving change dhan-same-day-data. Update Purpose after archive.
## Requirements
### Requirement: An incomplete candle SHALL NOT be persisted or seeded into an indicator

Any bar whose period has not yet elapsed at the time of retrieval SHALL be discarded. It SHALL NOT be
written to `market_bars` and SHALL NOT be fed to an indicator tracker. This SHALL hold for every
retrieval path, including broker historical fetches performed during market hours.

#### Scenario: Warmup during market hours

- **WHEN** warmup fetches candles at 11:07 IST and the broker returns a 5-minute candle stamped 11:05
- **THEN** that candle is discarded, is not persisted, and does not seed any tracker

#### Scenario: Warmup after the close

- **WHEN** warmup fetches candles at 16:00 IST
- **THEN** every candle of the session, including the 15:25 candle, is complete and is retained

#### Scenario: The stored series contains no partial bars

- **WHEN** `market_bars` is audited for any timeframe
- **THEN** no document exists whose bar period had not elapsed at its write time

### Requirement: The current session's bars SHALL be complete before a strategy trades

After an intraday restart, the platform SHALL reconstruct the current session's bar series in full
for every configured timeframe, or SHALL report the gap as a blocking readiness condition. An
indicator SHALL NOT be advanced across a known hole in its input series.

#### Scenario: Restart with a reconstructable session

- **WHEN** the backend restarts at 11:00 IST and the current session's bars can be reconstructed
- **THEN** the indicator engine resumes with a contiguous series and the strategy is ready

#### Scenario: Restart with an irreparable gap

- **WHEN** the current session's bars cannot be reconstructed for a configured timeframe
- **THEN** the readiness report marks the strategy blocked, naming the timeframe and the missing interval

#### Scenario: Indicators are never advanced across a hole

- **WHEN** a gap is detected between the last seeded bar and the first live bar
- **THEN** the tracker is not updated with the discontinuous bar and the gap is reported

### Requirement: Trading-day boundaries SHALL be computed from the IST timezone

Code that derives an Indian trading date SHALL use the `Asia/Kolkata` timezone rather than a
hard-coded UTC offset.

#### Scenario: Late-evening UTC maps to the next IST day

- **WHEN** the current instant is 19:30 UTC on 2026-07-09
- **THEN** the derived trading date is 2026-07-10

#### Scenario: Boundary instants

- **WHEN** the current instant is 18:29 UTC and again at 18:31 UTC on 2026-07-09
- **THEN** the derived trading dates are 2026-07-09 and 2026-07-10 respectively

