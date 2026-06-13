## ADDED Requirements

### Requirement: Backtest output reports gross and net P&L
The system SHALL report both gross P&L (premium collected minus premium paid, no costs) and net P&L (gross minus all commissions) in backtest output. Both values SHALL be present in the per-day result dict and the final summary table. The per-day `Trade` record SHALL carry a `commission_inr` field populated by `CommissionCalculator` at fill time.

#### Scenario: Per-day output shows gross, commission, and net columns
- **WHEN** `backtest_multiday.py` completes simulation for a trading day
- **THEN** the printed day summary line shows `Net premium: <gross>  Charges: -<commission_total>  Realized: <net>` where `net = gross - commission_total`

#### Scenario: Final summary includes net P&L totals
- **WHEN** the multi-day backtest summary is printed
- **THEN** each day row in the summary table includes a `Net` column (= gross - commission), and the footer shows `Total gross`, `Total commission`, `Total net`, and `Avg daily net`

#### Scenario: Commission is calculated per fill not per day
- **WHEN** a `Trade` is recorded (BUY or SELL)
- **THEN** `trade.commission_inr` is set to the result of `CommissionCalculator.calculate(side=trade.side, turnover_inr=trade.qty * trade.price)` at the time of fill

#### Scenario: --no-commission flag suppresses cost deduction
- **WHEN** `backtest_multiday.py --no-commission` is run
- **THEN** all `commission_inr` values are 0.00, gross P&L equals net P&L, and the output notes `[commissions disabled]`
