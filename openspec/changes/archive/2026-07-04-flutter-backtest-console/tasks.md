## 1. House-convention refactor

- [x] 1.1 Add `BacktestSource` interface in `app/lib/features/backtest/data/` with `BacktestLiveSource` (ApiClient) + `BacktestMockSource` (fixtures), selected by `AppConfig.useMock` via a Riverpod provider; migrate screens off the direct `BacktestRepository`.
- [x] 1.2 Move all colors/P&L styling to `core/theme/` tokens (remove inline `Color(...)`); structure the feature as `domain/data/application/presentation`.

## 2. Console + leaderboard

- [x] 2.1 Runs table: filter/sort by metric, verdict + promotion chips, all-index selector (NIFTY/BANKNIFTY/SENSEX).
- [x] 2.2 Sweep leaderboard tab: ranked combos + best-param highlight (from `/strangle-backtests/sweeps/{id}`).

## 3. Run detail

- [x] 3.1 Equity + drawdown chart (dual series, `fl_chart`).
- [x] 3.2 Day-by-day P&L table + trade drill-down.
- [x] 3.3 Decision-trace panel: reason-coded events by default, "load full per-minute trace" on demand (`runs/{id}/decisions`).
- [x] 3.4 Walk-forward per-fold IS-vs-OOS + stitched-OOS curve + verdict.

## 4. Launch flow

- [x] 4.1 Strategy picker from `GET /api/v1/strategies` + schema-driven editable param form (replace raw-JSON box).
- [x] 4.2 Time-period + index pickers; kind selector (single/sweep/walkforward); launch as async job.
- [x] 4.3 Live job progress over `/ws/jobs`; run appears in the table on completion.

## 5. Coverage + gap radar panel

- [x] 5.1 Coverage grid from `GET /api/v1/coverage` (per index/family, gap flags).
- [x] 5.2 One-click backfill button per gap → housekeeping job with live progress; refresh reflects closed gap.

## 6. Promotion + paper comparison

- [x] 6.1 Promotion dialog showing rationale/evidence + optional note before promoting (PASS only).
- [x] 6.2 Paper-comparison view: overlay + per-day divergence (`runs/{id}/vs-paper`); expand a date to minute-level diff.

## 7. Export + dashboards

- [x] 7.1 CSV/JSON export of runs/days/trades/leaderboards to disk (desktop).
- [x] 7.2 Deep-links into the OpenSearch backtest/coverage dashboards.

## 8. Tests + spec sync

- [x] 8.1 Widget tests per screen off `BacktestMockSource`; integration test for launch→job→appears-in-table.
- [x] 8.2 `cd app && flutter analyze && flutter test` clean; `openspec validate flutter-backtest-console --strict` passes.
