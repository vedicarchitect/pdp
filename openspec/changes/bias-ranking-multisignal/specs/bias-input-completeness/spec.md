## ADDED Requirements

### Requirement: The bias score SHALL include a SuperTrend agreement vote per timeframe

`score_bias` SHALL accept a SuperTrend input for each of the 5m, 15m and 1h timeframes, each carrying
the flip direction of both the `(10, 2)` and `(10, 3)` SuperTrend variants. A timeframe's vote SHALL
be `+1` only when both variants are bullish, `-1` only when both are bearish, and `0` when they
disagree. When a timeframe's SuperTrend input is absent (either variant unseeded), that timeframe
SHALL abstain rather than vote `0`, so an unwarmed SuperTrend does not dilute the score toward
neutral. Each timeframe's vote SHALL carry its own configurable weight.

#### Scenario: Both variants agree bullish

- **WHEN** the 1h SuperTrend input is `(+1, +1)`
- **THEN** the `st_1h` vote is `+1`

#### Scenario: Variants disagree

- **WHEN** the 15m SuperTrend input is `(+1, -1)`
- **THEN** the `st_15m` vote is `0`, contributing weight but not direction

#### Scenario: Unseeded SuperTrend abstains

- **WHEN** a timeframe's SuperTrend variants are not yet seeded (input is `None`)
- **THEN** that timeframe abstains and its weight is excluded from the score denominator

### Requirement: The bias score SHALL include a Parabolic SAR vote per timeframe

`score_bias` SHALL accept a Parabolic SAR direction for each of the 5m, 15m and 1h timeframes and
SHALL vote that direction (`+1` bullish, `-1` bearish). When a timeframe's PSAR direction is absent,
that timeframe SHALL abstain rather than vote `0`. Each timeframe's vote SHALL carry its own
configurable weight.

#### Scenario: PSAR direction votes directly

- **WHEN** the 5m Parabolic SAR direction is `-1`
- **THEN** the `psar_5m` vote is `-1`

#### Scenario: Unseeded PSAR abstains

- **WHEN** a timeframe's PSAR direction is `None`
- **THEN** that timeframe abstains and its weight is excluded from the score denominator

### Requirement: The bias score SHALL include a combined ATM-option vote

`score_bias` SHALL derive one 5m vote from the current at-the-money option pair by applying the same
per-series trend read (EMA stack, SuperTrend agreement, Parabolic SAR) to the ATM CE 5m series and the
ATM PE 5m series, inverting the PE read (a falling PE implies a bullish underlying), and combining the
two. The combined vote SHALL be `+1` only when the CE read and the inverted PE read both point
bullish, `-1` only when both point bearish, and `0` when they conflict. When either the CE or PE input
is absent, the ATM vote SHALL abstain. The ATM vote SHALL carry a single configurable weight.

#### Scenario: CE up and PE down is bullish

- **WHEN** the ATM CE 5m read is bullish and the ATM PE 5m read is bearish
- **THEN** the `atm` vote is `+1`

#### Scenario: Conflicting CE and PE reads

- **WHEN** the ATM CE read is bullish but the ATM PE read is also bullish (PE rising)
- **THEN** the `atm` vote is `0`

#### Scenario: Missing option side abstains

- **WHEN** the ATM CE or ATM PE 5m series is unavailable
- **THEN** the `atm` vote abstains and its weight is excluded from the score denominator

### Requirement: The new signal votes SHALL be computed identically on the backtest and live paths

The SuperTrend, Parabolic SAR and ATM votes SHALL be produced from indicator state computed by the
same tracker types on both paths — the live `IndicatorEngine` and the backtest loader's warmed
trackers — so that identical `BiasInputs` yield an identical `BiasResult`. The backtest loader SHALL
warm its SuperTrend and Parabolic SAR trackers from the spot warmup prefix before the first traded
day, and SHALL resolve the ATM CE/PE marks from the same option data it already loads, so no traded
day evaluates the new votes on unconverged indicators.

#### Scenario: Backtest and live agree on a golden input

- **WHEN** the loader-built `BiasInputs` and the strategy-built `BiasInputs` carry the same SuperTrend,
  PSAR and ATM values
- **THEN** `score_bias` returns the same bucket and PE:CE ratio on both

#### Scenario: New votes are warm on the first traded day

- **WHEN** a short backtest window is warmed by the spot prefix
- **THEN** the SuperTrend and PSAR votes for the first traded day are present, not abstaining

## MODIFIED Requirements

### Requirement: The naked directional buckets SHALL require higher-timeframe trend confirmation

The naked extreme buckets `COMPLETE_BULL` (5:0) and `COMPLETE_BEAR` (0:5) SHALL be reachable only when
**both** higher-timeframe trend votes — the EMA alignment vote (`ema_1h`) and the SuperTrend agreement
vote (`st_1h`) — are present (non-abstaining) and agree with the bucket's direction. These are the
only buckets that sell a fully naked, undefended side, so they now require two independent 1h trend
families to confirm. When either confirmation is absent or disagrees, the bucket SHALL downgrade to the
nearest defended bucket (`MOST_BULL`/`MOST_BEAR`), which retains a protective position on the opposite
side.

#### Scenario: Naked bucket downgraded when either 1h family disagrees or abstains

- **WHEN** the raw score would select `COMPLETE_BEAR` but `ema_1h` or `st_1h` abstains (or points
  bullish)
- **THEN** the bucket is `MOST_BEAR` (2:4), keeping a protective PE side, not `COMPLETE_BEAR` (0:5)

#### Scenario: Naked bucket allowed only with both 1h families agreeing

- **WHEN** the raw score selects `COMPLETE_BEAR` and both `ema_1h` and `st_1h` are present and bearish
- **THEN** the bucket remains `COMPLETE_BEAR` (0:5)

### Requirement: Startup SHALL fail when a strategy weights a bias input its configuration cannot supply

At strategy load, for every bias weight greater than zero, the platform SHALL verify the corresponding
input is satisfiable from that strategy's watchlist and the active settings, and SHALL raise naming the
weight and the missing requirement when it is not. This SHALL cover the SuperTrend, Parabolic SAR and
ATM weights: a non-zero `w_st_{5m,15m,1h}` SHALL require the `supertrend` family on that timeframe, a
non-zero `w_psar_{5m,15m,1h}` SHALL require the `psar` family on that timeframe, and a non-zero `w_atm`
SHALL require the option-data prerequisite for resolving the ATM CE/PE 5m read. A weight of zero SHALL
impose no requirement.

#### Scenario: Weighted SuperTrend without the family

- **WHEN** a strategy sets `w_st_1h: 1.0` and its `1H` watchlist entry omits the `supertrend` family
- **THEN** startup fails naming `w_st_1h` and the missing `supertrend` family

#### Scenario: Weighted PSAR without the family

- **WHEN** a strategy sets `w_psar_5m: 1.0` and its `5m` watchlist entry omits the `psar` family
- **THEN** startup fails naming `w_psar_5m` and the missing `psar` family

#### Scenario: Zeroed new weight imposes no requirement

- **WHEN** a strategy sets `w_st_1h: 0.0` and omits the `supertrend` family on `1H`
- **THEN** startup succeeds
