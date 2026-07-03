# indicator-suite Specification

## Purpose
Shared, single-compute indicator layer. The suite computes every requested technical indicator
once per closed bar per `(security_id, timeframe)` and caches a snapshot that strategies,
the backtest engine, and the UI consume read-only. Rule: IndicatorEngine computes once;
strategies consume, never recompute.
## Requirements
### Requirement: Shared single-compute layer
The indicator suite SHALL compute every requested indicator once per closed bar in the
`(security_id, timeframe)` it belongs to, before strategy dispatch, and expose the result
read-only. Strategies, the backtest engine, and the UI SHALL consume these values and SHALL
NOT recompute any indicator the suite provides.

#### Scenario: One compute, many consumers
- **WHEN** a bar closes for a `(security_id, timeframe)` with one or more requested indicators
- **THEN** the suite updates each requested indicator exactly once and caches a snapshot
- **AND** any strategy reading that `(security_id, timeframe)` receives the cached value
  without triggering recomputation

#### Scenario: Value not yet seeded
- **WHEN** a strategy reads an indicator that has not yet accumulated enough bars to produce a value
- **THEN** the suite returns `None` for that indicator rather than a partial or zero value

### Requirement: Config-driven selection per instrument and timeframe
The suite SHALL compute, for each `(security_id, timeframe)`, only the indicator families
requested by the loaded strategy configuration for that pair. Families not requested SHALL
incur no tracker allocation and no per-bar computation. Market Profile and Volume Profile SHALL
be computed only when explicitly requested.

#### Scenario: Only requested families are built
- **WHEN** the configuration requests only `ema` and `rsi` for a `(security_id, timeframe)`
- **THEN** the suite builds only the EMA and RSI trackers for that pair
- **AND** a snapshot for that pair returns EMA and RSI values and `None` for every other family

#### Scenario: Union across strategies
- **WHEN** two strategies share a `(security_id, timeframe)` and request `[ema]` and `[rsi]` respectively
- **THEN** the suite computes the union `{ema, rsi}` once for that pair, shared by both strategies

### Requirement: Performance and latency
Each indicator family SHALL update in O(1) per closed bar using `float64` state, with no
per-bar reallocation of history. The suite SHALL sustain continuous feeds for 200 or more
instruments across multiple timeframes within the platform's `tick→WS p99 ≤ 50ms` budget and
SHALL NOT perform blocking I/O on the hot path.

#### Scenario: Scale within budget
- **WHEN** bars close continuously for 200 or more `(security_id, timeframe)` bundles
- **THEN** the mean per-bar `on_bar` update is sub-millisecond and the tick→WS p99 stays within budget

### Requirement: Exponential moving averages
The suite SHALL provide EMA values for the configured periods (defaulting to 9, 20, 50, 100,
and 200), each updated incrementally from the bar close as `ema = α·close + (1−α)·ema` with
`α = 2/(period+1)`.

#### Scenario: EMA tracks a known series
- **WHEN** a known close series is fed through the EMA tracker for period 9
- **THEN** the reported EMA matches the hand-computed exponential moving average for that series

### Requirement: Relative strength index
The suite SHALL provide an RSI value using Wilder's running average of gains and losses over the
configured period (default 14), updated incrementally per closed bar. An optional EMA signal line
of the RSI (default period 9) SHALL be maintained and exposed as `RSIState.ma`.

#### Scenario: RSI matches Wilder reference
- **WHEN** a known close series is fed through the RSI tracker
- **THEN** the reported RSI matches the Wilder-method reference value for that series

#### Scenario: RSI signal line (MA)
- **WHEN** enough RSI values have been computed to seed the signal line
- **THEN** `RSIState.ma` holds the EMA of the RSI series; before seeding it is `None`

### Requirement: Parabolic SAR
The suite SHALL provide a Parabolic SAR value and trend direction, maintaining the extreme
point and acceleration factor and flipping direction when price crosses the SAR.

#### Scenario: SAR flips on reversal
- **WHEN** price closes through the current SAR against the prevailing trend
- **THEN** the tracker flips trend direction, resets the acceleration factor, and reports the
  new SAR on the opposite side of price

### Requirement: VWAP with session anchoring
The suite SHALL provide a volume-weighted average price as the running ratio of cumulative
price×volume to cumulative volume, reset at the start of each trading session (09:15 IST).

#### Scenario: VWAP resets each session
- **WHEN** the first bar of a new trading session closes
- **THEN** the VWAP accumulators reset so the reported VWAP reflects only the current session

### Requirement: Volume-weighted moving average
The suite SHALL provide a VWMA over a configured rolling window as the ratio of windowed
price×volume to windowed volume, updated in amortized O(1) using a bounded buffer.

#### Scenario: VWMA over a rolling window
- **WHEN** bars are fed through the VWMA tracker for a window of N
- **THEN** the reported VWMA reflects only the most recent N bars' price×volume over volume

### Requirement: Standard, Camarilla, and Fibonacci pivots
The suite SHALL compute pivot levels once per session from the prior session's high, low, and
close, and hold them constant intrabar. It SHALL provide the standard pivot and supports/
resistances, the Camarilla pivot with R3, R4, S3, and S4, and the Fibonacci pivot levels.

#### Scenario: Camarilla levels from prior HLC
- **WHEN** the prior session's high, low, and close are known
- **THEN** the suite reports Camarilla R3, R4, S3, S4, and the pivot computed from those values,
  unchanged for the duration of the current session

### Requirement: Weekly bar aggregation

The bar aggregator SHALL produce `1w` (weekly) bars using ISO-week boundaries, and the bar writer SHALL
persist them to `market_bars` alongside the existing timeframes. Weekly bar open SHALL be the first
trade of the ISO week, high/low the week extremes, close the last trade, with volume summed.

#### Scenario: Weekly bar rolls at ISO-week boundary

- **WHEN** bars cross from one ISO week into the next
- **THEN** the prior week's `1w` bar is emitted with that week's open/high/low/close and persisted to `market_bars`

### Requirement: Weekly Camarilla pivots

The indicator engine SHALL compute pivot levels on the `1w` timeframe so `get_pivots(security_id, "1w")`
returns standard, Camarilla, and Fibonacci levels derived from the prior ISO-week HLC. Warmup SHALL seed
weekly pivots from `market_bars` so values are available on day one.

#### Scenario: Weekly Camarilla available after warmup

- **WHEN** the engine is warmed up with at least two ISO weeks of bars for an index
- **THEN** `get_pivots(sid, "1w")` returns non-null `cam_pp`, `cam_r3`, `cam_r4`, `cam_s3`, `cam_s4`

#### Scenario: Strangle weekly Camarilla no longer missing

- **WHEN** the directional strangle reads weekly Camarilla via `pivots(sid, "1w")`
- **THEN** it receives populated values and does not log `cam_weekly_missing`

### Requirement: Fair-value gaps
The suite SHALL detect fair-value gaps from the three-bar pattern (a gap between bar N−2 and
bar N that bar N−1 does not cover) and maintain the set of currently unfilled gaps, marking a
gap filled when price later trades back through it.

#### Scenario: FVG detected and later filled
- **WHEN** a three-bar sequence forms a bullish or bearish fair-value gap
- **THEN** the suite reports the gap as unfilled
- **AND** when price later trades back through the gap, the suite marks it filled

### Requirement: Market Profile (opt-in)
When requested, the suite SHALL build a TPO-based market profile for the session by accumulating
time at price into price buckets, reset at session start, and report the developing profile.

#### Scenario: TPO accumulation
- **WHEN** bars trade across a range during a session with market profile requested
- **THEN** each bucket's TPO count reflects the time spent at that price for the current session

### Requirement: Volume Profile (opt-in)
When requested, the suite SHALL build a volume profile for the session by accumulating volume
into price buckets, reset at session start, and report the point of control (POC) and the value
area high and low (VAH/VAL).

#### Scenario: POC and value area
- **WHEN** session volume is distributed across price buckets with volume profile requested
- **THEN** the suite reports the POC at the highest-volume bucket and the value area (VAH/VAL)
  bounding the configured share of total volume

### Requirement: Warmup priming
On startup, the suite SHALL prime every configured indicator family from the prior session's
bars before the first live bar, deriving prior-session HLC for pivots. Warmup failures SHALL be
logged and SHALL NOT block application startup; an unprimed family SHALL report `None`.

#### Scenario: Families primed before first live bar
- **WHEN** the application starts with prior-session bars available
- **THEN** each configured family reports a value (where enough history exists) on the first
  live bar instead of cold-starting

#### Scenario: Warmup failure is non-fatal
- **WHEN** prior-session data is missing or a warmup fetch fails
- **THEN** startup proceeds, the affected families report `None`, and a warning is logged

### Requirement: Candlestick pattern detection
The suite SHALL provide a candlestick-pattern family that detects, per closed bar, a configured
set of classical single- and multi-bar patterns (including doji, hammer, shooting-star,
bullish/bearish engulfing, harami, morning star, evening star, and marubozu) using only the
current and preceding closed bars. It SHALL expose per-pattern boolean flags and a compact
bullish/bearish/neutral classification for the latest bar, updated in O(1) per bar.

#### Scenario: Detect a multi-bar pattern
- **WHEN** the most recent closed bars form a bullish engulfing
- **THEN** the candlestick family flags `bullish_engulfing` for the latest bar and classifies it bullish

#### Scenario: No pattern present
- **WHEN** the latest closed bar matches no configured pattern
- **THEN** all pattern flags are false and the classification is neutral

### Requirement: Elliott-Wave structure
The suite SHALL provide an Elliott-Wave family that detects swing pivots via a ZigZag with a
configurable percentage or ATR threshold and applies a heuristic wave labeling (impulse 1–5 and
corrective A–B–C) with a confidence score. The labeling is heuristic and SHALL be treated as a
probabilistic feature, not a deterministic rule.

#### Scenario: Label the current wave
- **WHEN** detected swings form a recognizable impulse sequence
- **THEN** the family exposes the current wave label, the position within the sequence, and a
  confidence score

#### Scenario: Insufficient structure
- **WHEN** too few swings exist to label a wave
- **THEN** the family returns no wave label rather than a forced or zero value

### Requirement: Fibonacci retracement and extension levels
The suite SHALL provide a Fibonacci retracement/extension family that, from the latest detected
swing leg, computes standard retracement levels (0.236, 0.382, 0.5, 0.618, 0.786) and extension
levels (1.272, 1.618, 2.0), and reports the nearest level to price, the signed distance to it, and
the most recently reacted-from level. This family is distinct from the suite's existing Fibonacci
*pivot* levels.

#### Scenario: Levels from the latest swing
- **WHEN** a new swing leg is confirmed
- **THEN** the family recomputes retracement and extension levels for that leg and reports the
  nearest level and price's signed distance to it

### Requirement: MACD
The suite SHALL provide a MACD family computing the MACD line, signal line, and histogram from
configurable fast, slow, and signal periods, updated incrementally per closed bar.

#### Scenario: MACD updates per bar
- **WHEN** a bar closes for a `(security_id, timeframe)` requesting MACD
- **THEN** the family updates the MACD line, signal line, and histogram from the bar close

### Requirement: Elder Impulse regime
The suite SHALL provide an Elder Impulse family that combines the slope of a 13-period EMA (trend)
with the slope of the MACD histogram (momentum) into a per-bar regime of green (both rising), red
(both falling), or blue (mixed), and SHALL expose the regime together with its two component
directions.

#### Scenario: Green impulse
- **WHEN** both the 13-EMA and the MACD histogram rise on the latest closed bar
- **THEN** the Elder Impulse family reports a green regime

#### Scenario: Mixed impulse
- **WHEN** the 13-EMA and the MACD histogram disagree in direction on the latest closed bar
- **THEN** the Elder Impulse family reports a blue regime

### Requirement: Opt-in and single-compute for new families
Each new family SHALL be built only when a watchlist entry requests it, SHALL be computed once
per closed bar like every other suite family, and SHALL be consumed read-only. This applies to
the candlestick-pattern, Elliott-Wave, Fibonacci retracement/extension, MACD, and Elder Impulse
families. Strategies SHALL NOT recompute them.

#### Scenario: Only requested new families are built
- **WHEN** a `(security_id, timeframe)` requests only `candlestick` and `elder_impulse`
- **THEN** the suite builds the candlestick and Elder Impulse trackers (and the MACD tracker Elder
  Impulse depends on) and no other new family

### Requirement: Backtest parity
The backtest engine SHALL compute suite indicators using the same tracker classes as the live
suite, so that for an identical bar series the reported indicator states are identical between
backtest and live.

#### Scenario: Identical states across paths
- **WHEN** the same bar series is fed through the live suite and the backtest trackers
- **THEN** the reported indicator states match for every bar

### Requirement: SuperTrend preserved
The existing SuperTrend indicator SHALL remain unchanged in algorithm and precision (`Decimal`),
and SHALL remain readable through the existing `ctx.indicators.supertrend(security_id, timeframe)`
accessor.

#### Scenario: SuperTrend unchanged
- **WHEN** a strategy reads `ctx.indicators.supertrend(security_id, timeframe)` after the suite is added
- **THEN** it receives the same SuperTrend value it would have before the suite, with no change
  in precision or behaviour

### Requirement: period_levels indicator family

The universal `IndicatorEngine` SHALL provide a `period_levels` family producing previous-period high/low levels — previous-day (PDH/PDL), previous-week (PWH/PWL), and previous-month (PMH/PML) — as a `PeriodLevelsState`. The tracker SHALL follow the standard family protocol `update(high, low, close, volume, bar_time) -> PeriodLevelsState | None`, freeze each completed period's high/low at the corresponding day/ISO-week/calendar-month boundary, and be seedable from MongoDB `market_bars` during warmup. The family SHALL be reachable via `IndicatorEngine.get_period_levels(sid, tf)`, included in `Snapshot.period_levels`, registered in `registry.py`, and accessible from strategies via `IndicatorReader.period_levels(sid, tf)`.

#### Scenario: Previous-week high/low frozen at week boundary
- **WHEN** the first bar of a new ISO week is processed
- **THEN** `PeriodLevelsState.pwh` / `pwl` reflect the prior week's accumulated high/low and remain constant for the duration of the new week

#### Scenario: Previous-month high/low frozen at month boundary
- **WHEN** the first bar of a new calendar month is processed
- **THEN** `PeriodLevelsState.pmh` / `pml` reflect the prior month's high/low

#### Scenario: Seeded from warmup
- **WHEN** the engine warms up from MongoDB `market_bars` for a security/timeframe with at least one prior week and month of data
- **THEN** `get_period_levels` returns populated PWH/PWL/PMH/PML before the first live bar

#### Scenario: Available in snapshot
- **WHEN** `get_snapshot(sid, tf)` is called after `period_levels` is configured
- **THEN** the returned `Snapshot.period_levels` is a populated `PeriodLevelsState` (or `None` if not yet seeded)

#### Scenario: Strategies can read period levels
- **WHEN** a strategy calls `ctx.indicators.period_levels(sid, tf)`
- **THEN** the `PeriodLevelsState` is returned without error

