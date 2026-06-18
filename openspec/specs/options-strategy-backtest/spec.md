# options-strategy-backtest Specification

## Purpose
TBD - created by archiving change 2026-06-17-options-strategy-backtester. Update Purpose after archive.
## Requirements
### Requirement: Options strategy configuration schema

The system SHALL support a YAML-based options strategy configuration with fields: `type: options-strategy`, `name`, `underlying`, `date_range` (from/to), `expiry_selection` (weekly/monthly/nearest), `entry` (time_ist, legs with strike selection), `exit` (time_ist), `risk` (combined_sl, combined_target, per_leg_sl, trailing_sl, re_entry), `lot_size`, and `commissions`. Strike selection SHALL support methods: `atm_offset` (offset from ATM), `by_premium` (closest to target premium), and `by_delta` (closest to target delta, degradable).

#### Scenario: Parse valid options strategy YAML
- **WHEN** a YAML file with `type: options-strategy` and valid fields is loaded
- **THEN** the config parses successfully into an `OptionsStrategyConfig` object with all fields populated

#### Scenario: Invalid config returns validation error
- **WHEN** a YAML file is missing required `entry.time_ist` field
- **THEN** a validation error is raised with a descriptive message

---

### Requirement: Bar-by-bar options replay engine

The system SHALL replay `option_bars` data bar-by-bar for each trading day in the configured date range. At `entry.time_ist`, the engine SHALL resolve strikes per the selection method, open positions, and begin tracking P&L. At each subsequent bar, the engine SHALL evaluate SL/target/trailing conditions. At `exit.time_ist`, the engine SHALL force-close all positions. The replay SHALL produce per-day and aggregate results.

#### Scenario: Entry at configured time
- **WHEN** the replay reaches 09:20 IST for a day with available bars
- **THEN** strikes are resolved, positions are opened at the bar's close price, and tracking begins

#### Scenario: Combined SL triggers exit
- **WHEN** the combined P&L of all legs reaches -50 points (with `combined_sl: {type: points, value: 50}`)
- **THEN** all legs are closed, exit_reason is `"combined_sl"`, and the trade is recorded

#### Scenario: Trailing SL adjusts and triggers
- **WHEN** combined P&L reaches +25 points (trail_after=20, trail_step=5), then drops back
- **THEN** the trailing SL level is set at +20 (25 - 5 = 20), and triggers when P&L drops to +20

#### Scenario: Re-entry after SL
- **WHEN** SL is hit and `re_entry.enabled=true` with `max_count=2` and this is the first SL
- **THEN** a new set of positions is opened at current strikes, re_entry count incremented

#### Scenario: Forced exit at configured time
- **WHEN** the replay reaches 15:10 IST with open positions
- **THEN** all legs are closed at the bar's close price, exit_reason is `"time_exit"`

#### Scenario: Missing bar data for a day
- **WHEN** a trading day has no `option_bars` for the required strikes
- **THEN** the day is skipped with a warning logged, and results exclude that day

---

### Requirement: Backtest results model

The system SHALL produce results containing: `total_pnl`, `total_trades`, `win_rate`, `max_drawdown`, `max_drawdown_pct`, `sharpe_ratio`, `equity_curve` (date vs cumulative P&L), `daily_pnl` (per-day breakdown), `weekday_stats` (avg P&L and win rate per weekday), `trade_log` (detailed per-trade records with legs, entry/exit times, P&L, exit reason), and `commissions_total`.

#### Scenario: Win rate calculation
- **WHEN** 60 out of 100 trading days had positive P&L
- **THEN** win_rate = 0.60

#### Scenario: Weekday stats
- **WHEN** backtest covers 20 Mondays with average P&L of +₹500
- **THEN** weekday_stats.monday = {avg_pnl: 500, count: 20, ...}

---

### Requirement: Backtest API endpoint

The system SHALL expose `POST /api/v1/backtests/run` accepting a JSON body matching the options strategy config schema. The endpoint SHALL execute the backtest and return the results. For date ranges exceeding 90 days, the endpoint SHALL return HTTP 400 with a message recommending the async job runner (when available).

#### Scenario: Run backtest via API
- **WHEN** `POST /api/v1/backtests/run` is called with a valid 30-day short straddle config
- **THEN** HTTP 200 is returned with complete backtest results

#### Scenario: Large date range rejected
- **WHEN** `POST /api/v1/backtests/run` is called with a 6-month date range
- **THEN** HTTP 400 is returned with message "Date range exceeds 90 days. Use async job runner for large backtests."

---

### Requirement: Backtest frontend

The system SHALL provide a `/backtest` route with a strategy configuration form and a results view. The form SHALL allow selecting underlying, entry/exit times, adding legs with strike selection, and configuring SL/target/trailing/re-entry parameters. The results view SHALL display equity curve, daily P&L table, weekday statistics, and a detailed trade log.

#### Scenario: Configure and run backtest from UI
- **WHEN** a user fills in the strategy form and clicks "Run Backtest"
- **THEN** a loading indicator appears, and results render when the API responds

#### Scenario: Results display equity curve
- **WHEN** backtest results are received with 60 daily data points
- **THEN** an equity curve chart renders showing cumulative P&L over 60 days

