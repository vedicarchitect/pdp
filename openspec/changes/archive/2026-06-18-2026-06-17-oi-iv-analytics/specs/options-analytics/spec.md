## MODIFIED Requirements

### Requirement: OI buildup classification

The system SHALL classify each option strike's market activity into one of four categories: Long Buildup (price ↑ + OI ↑), Short Buildup (price ↓ + OI ↑), Short Covering (price ↑ + OI ↓), or Long Unwinding (price ↓ + OI ↓). Classification SHALL be computed from the latest two option chain snapshots. A new endpoint `GET /api/v1/options/{underlying}/oi-buildup` SHALL return per-strike classification with price change, OI change, and OI change percentage.

#### Scenario: Strike classified as long buildup
- **WHEN** a strike's price increased by ₹5 and OI increased by 10,000 between the last two snapshots
- **THEN** the endpoint returns `classification: "long_buildup"` for that strike

#### Scenario: Strike classified as short covering
- **WHEN** a strike's price increased by ₹3 and OI decreased by 8,000
- **THEN** the endpoint returns `classification: "short_covering"` for that strike

#### Scenario: OI buildup returns current expiry by default
- **WHEN** `GET /api/v1/options/NIFTY/oi-buildup` is called without an `expiry` param
- **THEN** classification is computed for the nearest expiry

---

### Requirement: Multi-strike OI change series

The system SHALL expose `GET /api/v1/options/{underlying}/oi-series` returning OI change over time for multiple strikes. Query params SHALL include `expiry`, `interval` (5m, 15m, 1H, 1D), and optional `strikes` (default: top 10 by OI). The response SHALL be a time-series array suitable for multi-line charting.

#### Scenario: OI series for top 10 strikes
- **WHEN** `GET /api/v1/options/NIFTY/oi-series?interval=15m` is called
- **THEN** a time-series is returned with OI change data for the 10 strikes with highest absolute OI

---

### Requirement: ATM straddle price history

The system SHALL expose `GET /api/v1/options/{underlying}/straddle-history` returning a time-series of ATM straddle premium (CE + PE at ATM strike) for the specified date (default: today). The response SHALL include `timestamp`, `premium`, `ce_premium`, and `pe_premium` fields.

#### Scenario: Straddle history for today
- **WHEN** `GET /api/v1/options/NIFTY/straddle-history` is called during market hours with 20 chain snapshots available
- **THEN** 20 data points are returned showing the ATM straddle premium at each snapshot time

---

### Requirement: IV rank and percentile

The system SHALL expose `GET /api/v1/options/{underlying}/iv-history` returning `current_iv`, `iv_rank`, `iv_percentile`, `iv_high`, `iv_low`, and `lookback_days`. IV rank SHALL be computed as `(current - min) / (max - min)` over the lookback period (default 252 trading days). IV percentile SHALL be the percentage of historical days where IV was below the current IV.

#### Scenario: IV rank computation
- **WHEN** current ATM IV is 18%, 252-day min is 10%, 252-day max is 30%
- **THEN** iv_rank = (18 - 10) / (30 - 10) = 0.40

#### Scenario: IV percentile computation
- **WHEN** current ATM IV is 18% and 180 out of 252 historical days had IV below 18%
- **THEN** iv_percentile = 180 / 252 ≈ 0.714

#### Scenario: Insufficient historical data
- **WHEN** fewer than 20 trading days of IV data exist
- **THEN** the response includes `iv_rank: null` and `iv_percentile: null` with a warning message
