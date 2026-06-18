## Why

PDP's backtest engine (`src/pdp/backtest/`) handles directional indicator-based strategies using OHLCV bars — it doesn't support parametric multi-leg options strategies with SL/target, trailing stops, re-entry, or strike selection logic. Platforms like StockMock let traders backtest options strategies with time-based entry/exit, combined or per-leg stop losses, trailing SL, re-entry/re-execute on SL hit, and strike selection by ATM offset, premium, or delta. Without this, PDP users can't validate options strategies against historical data.

Additionally, the existing `src/pdp/backtest/routes.py` is defined but **not registered** in `main.py`, so even the current backtest results are not accessible via the API.

## What Changes

- **Options strategy spec**: New strategy configuration schema in `src/pdp/backtest/options_strategy.py` supporting: entry time (IST), exit time (IST), underlying, expiry selection (weekly/monthly/N-days-before), leg definitions with strike selection (ATM±N, by-premium, by-delta), SL/target per-leg and combined, trailing SL, re-entry (re-open same structure on SL hit, max N times), and basic adjustments (roll on expiry approach).
- **Options replay engine**: Extension of `sim.py` to replay `expired_option_bars` for multi-leg strategies — match bars to legs by strike/expiry/type, track P&L per leg and combined, apply SL/target/trailing logic bar-by-bar.
- **Register backtest routes**: Register the existing `src/pdp/backtest/routes.py` router in `main.py` — the read-only endpoints for listing and viewing backtest results become accessible.
- **New `POST /api/v1/backtests/run`**: Submit a backtest job (async via proposal #5's job runner, or synchronous if #5 is not yet implemented). Returns job ID or results.
- **Frontend `/backtest` route**: Strategy configuration form (entry/exit times, legs with strike selection, SL/target params), run button, results view (equity curve, P&L chart, drawdown chart, weekday/day-wise tables, trade log).

> **Note**: This proposal does NOT modify `sim.py`, `strategy_config.py`, `day_loader.py`, or `scripts/backtest_sweep.py` — those are guarded by the in-flight `configurable-strategy-backtest-sweep` change. The options strategy module is additive and sits alongside the existing backtest engine.

## Capabilities

### New Capabilities
- `options-strategy-backtest`: Parametric multi-leg options strategy backtesting with SL/target/trailing/re-entry support, strike selection, and results visualization.

### Modified Capabilities
- `backtest`: Register existing routes in `main.py`; add `POST /api/v1/backtests/run` endpoint.
- `backtest-config-yaml`: Document options strategy YAML schema alongside existing indicator strategy schema.

## Impact

- `src/pdp/backtest/options_strategy.py` — NEW (options strategy spec + replay engine)
- `src/pdp/backtest/options_replay.py` — NEW (bar-by-bar replay with SL/target/trailing logic)
- `src/pdp/backtest/routes.py` — MODIFIED (add `POST /api/v1/backtests/run`)
- `src/pdp/main.py` — MODIFIED (register `backtest.routes.router`)
- `tests/backtest/test_options_strategy.py` — NEW
- `tests/backtest/test_options_replay.py` — NEW
- `backtest/configs/options_example.yaml` — NEW (example config)
- `frontend/src/routes/backtest.tsx` — MODIFIED (full backtest UI)
- `frontend/src/components/backtest/StrategyForm.tsx` — NEW
- `frontend/src/components/backtest/ResultsView.tsx` — NEW
- `frontend/src/components/backtest/EquityCurve.tsx` — NEW
- `frontend/src/components/backtest/TradeLog.tsx` — NEW
- `frontend/src/components/backtest/DayWiseTable.tsx` — NEW
- Does NOT touch: `sim.py`, `strategy_config.py`, `day_loader.py`, `scripts/backtest_sweep.py` (in-flight change guard).
