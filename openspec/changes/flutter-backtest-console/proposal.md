## Why

The backtest warehouse is core to PDP — "our strategy stands on top of exhaustive backtest results
and insights" — but there is no real UI. The current Flutter `backtest` feature is a scaffold that
ignores house convention (no `Source`/mock split, inline colors), shows only an equity line and a
raw-JSON config box, and cannot surface days, trades, folds, the sweep leaderboard, coverage/gap
radar, promotion rationale, the decision trace, or paper comparison. Changes 1–4 build the backend
(results warehouse + decision trace, data coverage, paper comparison, strategy registry); this change
delivers the console that makes all of it usable in a few clicks, at enterprise quality.

## What Changes

- **House-convention refactor**: rebuild the `backtest` feature as `domain/data/application/
  presentation` with a `BacktestSource` interface + **live and mock** implementations behind
  `AppConfig.useMock`; all colors/P&L styling from `core/theme/` (no inline `Color(...)`).
- **Console**: run-history table (filter/sort by metric, verdict chips, promotion state), the sweep
  leaderboard with best-param ranking, and an all-index selector (NIFTY/BANKNIFTY/SENSEX).
- **Run detail**: equity **+ drawdown** chart, day-by-day P&L table, trade drill-down, the decision
  trace (why entry / why exit; full per-minute on demand), and the walk-forward per-fold IS-vs-OOS
  view with the stitched-OOS curve and verdict.
- **Launch flow**: a strategy picker (from `/api/v1/strategies`, change 4) with an editable param
  form, a time-period picker, and an index picker — few clicks to run; live job progress over
  `/ws/jobs`.
- **Data coverage + gap radar panel** (change 2): per-index/family coverage with one-click backfill
  buttons.
- **Promotion view** (change 1): shows the rationale/evidence before promoting; **paper-comparison
  view** (change 3): backtest-vs-paper per-day and minute-level divergence.
- **Export/download**: CSV/JSON of runs, days, trades, and leaderboards (desktop save).
- **Deep-insights links** into the OpenSearch backtest/coverage dashboards.

## Capabilities

### New Capabilities
- `flutter-backtest-console`: the Flutter backtest console UI — history/leaderboard, run-detail
  drill-downs, launch flow with strategy/param/window/index pickers, coverage/gap-radar panel,
  promotion and paper-comparison views, and export.

### Modified Capabilities
- `backtest-warehouse`: update the "Backtest management UI" and "In-UI optimization and leaderboard"
  requirements to the Flutter console with the new panels (coverage, decision trace, paper
  comparison, promotion rationale), and fix the stale Playwright reference to Flutter widget/
  integration tests.

## Impact

- Frontend: `app/lib/features/backtest/**` (rebuilt to house convention),
  `app/lib/core/{theme,config,network}/**`; consumes the change 1–4 APIs
  (`/strangle-backtests/*` incl. sweeps/decisions/promotion/vs-paper, `/coverage`, `/strategies`) and
  `/ws/jobs`.
- Verification shifts from Playwright to `flutter analyze && flutter test`.
- Depends on changes 1–4 for its backing APIs.
