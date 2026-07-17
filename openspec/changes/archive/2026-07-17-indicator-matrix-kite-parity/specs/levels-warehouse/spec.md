## MODIFIED Requirements

### Requirement: Persisted pivot/levels warehouse

The system SHALL persist computed price levels in a MongoDB collection `index_levels`, one document per
`(security_id, period, session_date)`, where `period` is `daily`, `weekly`, or `monthly`. Each document
SHALL contain `schema_version`, `security_id`, `underlying`, `period`, `session_date` (the session the
levels apply to), a `source` object (`h`, `l`, `c`, `window_start`, `window_end` of the prior
session/week/month), `standard` (pp/r1/r2/r3/s1/s2/s3), `camarilla` (pp/r3/r4/s3/s4), `fibonacci`
(pp/r1/r2/r3/s1/s2/s3), an open `levels` map reserved for future families, and `computed_at`. The
collection SHALL be a regular (non-time-series) collection with a unique index on
`(security_id, period, session_date)` and a secondary index on `(underlying, period, session_date)`.
Writes SHALL be idempotent upserts.

Level math SHALL reuse `pdp.indicators.pivots._compute_pivots`; the warehouse MUST NOT introduce a
second pivot implementation.

The source HLC for every period (`daily`, `weekly`, `monthly`) SHALL be computed by one shared,
session-anchored helper: for each trading day in the period's window, only ticks/bars within
`[09:15:00, 15:30:00)` IST contribute to that day's high/low/close, and the period's HLC is the
aggregate across those per-day session windows. The helper SHALL derive this from the 1-minute
`market_bars` series and MUST NOT aggregate `$max`/`$min` over a mixed set of timeframes (e.g.
`{"1D","1m"}` together) — doing so risks an out-of-session print (pre-open auction, post-close) or
an adjacent day's bar leaking into the window. A stored `1D` bar for a day MAY be used as a fallback
HLC source only when that day has no 1-minute bars at all.

#### Scenario: Daily levels stored from prior session HLC

- **WHEN** the daily compute runs for NIFTY with the prior trading day's HLC
- **THEN** `index_levels` contains a `period:"daily"` document for the next trading session with populated `standard`, `camarilla`, and `fibonacci`

#### Scenario: Weekly levels stored from prior week HLC

- **WHEN** the weekly compute runs for an index using the prior ISO-week aggregated HLC
- **THEN** `index_levels` contains a `period:"weekly"` document whose `source.window_start`/`window_end` span that ISO week

#### Scenario: Monthly levels stored from prior month HLC

- **WHEN** the monthly compute runs for an index using the prior calendar-month aggregated HLC
- **THEN** `index_levels` contains a `period:"monthly"` document whose `source.window_start`/`window_end` span that calendar month and whose `camarilla` is populated

#### Scenario: Idempotent re-run

- **WHEN** the compute runs twice for the same `(security_id, period, session_date)`
- **THEN** exactly one document exists for that key (upserted, not duplicated)

#### Scenario: Out-of-session prints excluded from monthly HLC

- **WHEN** the 1-minute series for a month contains a tick timestamped outside `[09:15:00, 15:30:00)` IST on its trading day (e.g. a pre-open auction print)
- **THEN** that tick's high/low value does NOT contribute to the month's `source.h`/`source.l`, even if it exceeds every in-session value that month

#### Scenario: Monthly high matches the true session high

- **WHEN** a month's highest in-session 1-minute high is `24261.6` and a pre-open print earlier that month recorded `24361.1`
- **THEN** the monthly `source.h` is `24261.6`, not `24361.1`

### Requirement: Five-year levels backfill

The system SHALL provide `scripts/backfill_levels.py`, runnable as `task backfill:levels`, that
backfills daily, weekly, **and monthly** levels for NIFTY/BANKNIFTY/SENSEX from spot `market_bars` over
a configurable range (supporting at least five years), with `--symbol`, `--from`, `--to`,
`--only-missing`, and `--dry-run` flags. It SHALL reuse `trading_days()`/`holidays()` from
`pdp.options.gap_backfill`, SHALL use the same session-anchored HLC helper as the live compute path
(no independent window derivation), and SHALL write idempotently.

#### Scenario: Backfill dry run reports plan

- **WHEN** `task backfill:levels -- --symbol NIFTY --from 2021-06-30 --dry-run` is run
- **THEN** it logs the trading-day count and range without writing to MongoDB

#### Scenario: Backfill populates daily, weekly, and monthly

- **WHEN** the backfill runs for SENSEX over a multi-year range
- **THEN** `index_levels` contains `daily`, `weekly`, and `monthly` documents for security_id 51 across that range

#### Scenario: Backfilled monthly matches live-computed monthly

- **WHEN** a monthly document produced by the backfill script is compared to the same period's document produced by the live `compute_session_levels` path
- **THEN** their `source.h`/`source.l`/`source.c` and `camarilla` values are identical
