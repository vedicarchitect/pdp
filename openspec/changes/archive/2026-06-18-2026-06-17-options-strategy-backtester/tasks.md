## 1. Pre-implementation data verification

- [x] 1.1 Query MongoDB `expired_option_bars` collection: `db.expired_option_bars.findOne()` — document field names (strike, expiry, option_type, open, high, low, close, oi, iv, volume)
- [x] 1.2 Check strike/expiry coverage: `db.expired_option_bars.distinct("expiry")` — verify at least 3 months of weekly expiries exist
- [x] 1.3 Check if `delta` field exists in `expired_option_bars` — if not, document by-delta fallback

## 2. Options strategy configuration

- [x] 2.1 Create `src/pdp/backtest/options_strategy.py` — Pydantic models: `StrikeSelection`, `LegConfig`, `RiskConfig`, `EntryConfig`, `ExitConfig`, `OptionsStrategyConfig`
- [x] 2.2 Implement YAML parsing: `OptionsStrategyConfig.from_yaml(path)` — load and validate config
- [x] 2.3 Create `backtest/configs/options_short_straddle.yaml` — example: short straddle with SL 50pts, target 30pts, trailing 20/5, re-entry 2x
- [x] 2.4 Test: parse example config, verify all fields resolve correctly

## 3. Options replay engine

- [x] 3.1 Create `src/pdp/backtest/options_replay.py` — `OptionsReplayEngine` class
- [x] 3.2 Implement data loading: query `option_bars` for date range, group by date and (strike, expiry, type)
- [x] 3.3 Implement strike resolution: ATM offset (from spot in `market_bars`), by-premium (closest to target), by-delta (if available)
- [x] 3.4 Implement entry logic: at `entry_time_ist`, resolve strikes, record entry prices from bars
- [x] 3.5 Implement bar-by-bar P&L tracking: compute combined and per-leg MTM P&L at each bar
- [x] 3.6 Implement SL logic: combined SL (points or %), per-leg SL, exit all legs on trigger
- [x] 3.7 Implement target logic: combined target (points or %), exit all legs on trigger
- [x] 3.8 Implement trailing SL: after `trail_after` profit, move SL up by `trail_step` on each new high
- [x] 3.9 Implement re-entry: on SL hit, if `re_entry.enabled` and count < `max_count`, re-open same structure at current strikes
- [x] 3.10 Implement forced exit: at `exit_time_ist`, close all positions
- [x] 3.11 Implement commission application: use existing `commissions.py` module
- [x] 3.12 Implement results aggregation: equity curve, daily P&L, weekday stats, trade log, win rate, max drawdown, Sharpe ratio

## 4. Backend endpoints

- [x] 4.1 Add `POST /api/v1/backtests/run` to `src/pdp/backtest/routes.py` — accepts JSON config (matching YAML schema), runs `OptionsReplayEngine`, returns `OptionsBacktestResult`
- [x] 4.2 Register `backtest.routes.router` in `src/pdp/main.py` (it was defined but never registered)
- [x] 4.3 Verify: `task dev` → existing read-only backtest endpoints are now accessible
- [x] 4.4 Verify: `curl -X POST http://localhost:8000/api/v1/backtests/run -d '...'` — returns results

## 5. Tests

- [x] 5.1 Create `tests/backtest/test_options_strategy.py` — test config parsing, YAML loading, validation
- [x] 5.2 Create `tests/backtest/test_options_replay.py` — test replay with mock bars:
  - [x] 5.2.1 Test basic entry/exit at configured times
  - [x] 5.2.2 Test combined SL triggers exit
  - [x] 5.2.3 Test combined target triggers exit
  - [x] 5.2.4 Test trailing SL adjusts and triggers
  - [x] 5.2.5 Test re-entry opens new position after SL
  - [x] 5.2.6 Test missing data (no bars for a strike) — day skipped with warning
- [x] 5.3 Run `pytest tests/backtest/ -v` — all pass (including existing tests)

## 6. Frontend backtest page

- [x] 6.1 Create `frontend/src/components/backtest/StrategyForm.tsx` — form with: underlying selector, entry/exit time pickers, expiry selection, legs builder (type/side/lots/strike selection method/offset), SL/target inputs, trailing SL toggle, re-entry toggle
- [x] 6.2 Create `frontend/src/components/backtest/ResultsView.tsx` — summary stats (total P&L, win rate, max DD, Sharpe), tabs for charts/tables
- [x] 6.3 Create `frontend/src/components/backtest/EquityCurve.tsx` — recharts LineChart with cumulative P&L, drawdown overlay
- [x] 6.4 Create `frontend/src/components/backtest/DayWiseTable.tsx` — DataTable with columns: Date, P&L, Trades, Re-entries, Exit Reason, Weekday
- [x] 6.5 Create `frontend/src/components/backtest/TradeLog.tsx` — DataTable with detailed trade log: Date, Entry Time, Exit Time, Legs (expandable), P&L, Exit Reason

## 7. Frontend integration

- [x] 7.1 Update `frontend/src/routes/backtest.tsx` — replace coming-soon skeleton with `StrategyForm` + `ResultsView`
- [x] 7.2 Wire form submission to `POST /api/v1/backtests/run` via TanStack Query mutation
- [x] 7.3 Show loading state during backtest execution
- [x] 7.4 Verify: configure a short straddle, run backtest, view results

## 8. Final verification

- [x] 8.1 Run `pytest tests/backtest/ -v` — all pass
- [x] 8.2 Run `cd frontend && npm run build` — clean build
- [x] 8.3 Run `task lint` — no lint errors in new files
- [x] 8.4 End-to-end: run a 1-month short straddle backtest from the UI, verify equity curve, trade log, and day-wise table render correctly
