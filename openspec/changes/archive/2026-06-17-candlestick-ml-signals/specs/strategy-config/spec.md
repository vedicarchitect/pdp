# strategy-config

## ADDED Requirements

### Requirement: Opt-in ML signal consumption
The strategy configuration SHALL allow a watchlist entry to opt into the `candlestick-ml-signals`
signal for its `security_id` and timeframes, including which trained model version to serve. When
not opted in, no ML model SHALL be loaded or served for that entry, and the entry's existing
indicator selection SHALL be unaffected.

#### Scenario: Watchlist opts into the ML signal
- **WHEN** a watchlist entry enables the ML signal with a model version for a timeframe
- **THEN** that model version is loaded and `ml_signal(sid, tf)` returns its output for that entry

#### Scenario: ML signal not requested
- **WHEN** a watchlist entry does not enable the ML signal
- **THEN** no ML model is loaded for that entry and `ml_signal(sid, tf)` returns `None`
