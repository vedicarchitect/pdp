### Requirement: Bias-scoring engine
The system SHALL provide a pure, deterministic bias-scoring function in `src/pdp/signals/bias.py` that accepts per-timeframe indicator snapshots (5m/15m/1h/1d/1w), an India VIX series, a PCR value, VWAP, and the 15m opening range, and returns a `BiasResult` containing a normalized score in `[−1, +1]`, a bias bucket, a sell PE:CE lot ratio, a `gated` flag, and a human-readable reason. The same function SHALL be used by both the backtest simulator and the live strategy so that identical inputs yield identical decisions.

#### Scenario: Aligned bullish inputs produce a bullish ratio
- **WHEN** 1h/15m EMAs are aligned bullish (9>20>50, price above 50), 5m price is above its 50 EMA, price closed above daily Camarilla R3 and above PDH, and PCR > 1.1
- **THEN** `BiasResult.score` is strongly positive and the bucket maps to a PE-heavy sell ratio (e.g. 4 PE : 2 CE or 5 PE complete-bull)

#### Scenario: Conflicting inputs produce a neutral ratio
- **WHEN** higher-timeframe signals disagree and the net score falls within the neutral band
- **THEN** the bucket is `neutral` with a balanced (1:1) ratio or no-trade, per configuration

#### Scenario: Same inputs are deterministic
- **WHEN** the function is called twice with identical inputs
- **THEN** it returns an identical `BiasResult` with no side effects

### Requirement: VIX entry gate
The bias engine SHALL block new entries (`gated = True`) when any of these hold: India VIX has risen more than 5% on the day, VIX is at the day's high, or VIX has increased over the last three 5-minute candles. When VIX history is unavailable for a timestamp, the gate SHALL default to allowing entries and the condition SHALL be logged.

#### Scenario: VIX spike blocks entry
- **WHEN** India VIX is up 6% on the day at decision time
- **THEN** `BiasResult.gated` is `True` and no strangle is opened

#### Scenario: Stable VIX allows entry
- **WHEN** India VIX is flat-to-down on the day and not at the day high
- **THEN** the VIX gate does not block entry (`gated` driven only by other gates)

### Requirement: PCR bias contribution
The bias engine SHALL treat PCR as a directional vote: PCR > 1.1 contributes a bullish vote and PCR < 0.9 contributes a bearish vote; values in between contribute no vote. PCR in the backtest SHALL be derived per bar from `option_bars` open interest as total PE OI divided by total CE OI.

#### Scenario: High PCR adds bullish vote
- **WHEN** PCR computed from the chain is 1.25
- **THEN** the PCR signal contributes a positive vote to the bias score

### Requirement: Multi-leg ratio-strangle simulator
The system SHALL provide `src/pdp/backtest/strangle_sim.py` that simulates a strangle with N PE legs and M CE legs at independent strikes, driven by the bias engine, with per-leg mark-to-market and commissions via the existing commission model. Leg counts SHALL follow the bias bucket's PE:CE ratio. Entries SHALL occur only after the 10:15 IST 1-hour candle completes.

#### Scenario: Bias ratio sets leg counts
- **WHEN** the bias bucket is `most-bull` (4 PE : 2 CE) at entry time
- **THEN** the simulator opens 4 PE lots and 2 CE lots at the selected strikes

#### Scenario: No entry before the 10:15 candle
- **WHEN** a valid bias forms at 09:45 IST
- **THEN** no legs are opened until after the 10:15 1-hour candle completes

### Requirement: Strike selection methods
The simulator SHALL support two strike-selection methods behind a `strike_method` configuration flag: `premium` selects the nearest strike whose premium exceeds 50 on the relevant side; `delta` selects the strike nearest a target delta (default 0.6) by solving implied volatility from the bar premium and computing Greeks via `src/pdp/options/greeks.py`.

#### Scenario: Premium method honors the floor
- **WHEN** `strike_method = premium` and the target side is CE
- **THEN** the chosen CE strike has a premium greater than 50 at entry

#### Scenario: Delta method targets the delta
- **WHEN** `strike_method = delta` with target 0.6
- **THEN** the chosen strike's absolute delta is the closest available to 0.6

### Requirement: Leg lifecycle and exits
The simulator SHALL implement: rollup of a leg when its premium falls below 20 (buy back, re-sell a strike with premium at least `roll_target_min_prem`); take-profit closing a leg at `take_profit_pct` of collected credit; tiered premium stops (half-close at 30% above entry, full-close at 40% above entry) with a 15-minute stop-recovery cooldown gate before re-entry on the stopped side; trend-flip adjustment that rolls the tested side when the 15m or 1h 50-EMA is crossed against the position; a daily loss cap that flattens and halts trading for the day when day P&L reaches −15000 INR; and square-off of all legs at session end.

#### Scenario: Rollup on premium decay
- **WHEN** an open leg's premium drops below 20
- **THEN** the leg is bought back and a new same-side strike with premium ≥ `roll_target_min_prem` is sold

#### Scenario: Take-profit on credit capture
- **WHEN** a leg has captured `take_profit_pct` (e.g. 50%) of its collected credit
- **THEN** the leg is closed and its realized P&L recorded

#### Scenario: Daily loss cap halts trading
- **WHEN** cumulative day P&L reaches −15000 INR
- **THEN** all open legs are closed and no new entries are taken for the rest of the day

### Requirement: Detailed every-minute status logging
The simulator and the live strategy SHALL emit, for every processed decision bar, a detailed status record containing the IST timestamp, spot, bias score and bucket, the VIX/PCR gate state, each individual signal vote (the conditions), every open leg with its strike/lots/entry/LTP/MTM, the running day P&L, and the action taken that bar. In the backtest this is exposed as an opt-in per-bar trace; in live it is a structlog heartbeat with the same fields.

#### Scenario: Per-bar trace captures conditions and position
- **WHEN** a backtest day is simulated with tracing enabled
- **THEN** exactly one status record is produced per processed bar, each including the per-signal votes, the open legs with LTP/MTM, the day P&L, and the action (e.g. `open 5PE`, `take_profit`, `roll`, `trend_flip`, `squareoff`, `hold`)

#### Scenario: Status line is human-readable
- **WHEN** a status record is formatted for monitor-style logging
- **THEN** it renders a single IST-stamped line with the bias score/bucket, VIX/PCR, the condition votes, the open legs, and the day P&L

### Requirement: VIX historical data pipeline
The system SHALL provide `scripts/backfill_vix.py` that fetches India VIX 1-minute history from Dhan and stores it in the `market_bars` collection under a dedicated security id, idempotently and rate-limited consistent with existing backfill scripts.

#### Scenario: VIX backfill is idempotent
- **WHEN** `scripts/backfill_vix.py` is run twice for the same date range
- **THEN** the second run produces no duplicate bars in `market_bars`

### Requirement: Data coverage audit
The system SHALL provide `scripts/audit_strangle_data.py` that reports, per year, the bar-coverage of NIFTY spot, options, and India VIX in Mongo, and identifies the earliest date with adequate coverage. The backtest window for optimization SHALL be derived from this report rather than assumed.

#### Scenario: Audit reports the usable horizon
- **WHEN** the audit script is run
- **THEN** it prints a per-year coverage table and the earliest date meeting the coverage threshold

### Requirement: Walk-forward optimization
The system SHALL provide `backtest/strangle_walkforward.py` that optimizes bias weights, gate thresholds, and strike parameters on an in-sample window and evaluates the chosen configuration on a disjoint out-of-sample window, reporting profit factor, Sharpe, and max drawdown for both windows side by side.

#### Scenario: Out-of-sample report is produced
- **WHEN** the walk-forward run completes over the audited data window
- **THEN** it emits an in-sample-vs-out-of-sample metrics table used as the go/no-go gate for paper deployment

### Requirement: Paper directional-strangle strategy
The system SHALL provide `src/pdp/strategies/directional_strangle.py` implementing the strategy ABC and `strategies/directional_strangle.yaml`, reusing the same `src/pdp/signals/bias.py` engine as the backtest. The strategy SHALL be paper-first (no live orders unless `LIVE=1` with broker and credentials) and SHALL apply the same gates, ratios, and exits as the simulator.

#### Scenario: Paper-first default
- **WHEN** the strategy runs without `LIVE=1`
- **THEN** all orders are routed to the paper broker

#### Scenario: Live and backtest agree on a bias decision
- **WHEN** the live strategy and a same-day backtest replay receive identical bar/VIX/PCR inputs at a timestamp
- **THEN** both produce the same bias bucket and PE:CE ratio

### Requirement: Hedge legs record the day P&L baseline
The strategy SHALL record the per-security day P&L baseline when opening a hedge leg, the same way
it does for short and momentum legs.

Without this, the hedge security's realized P&L is not baselined and `_day_realized()` mis-counts the
day total.

#### Scenario: Hedge open baselines the security
- **WHEN** a hedge leg is opened for a security
- **THEN** the strategy records that security's current realized P&L as the day baseline before
  placing the order, identically to short and momentum opens

### Requirement: Bias score uses the full configured signal set
The strategy SHALL provide live inputs for every configured bias signal so that each contributes a
vote when its data is available, rather than leaving votes permanently absent.

This covers: `ema_1h` and `ema_15m` (seeded by warmup before the first bar), `cam_weekly` (from a
weekly `1w` pivot snapshot), `vwap` (computed from index **futures** volume, since an index spot has
no traded volume), and `pcr` (derived from the option-chain poller). The intent is to dilute any
single signal's influence so a lone `ema_5m` flip no longer changes the bucket on its own.

#### Scenario: All configured signals vote when warmed
<!-- deferred: cam_weekly vote requires 1w bar-aggregator support, not yet implemented;
     existing cam_weekly_missing debug log fires once per session as a runtime marker.
     This scenario is aspirational and will pass fully once 1w support lands. -->
- **WHEN** the engine evaluates bias after warmup and chain data are available
- **THEN** the `bias_evaluated.votes` record contains entries for `ema_1h`, `ema_15m`, `ema_5m`,
  `cam_daily`, `cam_weekly`, `swing`, `vwap`, `orb`, and `pcr`

#### Scenario: VWAP comes from futures, not the index spot
- **WHEN** the VWAP signal is computed for an index-driven strangle
- **THEN** it is derived from the index futures' volume-bearing bars
- **AND** it produces a non-null vote once futures volume is non-zero

#### Scenario: A missing data source skips only its own vote
- **WHEN** one signal's data is unavailable (e.g. chain not yet polled for `pcr`)
- **THEN** only that signal's vote is omitted and the remaining signals still vote

### Requirement: Bucket changes require sustained confirmation
The strategy SHALL require a new bias bucket to persist for `bucket_confirm_bars` consecutive bars
before it closes and reopens legs for that bucket.

`bucket_confirm_bars` defaults to 2. A bucket that reverts before confirmation MUST reset the
confirmation counter and leave the open legs untouched.

#### Scenario: Single-bar flip does not churn legs
- **WHEN** the bucket changes for one bar and reverts on the next, with `bucket_confirm_bars = 2`
- **THEN** the strategy does not close or reopen any legs

#### Scenario: Sustained change acts after confirmation
- **WHEN** a new bucket persists for `bucket_confirm_bars` consecutive bars
- **THEN** the strategy closes the current legs and reopens for the new bucket

### Requirement: Day-loss halt survives a restart
The strategy SHALL persist a per-strategy, per-IST-day halt marker when `day_loss_cap` triggers, and
on startup SHALL remain halted for the rest of that trading day if the marker is set.

The marker MUST be keyed by strategy id and IST trading day, and MUST clear on IST date rollover so
the next day starts un-halted.

#### Scenario: Restart on the same day stays halted
- **WHEN** `day_loss_cap` has fired for a strategy today, the strategy is restarted, and the first
  bar of the same IST day is processed
- **THEN** the strategy is halted and does not open new legs

#### Scenario: Next day resumes
- **WHEN** the IST trading day rolls over after a halt
- **THEN** the halt marker is cleared and the strategy may open legs again
