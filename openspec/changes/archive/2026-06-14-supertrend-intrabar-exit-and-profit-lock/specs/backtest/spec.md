## ADDED Requirements

### Requirement: 1-minute option chain store

The backtest SHALL pre-load option bars at 1-minute resolution alongside the existing
5-minute chain store, in a separate `_chain_store_1m`, using the same `load_expiry_chain`
function with `tf_min=1`. The 1-minute store SHALL cover the same expiries and trade dates
as the 5-minute store and SHALL be populated before the day-loop begins (zero MongoDB
round-trips on the hot path).

The 1-minute store is used exclusively for pricing the ST-touch intra-bar exit. If a
contract's 1-minute bars are unavailable, the exit price SHALL fall back to the 5-minute
bar's close price.

#### Scenario: 1-minute option bar found at touch time
- **WHEN** an ST touch is detected at 1-minute timestamp 10:12 for a CE 23,400 leg
- **THEN** the exit price is the CE 23,400 bar's 1-minute close at 10:12 from `_chain_store_1m`

#### Scenario: 1-minute option bar unavailable at touch time
- **WHEN** no 1-minute bar is within tolerance of the touch timestamp
- **THEN** the exit price falls back to the 5-minute bar's close price from `_chain_store`
