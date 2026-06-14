## ADDED Requirements

### Requirement: Input-data completeness gate

The backtest SHALL validate the NIFTU index 1-minute spot series for each trade day before
simulating, and SHALL NOT generate trades or P&L for a day whose series is incomplete. A day is
incomplete when its bar count is below `MIN_BARS_FRAC` of the expected full-session count
(≈375 bars for 09:15–15:30) or when it contains an intraday gap of at least `MAX_GAP_MIN` minutes.
An incomplete day SHALL be reported with a distinct `data_incomplete` status in both the per-day
output and the final summary, carrying the diagnostic reason (bars present, largest gap). The
backtest SHALL NOT perform a hidden mid-run Dhan fetch to fill the index series on the hot path;
backfill is an explicit, separate step.

#### Scenario: Complete day is simulated

- **WHEN** a trade day has ≈375 NIFTU 1m bars spanning 09:15–15:30 with no gap ≥ `MAX_GAP_MIN`
- **THEN** the backtest simulates the day normally and reports trades and P&L

#### Scenario: Day with an intraday hole is skipped

- **WHEN** a trade day's NIFTU 1m series contains a gap ≥ `MAX_GAP_MIN` minutes (e.g. 10:10→11:38)
- **THEN** the backtest skips the day, records no trades, and reports `data_incomplete` with the gap detail

#### Scenario: Day with no spot data is skipped

- **WHEN** a trade day has zero NIFTU 1m bars in `market_bars`
- **THEN** the backtest skips the day, records no trades, and reports `data_incomplete` rather than fabricating results

### Requirement: NIFTU index spot backfill utility

The system SHALL provide a script that backfills NIFTU index 1-minute history from Dhan into the
`market_bars` collection. The script SHALL fetch `security_id="13"` on `IDX_I`/`INDEX`, convert
epoch timestamps to UTC-naive `datetime`, and upsert keyed on
`(ts, metadata.security_id, metadata.timeframe)` so existing complete days are not duplicated. The
script SHALL throttle requests to the Data-API rate limit and back off on rate-limit errors, and
SHALL support a dry-run mode that requires no credentials and a missing-only mode that skips days
already at the expected bar count.

#### Scenario: Backfill fills a missing day

- **WHEN** the script runs for a date whose `market_bars` index series is empty and Dhan has data
- **THEN** the day's 1m bars are inserted into `market_bars` with UTC-naive timestamps

#### Scenario: Re-running does not duplicate

- **WHEN** the script runs again over an already-backfilled range
- **THEN** no duplicate documents are created (idempotent upsert)

#### Scenario: Dry-run needs no credentials

- **WHEN** the script runs with `--dry-run`
- **THEN** it prints the planned trade-day range and performs no Dhan calls or writes

### Requirement: Continuous cross-day SuperTrend warmup

The backtest SHALL warm each trade day's SuperTrend tracker with the most recent prior trading
day's bars (resampled to the signal timeframe) before feeding the day's own bars, so the indicator
line is continuous across the day boundary and inherits the prior day's direction — matching how
charting platforms (TradingView/Kite) compute SuperTrend. Warmup bars SHALL be fed to the tracker
but SHALL NOT be emitted into the day's signal series, so the day's first `flipped` reflects a
genuine carried-over-direction change rather than a fresh cold-start seed. When no prior session is
available (no data within the lookback), the tracker SHALL cold-start as before.

#### Scenario: Day inherits the prior session's direction at the open

- **WHEN** the prior trading day closed in an established uptrend and the new day gaps up
- **THEN** the day opens with SuperTrend UP (carried over), not a cold-start DOWN seed

#### Scenario: Early flip on a morning reversal is detected

- **WHEN** a day opens UP (inherited) and then falls back through the SuperTrend band in the morning
- **THEN** SuperTrend flips UP→DOWN in that morning window (e.g. ~09:55 on 2026-06-12), and the
  wait-for-first-flip gate may enter from that flip

#### Scenario: No prior data falls back to cold start

- **WHEN** no prior trading session is available within the lookback window
- **THEN** the tracker cold-starts on the day's own first bars, preserving prior behavior

### Requirement: Wait-for-first-flip entry discipline

The backtest SHALL suppress all new-position entries (initial open and scale-in) for a trade day
until the first SuperTrend flip occurring after the session start time. The flip is detected via
the indicator's `flipped` signal, which is true only on a genuine trend-direction change. Once the
first flip of the day has occurred, normal entry behavior resumes. Flip handling, stop-loss, and
square-off logic are otherwise unchanged. The first-flip state SHALL reset at the start of each
trade day.

#### Scenario: No entry before the first flip

- **WHEN** the SuperTrend direction has not flipped since the session start
- **THEN** the backtest opens no position and records no scale-in for that day so far

#### Scenario: Entry resumes on the first flip

- **WHEN** the first SuperTrend flip after session start occurs on a given bar
- **THEN** the backtest may open a position from that bar onward according to the signal

#### Scenario: First-flip gate resets each day

- **WHEN** a new trade day begins
- **THEN** the first-flip requirement applies again before any entry on that day
