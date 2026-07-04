## 1. House-convention refactor

- [ ] 1.1 Add `BacktestSource` interface in `app/lib/features/backtest/data/` with `BacktestLiveSource` (ApiClient) + `BacktestMockSource` (fixtures), selected by `AppConfig.useMock` via a Riverpod provider; migrate screens off the direct `BacktestRepository`.
- [ ] 1.2 Move all colors/P&L styling to `core/theme/` tokens (remove inline `Color(...)`); structure the feature as `domain/data/application/presentation`.

## 2. Console + leaderboard

- [ ] 2.1 Runs table: filter/sort by metric, verdict + promotion chips, all-index selector (NIFTY/BANKNIFTY/SENSEX).
- [ ] 2.2 Sweep leaderboard tab: ranked combos + best-param highlight (from `/strangle-backtests/sweeps/{id}`).

## 3. Run detail

- [ ] 3.1 Equity + drawdown chart (dual series, `fl_chart`).
- [ ] 3.2 Day-by-day P&L table + trade drill-down.
- [ ] 3.3 Decision-trace panel: reason-coded events by default, "load full per-minute trace" on demand (`runs/{id}/decisions`).
- [ ] 3.4 Walk-forward per-fold IS-vs-OOS + stitched-OOS curve + verdict.

## 4. Launch flow

- [ ] 4.1 Strategy picker from `GET /api/v1/strategies` + schema-driven editable param form (replace raw-JSON box).
- [ ] 4.2 Time-period + index pickers; kind selector (single/sweep/walkforward); launch as async job.
- [ ] 4.3 Live job progress over `/ws/jobs`; run appears in the table on completion.

## 5. Coverage + gap radar panel

- [ ] 5.1 Coverage grid from `GET /api/v1/coverage` (per index/family, gap flags).
- [ ] 5.2 One-click backfill button per gap → housekeeping job with live progress; refresh reflects closed gap.

## 6. Promotion + paper comparison

- [ ] 6.1 Promotion dialog showing rationale/evidence + optional note before promoting (PASS only).
- [ ] 6.2 Paper-comparison view: overlay + per-day divergence (`runs/{id}/vs-paper`); expand a date to minute-level diff.

## 7. Export + dashboards

- [ ] 7.1 CSV/JSON export of runs/days/trades/leaderboards to disk (desktop).
- [ ] 7.2 Deep-links into the OpenSearch backtest/coverage dashboards.

## 8. Tests + spec sync

- [ ] 8.1 Widget tests per screen off `BacktestMockSource`; integration test for launch→job→appears-in-table.
- [ ] 8.2 `cd app && flutter analyze && flutter test` clean; `openspec validate flutter-backtest-console --strict` passes.
