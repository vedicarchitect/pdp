## ADDED Requirements

### Requirement: Strategy configs SHALL declare every indicator period the platform reports

An indicator period that is rendered by the execution console or consumed by a strategy SHALL be
declared in that strategy's watchlist configuration. The live and backtest configurations for the
same strategy SHALL declare identical indicator families and periods.

#### Scenario: EMA 200 is configured

- **WHEN** the execution console requests EMA(200) for a watched security and timeframe
- **THEN** the period is present in the strategy's `ema` family configuration and a value can be produced

#### Scenario: Live and backtest configs agree

- **WHEN** the live and backtest configurations for a strangle underlying are compared
- **THEN** their `ema` periods and indicator families are identical

### Requirement: The warmup window SHALL be derived from the configured indicator periods

Warmup SHALL compute the required bar count for each `(security_id, timeframe)` as at least five
times the largest configured period across all indicator families, with a floor of 200 bars, and
SHALL convert that to a calendar lookback using the per-timeframe session-bar rate plus a
weekend/holiday pad. The hand-maintained `_TF_WARMUP_CALENDAR_DAYS` table SHALL be removed. An
unconfigured timeframe SHALL raise rather than default to a one-day lookback.

#### Scenario: A longer period widens the window automatically

- **WHEN** a config's largest EMA period changes from 100 to 200
- **THEN** the warmup lookback for that timeframe doubles with no source change to the warmup module

#### Scenario: Unknown timeframe

- **WHEN** warmup encounters a timeframe absent from the session-bar rate table
- **THEN** it raises with the offending timeframe named, rather than warming up on one calendar day

#### Scenario: Floor applies to short periods

- **WHEN** the largest configured period is 14
- **THEN** the required bar count is 200, not 70

### Requirement: Stored bar history SHALL reach the depth the indicators require

For every warehoused underlying and configured timeframe, `market_bars` SHALL hold at least the
required bar count. Backfill SHALL derive 15m/30m/1H from the stored 1-minute series wherever 1m
coverage exists and SHALL fall back to broker historical data only for windows lacking 1m coverage.

#### Scenario: Depth is met from the 1-minute series

- **WHEN** backfill runs for a timeframe with complete 1m coverage over the required window
- **THEN** no broker historical API call is made

#### Scenario: Depth is reported when it cannot be met

- **WHEN** backfill cannot reach the required bar count for a `(security_id, timeframe)`
- **THEN** it reports bars found and bars needed, and exits non-zero

### Requirement: An indicator SHALL NOT report a value before it has converged

A tracker SHALL omit a period from its state until it has consumed at least that many bars. Warmup
SHALL emit exactly one `indicator_warmup_short` warning per `(security_id, timeframe, family)` that
could not reach its required depth, naming bars found and bars needed.

#### Scenario: Unconverged EMA is omitted, not approximated

- **WHEN** an EMA(200) tracker has consumed 150 bars
- **THEN** `values` contains no key `200`, and the console renders `--`

#### Scenario: Converged EMA is reported

- **WHEN** an EMA(200) tracker has consumed 200 bars
- **THEN** `values[200]` is present

#### Scenario: Short warmup is logged once

- **WHEN** warmup finds 150 of 1000 required 30m bars for a security
- **THEN** exactly one `indicator_warmup_short` warning is emitted for that `(sid, 30m, ema)` carrying both counts

### Requirement: Startup SHALL summarise indicator seeding for every strategy

On startup, after warmup, the platform SHALL log one summary per strategy listing which
`(security_id, timeframe, family, period)` combinations are fully seeded and which are not, so that
a session beginning with an unseeded indicator is evident from the log without inspecting the UI.

#### Scenario: A session starts with an unseeded indicator

- **WHEN** the strategy host finishes warmup with EMA(200) unseeded on the 1H timeframe
- **THEN** the startup summary names that combination as unseeded

#### Scenario: A fully seeded session

- **WHEN** every configured combination is fully seeded
- **THEN** the summary reports zero unseeded combinations
