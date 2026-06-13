## ADDED Requirements

### Requirement: Batch option-chain pre-loading

The backtest SHALL pre-load option bars in batch rather than querying per signal bar. For each
distinct expiry in the backtest range the system SHALL issue at most one `option_bars` query,
filtered by `underlying`, `expiry_date`, `option_type`, `timeframe`, and a `ts` range covering all
that expiry's trade-days, using the `(underlying, expiry_date, option_type, ts)` index. Loaded bars
SHALL be grouped in memory by `(trade_date, option_type, strike)` and resampled once to the signal
timeframe. The total number of option-bar queries for a run SHALL be O(number of expiries), not
O(number of signal bars).

#### Scenario: One query per expiry

- **WHEN** a backtest spans N trading days across M distinct weekly expiries
- **THEN** the system issues at most M option-bar queries (plus one NIFTY spot query for the range)
- **AND** the per-bar inner loop performs no MongoDB reads

#### Scenario: Results are unchanged

- **WHEN** the same backtest window is run with batch pre-loading
- **THEN** the replayed trades, per-leg P&L, and summary totals are identical to the per-bar reader

### Requirement: In-memory nearest-strike fallback

When the exact target strike is absent for a `(trade_date, option_type)`, the backtest SHALL select
the nearest available strike within `WAREHOUSE_STRIKE_BAND` grid steps from the already pre-loaded
chain, without issuing additional MongoDB queries. The live broker API MAY be consulted only when
no strike in the band was pre-loaded.

#### Scenario: Substitute strike served from memory

- **WHEN** the exact strike has no bars but a strike within the band does
- **THEN** the nearest in-band strike is used and the substitution is logged
- **AND** no extra MongoDB query is issued to find it

### Requirement: Backtest performance instrumentation

The backtest SHALL record and log, via `structlog`, the total elapsed wall-clock time, per-day
elapsed time, and the count of option-bar queries issued. These metrics SHALL be emitted at the end
of a run so the O(expiries) query budget and the sub-minute target can be verified.

#### Scenario: Timing emitted

- **WHEN** a multi-day backtest completes
- **THEN** a structured log line reports `elapsed_s`, `days`, and `option_queries`
