## ADDED Requirements

### Requirement: The bias score SHALL require a minimum quorum of configured weight

`score_bias` SHALL compute the fraction of total *configured* weight (the sum of all non-zero
per-signal weights) that is actually present (non-abstaining) at a decision instant. When that
fraction is below `BiasWeights.min_quorum_weight_frac`, the result SHALL be forced to the `NEUTRAL`
bucket (the balanced 1:1 ratio) regardless of the computed score, so a renormalized score cannot
saturate onto a small subset of present inputs. The present-weight fraction SHALL be exposed on the
result for observability.

#### Scenario: A starved input set forces neutral

- **WHEN** only ORB and PCR are present (all trend, level, and swing inputs abstain) and their
  combined weight is below the configured quorum fraction
- **THEN** the bias bucket is `NEUTRAL` (1:1), not a saturated `COMPLETE_BULL`/`COMPLETE_BEAR`

#### Scenario: A quorum-satisfying input set scores normally

- **WHEN** the present inputs' weight meets or exceeds the quorum fraction
- **THEN** the score is bucketed by the normal thresholds and the present-weight fraction is reported
  on the result

### Requirement: The naked directional buckets SHALL require higher-timeframe trend confirmation

The naked extreme buckets `COMPLETE_BULL` (5:0) and `COMPLETE_BEAR` (0:5) SHALL be reachable only
when the higher-timeframe trend vote (`ema_1h`) is present (non-abstaining) and agrees with the
bucket's direction. These are the only buckets that sell a fully naked, undefended side. When that
confirmation is absent, the bucket SHALL downgrade to the nearest defended bucket
(`MOST_BULL`/`MOST_BEAR`), which retains a protective position on the opposite side.

#### Scenario: Naked bucket downgraded without trend confirmation

- **WHEN** the raw score would select `COMPLETE_BEAR` but `ema_1h` abstains (or is bullish)
- **THEN** the bucket is `MOST_BEAR` (2:4), keeping a protective PE side, not `COMPLETE_BEAR` (0:5)

#### Scenario: Naked bucket allowed with agreeing trend

- **WHEN** the raw score selects `COMPLETE_BEAR` and `ema_1h` is present and bearish
- **THEN** the bucket remains `COMPLETE_BEAR` (0:5)

### Requirement: The strangle backtest SHALL warm indicators from prior data before deciding

The directional-strangle backtest SHALL load a warmup runway of prior trading-day spot data ahead of
each traded window (enough to converge the higher-timeframe EMAs the bias engine consumes) so that no
traded day evaluates the bias engine on unconverged indicators. The warmup days SHALL NOT be traded
or included in results. Because the required prior data already exists in the warehouse, the backtest
SHALL always load the warmup prefix rather than trading a starved window.

#### Scenario: A short window still warms its indicators

- **WHEN** a single-day (or otherwise short) backtest window is requested
- **THEN** the higher-timeframe EMAs are converged for the first traded day (their votes are present,
  not abstaining), and the reported results cover only the requested day(s)

#### Scenario: Warmup days are not traded

- **WHEN** the backtest loads its warmup prefix
- **THEN** those prior days contribute to indicator warmup only and produce no trades or P&L
