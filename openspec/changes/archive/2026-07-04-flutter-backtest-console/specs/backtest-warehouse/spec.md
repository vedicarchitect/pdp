## MODIFIED Requirements

### Requirement: Backtest management UI
The frontend SHALL provide a Flutter backtest console that lists runs in a sortable, filterable table
(profit-factor, Sharpe, max drawdown, net, kind, PASS/REVIEW, promotion status), a run-detail view
with equity and drawdown charts, per-day P&L, metric cards, and a config viewer, an interactive
walk-forward view showing per-fold IS-vs-OOS metrics with the stitched-OOS curve and verdict, a
day drill-down showing the decision trace (reason-coded why-entry/why-exit events, with the full
per-minute trace on demand) with trades and legs, a paper-comparison view overlaying a run against
paper results, a promotion view showing the rationale/evidence, and a data-coverage/gap-radar panel.
New routes and components SHALL be covered by Flutter widget/integration tests (`flutter analyze &&
flutter test`).

#### Scenario: A user inspects a walk-forward run
- **WHEN** a user opens a walk-forward run in the console
- **THEN** the per-fold IS-vs-OOS table, the stitched-OOS equity curve, and the PASS/REVIEW verdict are displayed

#### Scenario: A user inspects why-entry/why-exit for a day
- **WHEN** a user opens a day drill-down in a run
- **THEN** the reason-coded decision events are shown with trades and legs, and the full per-minute trace can be loaded on demand

### Requirement: In-UI optimization and leaderboard
The frontend SHALL let a user launch a single backtest, sweep, or walk-forward from the console
(choosing a strategy from the registry with an editable param form, window, index, and objective),
track its progress live over the jobs WebSocket, and view an out-of-sample leaderboard ranking
configs by a chosen metric with the selected best param.

#### Scenario: A user launches and tracks an optimization
- **WHEN** a user starts a walk-forward from the UI
- **THEN** progress is shown live and, on completion, the run appears in the runs table and the OOS leaderboard

#### Scenario: A user launches from a strategy picker
- **WHEN** a user selects a strategy from the picker, edits its params, and sets a window and index
- **THEN** the launch uses those params (no raw-JSON box) and the run appears on completion
