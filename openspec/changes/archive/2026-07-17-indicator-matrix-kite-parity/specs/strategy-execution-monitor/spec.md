## MODIFIED Requirements

### Requirement: Monitor indicator matrix

The system SHALL include an indicator matrix for the three indices, each active non-hedge
strike, and — for NIFTY — the current at-the-money (ATM) call and put option, spanning
timeframes `5m`, `15m`, `30m`, `1H`, `1D`. For each timeframe it SHALL include EMA(9/20/50/100/
200) on close, three SuperTrend variants — `(10,2)`, `(10,3)`, and `(3,1)` (period, multiplier)
— each with value and direction, Parabolic SAR(0.02/0.02/0.2), RSI(14) with its SMA(14) signal,
and — sourced from the index's current-month futures contract, or from the option's own traded
volume for the ATM CE/PE rows — session VWAP (hlc3) and VWMA(20). Price-based indicators (EMA,
SuperTrend, PSAR, RSI) SHALL be computed on the spot index security id (or the option security id
for ATM rows); volume-anchored VWAP and VWMA SHALL be computed on the futures security id for
index rows (spot indices carry no tradeable volume) and on the option's own 1-minute bars for ATM
rows (options do carry traded volume).

The NIFTY ATM CE/PE rows SHALL resolve the current ATM strike from spot and the nearest expiry,
SHALL compute their indicator values on demand from the `option_bars` 1-minute series (not via a
live per-strike tracker), and SHALL render `null`/`--` for any cell whose backing 1-minute history
is shorter than that indicator's required depth, rather than fabricating a value. ATM CE/PE rows
MUST NOT include Camarilla or previous-period high/low fields (index-only concepts).

The matrix SHALL include Camarilla levels (pp/r3/r4/s3/s4) and previous-period high/low for
three periods — `camarilla_daily` + PDH/PDL, `camarilla_weekly` + PWH/PWL, and
`camarilla_monthly` + PMH/PML — for index rows only. These level sets SHALL be read from the
persisted `index_levels` warehouse (`LevelsStore`) for the current session, NOT recomputed from
the live indicator engine. When a level document is missing the corresponding fields SHALL be
`null` and the endpoint SHALL NOT error. The client maps timeframe to period for display:
`5m`/`15m` use daily, `30m`/`1H` use weekly, `1D` uses monthly.

#### Scenario: Matrix covers indices, active strikes, and NIFTY ATM CE/PE

- **WHEN** the monitor is requested with two short legs open
- **THEN** `indicators` contains entries for NIFTY/BANKNIFTY/SENSEX, the two active non-hedge strike security ids, and a NIFTY ATM CE row and a NIFTY ATM PE row labeled with their resolved strike and expiry

#### Scenario: Matrix includes EMA200, RSI, VWAP and VWMA

- **WHEN** the monitor is requested and warmup has seeded the index and its futures contract
- **THEN** each index timeframe cell includes non-null `ema200`, `rsi`, `rsi_ma`, and — from the futures contract — `vwap` and `vwma`

#### Scenario: Matrix includes three SuperTrend variants

- **WHEN** the monitor is requested for any index or strike timeframe cell
- **THEN** the cell includes three distinct SuperTrend results keyed by variant — `st_10_2`, `st_10_3`, `st_3_1` — each with its own value and direction, computed independently

#### Scenario: ATM CE/PE row indicators computed from option_bars

- **WHEN** the monitor is requested and the NIFTY ATM call's `option_bars` 1-minute series has at least the required depth for a timeframe's EMA/RSI/PSAR/SuperTrend/VWAP/VWMA
- **THEN** that timeframe's cell in the ATM CE row is populated from bars aggregated from `option_bars`, not from the spot IndicatorEngine

#### Scenario: ATM row degrades honestly on short history

- **WHEN** the NIFTY ATM put's `option_bars` 1-minute series has fewer bars than a given indicator's required depth for a timeframe
- **THEN** that indicator's field in the ATM PE row's cell for that timeframe is `null`, not a partial or fabricated value

#### Scenario: ATM rows omit index-only levels

- **WHEN** the monitor is requested and the NIFTY ATM CE/PE rows are present
- **THEN** those rows' cells have no `camarilla_daily`/`camarilla_weekly`/`camarilla_monthly` or `pdh`/`pdl`/`pwh`/`pwl`/`pmh`/`pml` fields populated

#### Scenario: Levels sourced from the warehouse across three periods

- **WHEN** `index_levels` holds daily, weekly, and monthly documents for an index for the current session
- **THEN** that index's `camarilla_daily`/`camarilla_weekly`/`camarilla_monthly` and `period.pdh/pdl/pwh/pwl/pmh/pml` are populated from those documents, and PDH differs from PDL and from the current price

#### Scenario: Missing level document yields nulls, not an error

- **WHEN** the monthly `index_levels` document for an index is absent
- **THEN** `camarilla_monthly` and `period.pmh/pml` are `null` and the endpoint still returns HTTP 200

#### Scenario: 1D column populated after warmup

- **WHEN** the application has completed startup warmup with a 1D data source available
- **THEN** the `1D` row for each index has non-null EMA/SuperTrend/PSAR values rather than `--`
