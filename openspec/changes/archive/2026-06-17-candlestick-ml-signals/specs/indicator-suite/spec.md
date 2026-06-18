# indicator-suite

## ADDED Requirements

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
