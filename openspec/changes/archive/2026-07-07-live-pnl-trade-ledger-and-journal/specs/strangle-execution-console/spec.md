## MODIFIED Requirements

### Requirement: Execution console API — stats

`GET /api/v1/strangle/stats` SHALL return day realized P&L, unrealized P&L, total P&L, trade
count, and open leg count by side, so a client can display a day summary. The console's live
P&L SHALL be sourced **only** from the engine `state()` (`day_realized`, `day_unrealized`,
`day_pnl`) and NEVER from the journal's `compute_daily_stats`. P&L SHALL be presented **per
index** (NIFTY / BANKNIFTY / SENSEX rows) rather than as a single blended figure, with each row
carrying its `underlying`, `done_for_day`, and `squared_off_at`, plus a `totals` object summing
across indices. When an index's strategy is `done_for_day`, the console SHALL show a
"Squared off HH:MM — final ₹X" state for that index rather than a stale ticking mark-to-market.

#### Scenario: Stats returned for active day

- **WHEN** the strategy has been running intraday
- **THEN** response includes `day_realized`, `day_unrealized`, `day_pnl`, `trade_count`, and
  open leg counts by side

#### Scenario: P&L is broken out per index

- **WHEN** the console P&L is requested with NIFTY, BANKNIFTY, and SENSEX strategies running
- **THEN** the response carries a per-index P&L breakdown (one row per underlying) plus a
  `totals` object, never a single blended number

#### Scenario: Squared-off index shows a final state

- **WHEN** an index's strategy has squared off for the day
- **THEN** the console shows "Squared off HH:MM — final ₹X" for that index using its
  `squared_off_at` and final `day_pnl`, not a live-updating MTM

### Requirement: Execution console API — activity

`GET /api/v1/strangle/activity` SHALL return recent strategy activity. In addition, the console
SHALL expose today's entry→exit trades via the `live-trade-ledger` trades API
(`GET /api/v1/strangle/trades`), grouped by index, so the console can render a "Today's Trades"
table alongside the open-legs view with per-trade entry, exit, lots, and P&L. Closed trades
SHALL remain visible after their legs close (they are not dropped when `state().legs` no longer
lists them), so a square-off reads as an explained sequence of closes rather than a glitch.

#### Scenario: Today's closed trades remain visible

- **WHEN** legs are closed at square-off and no longer appear in `state().legs`
- **THEN** the console still shows those closed trades in the Today's Trades table with their
  entry→exit prices and per-trade P&L

#### Scenario: Trades are grouped per index

- **WHEN** the Today's Trades table is rendered for a multi-index day
- **THEN** rows are grouped under NIFTY / BANKNIFTY / SENSEX section headers, not blended
