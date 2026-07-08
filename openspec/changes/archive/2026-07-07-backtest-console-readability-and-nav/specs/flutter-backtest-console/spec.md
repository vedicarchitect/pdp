## MODIFIED Requirements

### Requirement: Run history and leaderboard console
The console SHALL list runs in a sortable, filterable table (by metric, kind, verdict, promotion
state, and index) with an all-index selector (NIFTY/BANKNIFTY/SENSEX), defaulting to a per-index
grouped layout, and SHALL show the sweep leaderboard ranking combinations by the objective metric
with the selected best param. Every run's Verdict SHALL render as a PASS/REVIEW chip (never `--`,
since single runs are now graded), and the console SHALL present a plain-English per-index
leaderboard card naming the best/promoted config (e.g. "NIFTY: best = ST(10,2)/15m, PF 5.72, PASS,
promoted") rather than raw combo JSON.

#### Scenario: Runs are filtered and sorted
- **WHEN** the user filters by kind `walkforward` and sorts by profit-factor descending
- **THEN** only walk-forward runs are shown, ordered by profit-factor descending

#### Scenario: Runs are grouped by index

- **WHEN** the Runs tab is opened
- **THEN** runs are grouped per index (NIFTY/BANKNIFTY/SENSEX) and the index selector filters
  them, and each run shows a PASS/REVIEW verdict chip rather than `--`

#### Scenario: The sweep leaderboard is shown
- **WHEN** the user opens a sweep
- **THEN** its combinations are listed ranked by the objective with the best param highlighted

#### Scenario: A plain-English leaderboard card is shown

- **WHEN** the user views the leaderboard
- **THEN** a per-index card names the best config with its metrics, verdict, and promotion state
  in plain language, not raw JSON

### Requirement: Coverage and gap-radar panel
The console SHALL show a data-coverage panel (per index and family) backed by `GET /api/v1/coverage`,
flagging missing input families (spot, options, weekly Camarilla, VIX) per date, with a one-click
backfill action per gap whose job progress streams over the jobs WebSocket. The panel SHALL load
without timing out — it relies on the coverage API's sub-2s response and a sufficient client
receive-timeout backstop — and SHALL default to a per-index grouped layout. It SHALL NOT reference
a futures family (removed upstream).

#### Scenario: The coverage panel loads without timing out

- **WHEN** the user opens the Coverage tab
- **THEN** the panel loads without a Dio timeout / DioException and shows per-index, per-family
  coverage

#### Scenario: A gap is filled from the panel
- **WHEN** the user clicks backfill on a flagged gap
- **THEN** a backfill job starts with live progress and the panel reflects the closed gap on refresh

### Requirement: Few-clicks launch flow
The console SHALL let a user launch a single run, sweep, or walk-forward with a schema-driven param
form (no raw-JSON box), a window, an index, and an objective, tracking progress live over the jobs
WebSocket. The Sweeps and folds views SHALL carry plain-English explainer copy: what a sweep is
("we tried N parameter sets; this one had the best profit-factor"), what walk-forward PASS proves
("optimized on past data, then tested on unseen data — PASS means it held up"), and a one-line
verdict reason per run.

#### Scenario: A user launches from a schema-driven form

- **WHEN** a user selects a strategy, edits its params in the form, and sets a window/index/objective
- **THEN** the launch uses those params with no raw-JSON box and progress streams live

#### Scenario: Sweeps and folds carry layman copy

- **WHEN** the user views a sweep or walk-forward folds
- **THEN** plain-English copy explains what the sweep/walk-forward means and gives a one-line
  verdict reason
