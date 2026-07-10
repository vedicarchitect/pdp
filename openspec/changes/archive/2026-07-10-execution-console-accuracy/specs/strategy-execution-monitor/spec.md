## MODIFIED Requirements

### Requirement: Monitor indicator matrix

The system SHALL include an indicator matrix for the three indices and each active non-hedge
strike, spanning timeframes `5m`, `15m`, `30m`, `1H`, `1D`. For each timeframe it SHALL
include EMA(9/20/50/100/200) on close, SuperTrend(10,2) value and direction, Parabolic
SAR(0.02/0.02/0.2), RSI(14) with its SMA(14) signal, and — sourced from the index's
current-month futures contract — session VWAP (hlc3) and VWMA(20). Price-based indicators
(EMA, SuperTrend, PSAR, RSI) SHALL be computed on the spot index security id; volume-anchored
VWAP and VWMA SHALL be computed on the futures security id, because spot indices carry no
tradeable volume. SuperTrend for the matrix SHALL use period 10 / multiplier 2 regardless of
any strategy-specific SuperTrend configuration.

The matrix SHALL include Camarilla levels (pp/r3/r4/s3/s4) and previous-period high/low for
three periods — `camarilla_daily` + PDH/PDL, `camarilla_weekly` + PWH/PWL, and
`camarilla_monthly` + PMH/PML. These level sets SHALL be read from the persisted
`index_levels` warehouse (`LevelsStore`) for the current session, NOT recomputed from the
live indicator engine. When a level document is missing the corresponding fields SHALL be
`null` and the endpoint SHALL NOT error. The client maps timeframe to period for display:
`5m`/`15m` use daily, `30m`/`1H` use weekly, `1D` uses monthly.

#### Scenario: Matrix covers indices and active strikes

- **WHEN** the monitor is requested with two short legs open
- **THEN** `indicators` contains entries for NIFTY/BANKNIFTY/SENSEX and the two active non-hedge strike security ids

#### Scenario: Matrix includes EMA200, RSI, VWAP and VWMA

- **WHEN** the monitor is requested and warmup has seeded the index and its futures contract
- **THEN** each index timeframe cell includes non-null `ema200`, `rsi`, `rsi_ma`, and — from the futures contract — `vwap` and `vwma`

#### Scenario: Levels sourced from the warehouse across three periods

- **WHEN** `index_levels` holds daily, weekly, and monthly documents for an index for the current session
- **THEN** that index's `camarilla_daily`/`camarilla_weekly`/`camarilla_monthly` and `period.pdh/pdl/pwh/pwl/pmh/pml` are populated from those documents, and PDH differs from PDL and from the current price

#### Scenario: Missing level document yields nulls, not an error

- **WHEN** the monthly `index_levels` document for an index is absent
- **THEN** `camarilla_monthly` and `period.pmh/pml` are `null` and the endpoint still returns HTTP 200

#### Scenario: 1D column populated after warmup

- **WHEN** the application has completed startup warmup with a 1D data source available
- **THEN** the `1D` row for each index has non-null EMA/SuperTrend/PSAR values rather than `--`
