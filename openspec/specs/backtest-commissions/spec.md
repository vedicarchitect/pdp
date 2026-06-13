# backtest-commissions Specification

## Purpose
TBD - created by archiving change backtest-commissions. Update Purpose after archive.
## Requirements
### Requirement: Commission calculation per fill
The system SHALL provide a `CommissionCalculator` that computes all Indian exchange cost components for a single options order fill. The calculator SHALL accept: `side` (BUY or SELL), `turnover_inr` (qty × price in absolute rupees), and return a `CommissionBreakdown` with each component as a named field and a `total_inr` sum.

Components computed:
- **Brokerage**: flat ₹20 per order (both sides)
- **STT**: 0.1% of turnover, sell-side only
- **Exchange transaction charge**: 0.03553% of turnover, both sides
- **SEBI charge**: ₹10 per ₹1 crore of turnover (= 0.00001 × turnover), both sides
- **Stamp duty**: 0.004% of turnover, buy-side only
- **GST**: 18% of (brokerage + exchange txn charge + SEBI charge), both sides

#### Scenario: Sell-side commission for 1 NIFTY lot at ₹100 premium
- **WHEN** `calculate(side="SELL", turnover_inr=7500.0)` is called (75 units × ₹100)
- **THEN** brokerage = 20.00, STT = 7.50, txn = 2.66, SEBI = 0.08, stamp = 0.00, GST = 4.09, total ≈ 34.33

#### Scenario: Buy-side commission for 1 NIFTY lot at ₹100 premium
- **WHEN** `calculate(side="BUY", turnover_inr=7500.0)` is called
- **THEN** STT = 0.00 (buy-side exempt), stamp = 0.30, brokerage = 20.00, txn = 2.66, total ≈ 27.13

#### Scenario: Zero-turnover fill is free
- **WHEN** `calculate(side="SELL", turnover_inr=0.0)` is called
- **THEN** total_inr = 20.00 (brokerage only)

---

### Requirement: Commission rates configurable via settings
The system SHALL read all commission rate parameters from a `BacktestCommissionSettings` model in `src/pdp/settings.py`. Default values SHALL match current NSE/BSE circular rates. All rates SHALL be overridable via environment variables prefixed `BACKTEST_COMMISSION__`.

#### Scenario: Default rates match NSE schedule
- **WHEN** `BacktestCommissionSettings()` is instantiated with no overrides
- **THEN** `stt_rate = 0.001`, `txn_charge_rate = 0.0003553`, `sebi_rate = 0.00001`, `stamp_duty_rate = 0.00004`, `gst_rate = 0.18`, `brokerage_per_order = 20.00`

#### Scenario: Rate override via environment variable
- **WHEN** environment variable `BACKTEST_COMMISSION__BROKERAGE_PER_ORDER=15` is set
- **THEN** `BacktestCommissionSettings().brokerage_per_order == Decimal("15")`

---

### Requirement: Null commission calculator for raw comparison
The system SHALL provide a `NullCommissionCalculator` that returns zero for all components, enabling `--no-commission` mode for gross-premium-only analysis.

#### Scenario: Null calculator returns zero total
- **WHEN** `NullCommissionCalculator().calculate(side="SELL", turnover_inr=50000.0)` is called
- **THEN** `total_inr = 0.00` and all component fields = 0.00

