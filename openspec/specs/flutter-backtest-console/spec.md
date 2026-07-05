# flutter-backtest-console Specification

## Purpose
The Flutter backtest console — house-convention feature (`domain/data/application/presentation`
layering, `BacktestSource` interface with live+mock impls) that makes the backend backtest warehouse
usable in a few clicks: run history/leaderboard, run-detail drill-downs, a strategy-registry-driven
launch flow, a data-coverage/gap-radar panel, promotion rationale, backtest-vs-paper comparison, and
export/dashboard links.

## Requirements

### Requirement: House-convention feature architecture
The backtest feature SHALL follow the app's house convention: `domain/data/application/presentation`
layering with a `BacktestSource` interface backed by both a live implementation and a mock
implementation selected via `AppConfig.useMock`, and all colors/P&L styling SHALL come from
`core/theme/` (no inline `Color(...)`).

#### Scenario: Mock source drives the UI without a backend
- **WHEN** the app runs with `AppConfig.useMock` enabled
- **THEN** the backtest console renders from the mock `BacktestSource` without any network calls

#### Scenario: P&L styling comes from the theme
- **WHEN** profit and loss values are displayed
- **THEN** their colors come from `core/theme/` tokens, not inline color literals

### Requirement: Run history and leaderboard console
The console SHALL list runs in a sortable, filterable table (by metric, kind, verdict, promotion
state) with an all-index selector (NIFTY/BANKNIFTY/SENSEX), and SHALL show the sweep leaderboard
ranking combinations by the objective metric with the selected best param.

#### Scenario: Runs are filtered and sorted
- **WHEN** the user filters by kind `walkforward` and sorts by profit-factor descending
- **THEN** only walk-forward runs are shown, ordered by profit-factor descending

#### Scenario: The sweep leaderboard is shown
- **WHEN** the user opens a sweep
- **THEN** its combinations are listed ranked by the objective with the best param highlighted

### Requirement: Run detail with deep insights
The run-detail view SHALL show an equity-and-drawdown chart, a day-by-day P&L table, a trade
drill-down, the decision trace (reason-coded why-entry/why-exit events, with the full per-minute
trace available on demand), and — for walk-forward runs — the per-fold IS-vs-OOS view with the
stitched-OOS curve and the PASS/REVIEW verdict.

#### Scenario: A day's why-entry/why-exit is inspectable
- **WHEN** the user opens a day in a run
- **THEN** the decision events with reason codes (e.g. ST flip → scale-in → entry → rollup → exit) are shown, and the full per-minute trace can be loaded on demand

#### Scenario: A walk-forward run shows folds and verdict
- **WHEN** the user opens a walk-forward run
- **THEN** the per-fold IS-vs-OOS metrics, the stitched-OOS equity curve, and the verdict are displayed

### Requirement: Few-clicks launch flow
The launch flow SHALL let the user pick a strategy from `GET /api/v1/strategies` with an editable
param form (no raw-JSON box), a time-period picker, and an index picker, then launch a single
backtest, sweep, or walk-forward as an async job whose progress streams live over the jobs
WebSocket; on completion the run appears in the console.

#### Scenario: A backtest is launched in a few clicks
- **WHEN** the user selects a strategy, edits params, sets a window and index, and launches
- **THEN** a job starts, progress streams live, and on completion the run appears in the runs table

### Requirement: Coverage and gap-radar panel
The console SHALL show a data-coverage panel (per index and family) backed by `GET /api/v1/coverage`,
flagging missing input families (e.g. VWAP/spot, weekly Camarilla, VIX, futures) per date, with a
one-click backfill action per gap whose job progress streams over the jobs WebSocket.

#### Scenario: A gap is filled from the panel
- **WHEN** the user clicks backfill on a flagged gap
- **THEN** a backfill job starts with live progress and the panel reflects the closed gap on refresh

### Requirement: Promotion and paper-comparison views
The console SHALL show, on a PASS run, the promotion rationale/evidence (threshold-vs-actual,
stitched-OOS, positive-fold fraction) before promoting, and SHALL provide a paper-comparison view
that overlays a run against paper results for the same strategy with per-day and on-demand
minute-level divergence.

#### Scenario: Promotion shows evidence before promoting
- **WHEN** the user opens the promote action on a PASS run
- **THEN** the rationale/evidence is displayed and an optional note can be entered before confirming

#### Scenario: A run is compared against paper
- **WHEN** the user opens the paper-comparison view for a run whose strategy has paper trades
- **THEN** the backtest and paper series are overlaid per day with divergence, and a date can be expanded to a minute-level diff

### Requirement: Export and dashboard links
The console SHALL let the user export runs, days, trades, and leaderboards as CSV/JSON (saved to
disk on desktop), and SHALL provide links into the OpenSearch backtest/coverage dashboards for deep
analytics.

#### Scenario: A run's data is exported
- **WHEN** the user exports a run's day/trade data
- **THEN** a CSV/JSON file is written to disk with that run's data

### Requirement: Console covered by Flutter tests
The backtest console's routes and widgets SHALL be covered by Flutter widget/integration tests (not
Playwright), runnable via `flutter analyze && flutter test`.

#### Scenario: Console tests run in the Flutter toolchain
- **WHEN** `flutter analyze && flutter test` is run
- **THEN** the backtest console's widget/integration tests execute and pass
