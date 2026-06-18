# candlestick-ml-signals

## ADDED Requirements

### Requirement: Offline-trained classical model
The system SHALL train a classical gradient-boosted-tree model offline over historical
`market_bars`, producing a versioned model artifact on disk. Training SHALL NOT run on the live
hot path. The artifact SHALL record its feature schema, label schema, training window, and a
build identifier so inference can detect schema drift.

#### Scenario: Train and version an artifact
- **WHEN** the trainer runs over a configured historical window for a `(security_id, timeframe)`
- **THEN** it writes a versioned artifact containing the fitted model, the feature schema, the
  label schema, the training window, and a build identifier
- **AND** it emits a metrics report (validation scores and feature importances)

#### Scenario: Inference rejects a mismatched artifact
- **WHEN** the online feature schema does not match the artifact's recorded feature schema
- **THEN** inference SHALL refuse to serve and SHALL return no signal rather than a value from
  mismatched features

### Requirement: Single leakage-safe feature builder
A single feature builder SHALL produce feature rows used identically for training and inference.
For any bar, the builder SHALL use only information available at or before that bar's close
(closed-bar indicator snapshots, prior swings, prior-session levels). It SHALL NOT use any future
bar or any whole-series transform that depends on later data.

#### Scenario: Same features offline and online
- **WHEN** a feature row is built for a given bar during training and again during live inference
- **THEN** both rows are identical for the features available at that bar's close

#### Scenario: No future information leaks into a row
- **WHEN** the builder produces the feature row for bar *t*
- **THEN** the row depends only on bars with index ≤ *t* and on prior-session/prior-swing state

### Requirement: Forward-looking labels with purged validation
Training labels SHALL look forward by exactly the configured horizon and SHALL be dropped where
the full horizon is unavailable. Model validation SHALL use purged, embargoed walk-forward
cross-validation so that no training fold overlaps a validation label's horizon.

#### Scenario: Drop rows without a full horizon
- **WHEN** fewer than the configured horizon of future bars exist after a candidate bar
- **THEN** that bar produces no training label and is excluded from the training set

#### Scenario: Purged walk-forward folds
- **WHEN** the trainer builds cross-validation folds
- **THEN** each validation fold is separated from its training data by an embargo at least as
  long as the label horizon

### Requirement: Read-only online directional signal
The trained model SHALL be exposed as a read-only signal per `(security_id, timeframe)` returning
class probabilities and the argmax class plus the serving model version. The signal SHALL be
reachable via the indicator reader (`ctx.indicators.ml_signal(security_id, timeframe)`) and SHALL
be consumed read-only by strategies, which SHALL NOT retrain or recompute it.

#### Scenario: Strategy reads the signal
- **WHEN** a strategy opted into the ML signal reads `ml_signal(sid, tf)` after a bar closes
- **THEN** it receives the class probabilities, the argmax class, and the serving model version

#### Scenario: No model loaded
- **WHEN** no artifact is loaded for a `(security_id, timeframe)`
- **THEN** `ml_signal(sid, tf)` returns `None` and strategies degrade gracefully

### Requirement: Non-blocking hot path
Online inference SHALL NOT perform blocking I/O on the tick/bar hot path and SHALL operate within
the platform's `tick→WS p99 ≤ 50ms` budget. Inference SHALL reuse the already-computed indicator
snapshot for the bar and SHALL NOT recompute indicators.

#### Scenario: Signal served within budget
- **WHEN** bars close continuously across many `(security_id, timeframe)` bundles with the signal enabled
- **THEN** signal computation reuses the cached indicator snapshot, performs no blocking I/O on the
  hot path, and the tick→WS p99 stays within budget

### Requirement: Backtest parity
The backtest engine SHALL produce the same signal as live for the same bars by running the same
feature builder and the same pinned model artifact. The signal SHALL NOT use any data a live run
would not have had at the same bar.

#### Scenario: Live equals backtest
- **WHEN** the same bar sequence is replayed in backtest and processed live with the same artifact
- **THEN** the signal values match at every bar

### Requirement: Expiry-day close-zone head (phase 2)
The system SHALL provide a second model that predicts NIFTY's expiry-day close zone as a bucketed
distance from spot, consuming option-chain analytics features (max-pain, PCR, GEX, implied
volatility / India VIX, OI walls) in addition to the price-structure features. This head SHALL be
gated behind configuration and SHALL be disabled by default.

#### Scenario: Expiry head disabled by default
- **WHEN** the expiry head is not explicitly enabled in configuration
- **THEN** no expiry-close model is loaded or served

#### Scenario: Expiry head consumes options features
- **WHEN** the expiry head is enabled on a NIFTY expiry day
- **THEN** its feature row includes the option-chain analytics features for the active expiry and
  it returns a probability distribution over close-zone buckets
