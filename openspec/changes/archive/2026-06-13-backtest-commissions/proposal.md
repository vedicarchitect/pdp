## Why

Backtest P&L is currently gross — it counts every rupee of simulated premium without deducting the real costs of placing orders on Indian exchanges. For short-options strategies like SuperTrend Short, a single 3-lot round-trip costs ₹150–400 in STT, exchange charges, brokerage, and taxes. Ignoring this makes marginal strategies look profitable when they are not, and causes live results to diverge systematically from backtest expectations.

## What Changes

- New `CommissionCalculator` in `src/pdp/backtest/` that models all Indian exchange cost components per order leg.
- `BacktestEngine` records gross and net P&L separately; `backtest_multiday.py` output shows both side-by-side.
- Commission parameters (brokerage flat fee, STT rate, txn charge rate, SEBI rate, stamp duty rate, GST rate) are configurable via `settings.py` with sensible Indian-market defaults.
- Per-underlying lot-size config (NIFTY=75, BANKNIFTY=15, SENSEX=20) used for turnover calculations.
- New `backtest_result` output fields: `gross_pnl`, `net_pnl`, `total_commission`, `commission_breakdown` (per component).

## Capabilities

### New Capabilities
- `backtest-commissions`: Realistic Indian exchange commission modeling for backtest engine — STT, exchange txn charges, brokerage, GST, SEBI charges, stamp duty; gross vs net P&L reporting.

### Modified Capabilities
- `backtest`: Backtest engine now tracks net P&L alongside gross; `BacktestTrade` record gains `commission_inr` and `net_pnl` fields.

## Impact

- `src/pdp/backtest/engine.py` — `BacktestTrade` dataclass extended; `BacktestEngine` calls `CommissionCalculator` on each simulated fill.
- `src/pdp/backtest/indicators.py` — no changes.
- `src/pdp/settings.py` — new `BacktestCommissionSettings` nested model with all rate defaults.
- `backtest_multiday.py` — summary table gains gross/net columns; per-day breakdown includes commission total.
- `src/pdp/cli/backtest_commands.py` — `--no-commission` flag to disable for raw comparison.
- New file: `src/pdp/backtest/commissions.py`.
- Tests: `tests/backtest/test_commissions.py` (unit), updated `tests/backtest/` integration fixtures.
- No API surface changes; no frontend changes; no database schema changes.
