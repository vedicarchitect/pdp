## ADDED Requirements

### Requirement: Positional Dashboard Page
The system SHALL provide a dedicated `/positional` SPA page for multi-leg F&O positional book monitoring, replacing the existing stub route.

#### Scenario: User navigates to positional dashboard
- **WHEN** a user navigates to `/positional`
- **THEN** the page loads, subscribes to `/ws/portfolio`, and renders a strategy-grouped position table

#### Scenario: Dashboard shows empty state
- **WHEN** no open positions exist
- **THEN** the page displays an "No open positions" placeholder with a link to the instruments page

---

### Requirement: Strategy-Grouped Multi-Leg Book View
The system SHALL display all open positions grouped by `strategy_id`, with each group row showing aggregate net Δ, Γ, Θ, Vega, and combined P&L. Positions without a `strategy_id` SHALL be grouped under "Untagged".

#### Scenario: Multi-leg strategy row
- **WHEN** two positions share `strategy_id = "iron-condor-1"` (one CE leg, one PE leg)
- **THEN** a single strategy row shows `net_delta = sum(delta_i × qty_i)`, `net_theta = sum(theta_i × qty_i)`, and combined `unrealized_pnl`

#### Scenario: Expanding a strategy row
- **WHEN** the user clicks the expand arrow on a strategy row
- **THEN** individual leg rows appear inline, each showing: `symbol`, `expiry`, `qty`, `avg_price`, `ltp`, `per-leg_pnl`, and per-leg Greeks (Δ, Γ, Θ, V)

#### Scenario: Untagged group
- **WHEN** positions exist with a null `strategy_id`
- **THEN** they are grouped under a row labelled "Untagged" and displayed last in the table

---

### Requirement: Greek Enrichment from Options Snapshots
The system SHALL enrich each positional leg with the latest per-strike Greeks from the `options-analytics` REST endpoint. Greeks SHALL be considered stale when the snapshot age exceeds 60 seconds, and the UI SHALL flag stale rows.

#### Scenario: Greeks populated from snapshot
- **WHEN** a position exists for a CE strike and a valid options snapshot is available
- **THEN** the positional leg row shows `delta`, `gamma`, `theta`, `vega` sourced from that snapshot

#### Scenario: Greeks stale flag
- **WHEN** the last options snapshot for an underlying is older than 60 seconds
- **THEN** Greek cells for affected legs display a `stale` indicator and a `last_updated` tooltip showing the snapshot timestamp

#### Scenario: No snapshot available
- **WHEN** no options snapshot exists for a leg's underlying (paper mode or options poller not running)
- **THEN** Greek cells display `—` and no stale flag is shown

---

### Requirement: Expiry Alerts (T-7 / T-3 / T-1)
The system SHALL compute days-to-expiry (DTE) for each position leg and display expiry proximity alerts when DTE ≤ 7.

#### Scenario: T-7 warning alert
- **WHEN** a position leg has DTE = 7
- **THEN** an amber alert pill appears: "NIFTY 24500 CE expires in 7 days — consider rolling"

#### Scenario: T-3 urgent alert
- **WHEN** a position leg has DTE ≤ 3
- **THEN** an orange alert pill appears with "3 days to expiry" text

#### Scenario: T-1 critical alert
- **WHEN** a position leg has DTE ≤ 1
- **THEN** a red critical alert pill appears: "Expiring today/tomorrow — action required"

#### Scenario: No alert when DTE > 7
- **WHEN** all position legs have DTE > 7
- **THEN** no expiry alert banners are displayed

---

### Requirement: Rollover Cost Estimator
The system SHALL provide a per-leg rollover cost estimator panel that, when triggered, fetches current and next-expiry mid prices from the options-analytics REST endpoint and computes an indicative rollover cost.

#### Scenario: Rollover estimate displayed
- **WHEN** the user clicks "Estimate Rollover" on a leg with DTE ≤ 7
- **THEN** the panel calls `GET /api/v1/options/{underlying}/chain`, finds the matching strike in the next expiry, and displays: `current_mid`, `next_mid`, `rollover_cost = next_mid − current_mid`, and `slippage_estimate`

#### Scenario: No next expiry available
- **WHEN** only one expiry exists in the options chain for the underlying
- **THEN** the panel displays "No next expiry available for rollover"

#### Scenario: Slippage buffer configurable
- **WHEN** the user changes the slippage input (default 0.1%)
- **THEN** `slippage_estimate` recalculates immediately without re-fetching the chain

---

### Requirement: EOD P&L Snapshot Storage
The system SHALL expose `POST /api/v1/positional/snapshot` to persist a point-in-time P&L record for all open positions to the `positional_eod_snapshots` MongoDB collection. Each document SHALL contain: `date` (YYYY-MM-DD), `total_unrealized_pnl`, `total_realized_pnl`, `day_pnl`, `position_count`, and `created_at`.

#### Scenario: Snapshot created successfully
- **WHEN** `POST /api/v1/positional/snapshot` is called
- **THEN** HTTP 201 is returned and a document is upserted in `positional_eod_snapshots` keyed on `date`; calling again on the same day updates the existing document

#### Scenario: Snapshot in paper mode
- **WHEN** `LIVE=0` and `POST /api/v1/positional/snapshot` is called
- **THEN** HTTP 201 is returned with `"mode": "paper"` and the snapshot is stored normally

---

### Requirement: EOD P&L History Endpoint
The system SHALL expose `GET /api/v1/positional/snapshots?days=N` (default N=90) returning the last N daily snapshot documents sorted ascending by `date`, for use by the frontend sparkline chart.

#### Scenario: Snapshot history returned
- **WHEN** `GET /api/v1/positional/snapshots?days=30` is called and 15 snapshot documents exist
- **THEN** HTTP 200 is returned with a JSON array of 15 documents sorted by `date` ascending

#### Scenario: Empty history
- **WHEN** no snapshots exist
- **THEN** HTTP 200 is returned with an empty array `[]`

---

### Requirement: P&L Sparkline Chart
The system SHALL render a small line chart on the positional page showing the daily `day_pnl` for the last 90 days, fetched from `GET /api/v1/positional/snapshots`.

#### Scenario: Chart renders with history data
- **WHEN** snapshot history contains at least 2 data points
- **THEN** a sparkline chart displays with date on the X-axis and `day_pnl` on the Y-axis, with positive values in green and negative in red

#### Scenario: Chart shows placeholder with no data
- **WHEN** no snapshot history exists
- **THEN** the chart area displays "No history yet — snapshots will appear after market close"
