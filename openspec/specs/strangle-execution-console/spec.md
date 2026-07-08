# strangle-execution-console Specification

## Purpose
Live observability and execution console for the directional strangle strategy: per-signal vote logging, leg status heartbeat, rollup on premium decay, stop-gate cooldown, weekly Camarilla input, live PCR input, indicator timeframe audit, canonical log schema, and REST status/legs/activity/stats endpoints.
## Requirements
### Requirement: Parity — per-signal vote logging
On every 5m bar, `DirectionalStrangle` SHALL emit a `bias_evaluated` structlog event that
includes the full `BiasResult.votes` dict alongside the existing `score`, `bucket`, `gated`,
and `reason` fields, so live decisions can be compared line-by-line with backtest replay.

#### Scenario: Vote breakdown present on every evaluation
- **WHEN** a 5m bar closes and the strategy evaluates bias
- **THEN** the `bias_evaluated` log event includes a `votes` field with a dict keyed by
  signal name (e.g. `ema_1h`, `ema_15m`, `cam_daily`, `vwap`, `pcr`) mapping to integer
  votes (`+1`, `0`, or `-1`)

#### Scenario: Missing signal is absent from votes dict
- **WHEN** a required input (e.g. `cam_weekly`) is `None` at evaluation time
- **THEN** the corresponding key is absent from the `votes` dict (not `null` or `0`)

---

### Requirement: Parity — leg status heartbeat
After each `bias_evaluated` event, `DirectionalStrangle` SHALL emit a `leg_status` structlog
event listing all open legs (short and hedge) with last-known LTP and mark-to-market value,
so a reader can reconstruct open exposure at any point in the trading day.

#### Scenario: Leg status emitted every 5m bar
- **WHEN** a 5m bar closes and there are open legs
- **THEN** a `leg_status` event is emitted with a `legs` list; each entry includes
  `security_id`, `opt_type`, `strike`, `lots`, `entry_price`, `ltp` (nullable), `mtm` (nullable)

#### Scenario: Empty leg status when flat
- **WHEN** a 5m bar closes and there are no open legs
- **THEN** a `leg_status` event is still emitted with `legs: []`

---

### Requirement: Parity — rollup on premium decay
`DirectionalStrangle` SHALL close and reopen a short leg when its LTP falls below
`roll_trigger_prem` (default 20), re-entering at the next OTM strike with premium ≥
`roll_target_min_prem` (default 50). The matching protective hedge SHALL be similarly
replaced at the new strike.

#### Scenario: Rollup fires when premium decays
- **WHEN** a short leg's LTP drops below `roll_trigger_prem`
- **THEN** the leg is closed, a new short is opened at the next available strike with
  premium ≥ `roll_target_min_prem`, and a `rolled` event is emitted with `old_strike`,
  `new_strike`, `old_ltp`, `new_ltp`

#### Scenario: No rollup when premium is above threshold
- **WHEN** all short leg LTPs are above `roll_trigger_prem`
- **THEN** no rollup occurs and no `rolled` event is emitted

---

### Requirement: Parity — stop-gate re-entry cooldown
After `stop_half` or `stop_all` fires on a side (`PE` or `CE`), `DirectionalStrangle` SHALL
block re-entry on that side until the stopped instrument's LTP stays below the stop-exit
price for 3 consecutive 5m bars (≈15 minutes).

#### Scenario: Stop-gate blocks immediate re-entry
- **WHEN** a stop fires and the next 5m bar would otherwise trigger re-entry on the same side
- **THEN** the new short leg is NOT opened, and a `stop_gate_wait` event is emitted with
  `opt_type`, `n_below`, and `exit_px`

#### Scenario: Stop-gate clears after 3 bars below exit price
- **WHEN** the stopped instrument's LTP has been below `exit_px` for 3 consecutive 5m bars
- **THEN** the gate is cleared and re-entry is permitted on the next bar

#### Scenario: Stop-gate resets if LTP rises above exit price
- **WHEN** the stopped instrument's LTP rises above `exit_px` before the gate clears
- **THEN** the bar counter `n_below` resets to 0 and the 3-bar window restarts

---

### Requirement: Parity — weekly Camarilla input
`DirectionalStrangle` SHALL populate `cam_weekly` in `BiasInputs` from the indicator
engine's weekly pivot state, so the weekly Camarilla vote is included in the bias score.

#### Scenario: Weekly Cam included when indicator is warmed
- **WHEN** `ind.pivots(sid, "1w")` returns a non-None pivot state
- **THEN** `cam_weekly` in `BiasInputs` is a `CamLevels` object with `r3`, `r4`, `s3`, `s4`

#### Scenario: Weekly Cam treated as missing when not warmed
- **WHEN** `ind.pivots(sid, "1w")` returns `None`
- **THEN** `cam_weekly=None` is passed to `BiasInputs` (vote excluded from score),
  and a `cam_weekly_missing` debug event is emitted once per session

---

### Requirement: Parity — live PCR input
`DirectionalStrangle` SHALL populate `pcr` in `BiasInputs` from a live source (indicator
engine or options chain poller) so the PCR vote contributes to real-time bias scoring.

#### Scenario: PCR vote applied when data is available
- **WHEN** a PCR value is available from the indicator engine or chain poller
- **THEN** `pcr` in `BiasInputs` is a float and the PCR vote contributes to the score

#### Scenario: PCR vote skipped when data unavailable
- **WHEN** no PCR source is available or the value is `None`
- **THEN** `pcr=None` is passed to `BiasInputs` and the PCR vote is excluded

---

### Requirement: Parity — indicator timeframe key audit
On `on_init`, `DirectionalStrangle` SHALL assert that the indicator engine resolves the
expected timeframes (`5m`, `15m`, `1h`) without error, and log a startup check so a
failed warmup is visible immediately.

#### Scenario: Warm startup logged
- **WHEN** `on_init` completes and all expected indicator timeframes resolve
- **THEN** a `strategy_warmup_check` info event is emitted listing `warmed_timeframes`

#### Scenario: Missing timeframe surfaced at init
- **WHEN** an expected timeframe (e.g. `1h`) is not warmed at startup
- **THEN** a `strategy_warmup_warning` warning event is emitted naming the missing timeframe

---

### Requirement: Canonical per-action log schema
Every significant action in `DirectionalStrangle` SHALL emit a structlog event via
`emit_strangle_event(ctx, event_type, **fields)`. Every event SHALL include: `event_type`
(from `StrangleEventType`), `strategy_id`, `snapshot_date` (IST), `ist_time`,
`underlying`, `score`, `bucket`. The event SHALL also be written to the strategy's daily
log file (`logs/<strategy_id>/<date>.log`) via `StrategyDailyLog.write()`.

Covered event types: `leg_open`, `leg_close`, `take_profit`, `stop_half`, `stop_all`,
`day_loss_cap`, `rolled`, `stop_gate_wait`, `bucket_change`, `bias_evaluated`, `leg_status`,
`square_off`.

#### Scenario: Leg open event emitted on entry
- **WHEN** a short or hedge leg is opened
- **THEN** a `leg_open` event is emitted with `sid`, `opt_type`, `strike`, `lots`,
  `entry_price`, `is_hedge`, `mode` (`paper` or `live`)

#### Scenario: Take-profit event emitted on TP close
- **WHEN** a short leg is closed via take-profit
- **THEN** a `take_profit` event is emitted with `sid`, `ltp`, `entry_price`, `pnl`

#### Scenario: Rolled event includes old and new leg details
- **WHEN** a rollup occurs
- **THEN** a `rolled` event is emitted with `opt_type`, `old_strike`, `old_ltp`,
  `new_strike`, `new_ltp`, `lots`

#### Scenario: Events written to daily log file
- **WHEN** any canonical event is emitted during the trading session
- **THEN** the event dict is appended to `logs/<strategy_id>/<YYYY-MM-DD>.log` (IST date)

---

### Requirement: Execution console API — status
`GET /api/v1/strangle/status` SHALL return the current execution mode, bucket, bias score,
day state, and session metadata so a client can show a live strategy summary.

#### Scenario: Status returned when strategy is running
- **WHEN** the strategy is active and has received at least one 5m bar
- **THEN** response includes `mode`, `strategy_id`, `bucket`, `score`, `done_for_day`,
  `vix_now` (nullable), `started_at`, `n_open_legs`, `day_pnl`

#### Scenario: Status returns 404 when strategy not loaded
- **WHEN** no `DirectionalStrangle` instance is loaded
- **THEN** `GET /api/v1/strangle/status` returns HTTP 404

---

### Requirement: Execution console API — legs
`GET /api/v1/strangle/legs` SHALL return all currently open legs with entry price, last
known LTP, mark-to-market, side, and strike, so a client can display a live position table.

#### Scenario: Legs returned with LTP when ticks have been received
- **WHEN** open legs exist and ticks have been seen for those sids
- **THEN** each leg in the response includes `entry_price`, `ltp`, `mtm`, `opt_type`,
  `strike`, `lots`, `is_hedge`, `is_momentum`

#### Scenario: LTP is null when no tick yet received for a leg
- **WHEN** a leg was just opened and no tick has arrived yet
- **THEN** `ltp` and `mtm` are `null` in the response

---

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

