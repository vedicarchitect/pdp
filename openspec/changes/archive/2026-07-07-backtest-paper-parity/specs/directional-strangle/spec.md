## MODIFIED Requirements

### Requirement: Bias-scoring engine
The system SHALL provide a pure, deterministic bias-scoring function in `src/pdp/signals/bias.py` that accepts per-timeframe indicator snapshots (5m/15m/1h/1d/1w), an India VIX series, a PCR value, and the 15m opening range, and returns a `BiasResult` containing a normalized score in `[−1, +1]`, a bias bucket, a sell PE:CE lot ratio, a `gated` flag, and a human-readable reason. VWAP SHALL NOT be a bias input — neither the live strategy nor the backtest simulator SHALL pass a VWAP value into the scoring function, and the function SHALL NOT define a VWAP vote or weight. The same function SHALL be used by both the backtest simulator and the live strategy so that identical inputs yield identical decisions, with no structurally-divergent input (such as futures-weighted vs equal-weighted VWAP) remaining between the two paths.

#### Scenario: Aligned bullish inputs produce a bullish ratio
- **WHEN** 1h/15m EMAs are aligned bullish (9>20>50, price above 50), 5m price is above its 50 EMA, price closed above daily Camarilla R3 and above PDH, and PCR > 1.1
- **THEN** `BiasResult.score` is strongly positive and the bucket maps to a PE-heavy sell ratio (e.g. 4 PE : 2 CE or 5 PE complete-bull)

#### Scenario: Conflicting inputs produce a neutral ratio
- **WHEN** higher-timeframe signals disagree and the net score falls within the neutral band
- **THEN** the bucket is `neutral` with a balanced (1:1) ratio or no-trade, per configuration

#### Scenario: Same inputs are deterministic
- **WHEN** the function is called twice with identical inputs
- **THEN** it returns an identical `BiasResult` with no side effects

#### Scenario: No VWAP input on either path

- **WHEN** the live strategy and the backtest simulator each assemble bias inputs for the same
  bar with all other inputs equal
- **THEN** neither passes a VWAP value, the scoring weight sum excludes any VWAP weight, and the
  two paths produce the same `BiasResult` with no VWAP-driven divergence
