## MODIFIED Requirements

### Requirement: Leg lifecycle and exits

The simulator SHALL implement: rollup of a leg when its premium falls below 20 (buy back, re-sell a strike with premium at least `roll_target_min_prem`, preserving the rolled side's bucket assignment for TP eligibility); take-profit closing a leg when its LTP falls to `entry_price * take_profit_pct` (the identical condition the live strategy uses); tiered premium stops (half-close at 30% above entry, full-close at 40% above entry) with a 15-minute stop-recovery cooldown gate before re-entry on the stopped side; trend-flip adjustment that rolls the tested side when the 15m or 1h 50-EMA is crossed against the position; a daily loss cap that flattens and halts trading for the day when day P&L reaches −15000 INR; and square-off of all legs at session end, priced off each leg's close bar like every other exit path. Every terminal close event (`leg_close`, `take_profit`, `stop_all`, and the partial `stop_half`, including the closes driven by `square_off` / `day_loss_cap`) SHALL carry the full round-trip economics — `entry_price`, `exit_price`, `lots`, `entry_time`, `exit_time`, `pnl`, `opt_type`, `strike`, `is_hedge`, `expiry`, and a resolved human `symbol` — with the `pnl` sign matching the engine's unrealized convention (short: `(entry − exit) × lots × lot_size`; hedge/long: `(exit − entry) × lots × lot_size`).

#### Scenario: Rollup on premium decay
- **WHEN** an open leg's premium drops below 20
- **THEN** the leg is bought back and a new same-side strike with premium ≥ `roll_target_min_prem` is sold

#### Scenario: A rolled leg keeps its bucket-based TP eligibility
- **WHEN** a leg opened under `complete_bull`/`complete_bear` (an extreme bucket) rolls to a new
  strike under `take_profit_extreme_only: true`
- **THEN** the new leg is still eligible for take-profit for the rest of the day, because the
  rolled side's original bucket carries over into `leg_buckets` rather than being dropped

#### Scenario: Take-profit fires at the same LTP threshold in backtest and live
- **WHEN** a leg's LTP falls to `entry_price * take_profit_pct`
- **THEN** the backtest simulator closes it with reason `take_profit`, using the identical
  condition the live strategy evaluates — for any configured `take_profit_pct`, not only 0.5

#### Scenario: Square-off prices off the close, like every other exit
- **WHEN** the session-end square-off closes all open legs
- **THEN** each leg's exit price is read from its close bar, the same source every other exit path
  (`take_profit`, `pct_stop_half`, `pct_stop_all`, `roll`) uses — not the bar's open

#### Scenario: Terminal close carries full round-trip economics

- **WHEN** any terminal close event is emitted for a leg
- **THEN** it carries `entry_price`, `exit_price`, `lots`, `entry_time`, `exit_time`, `pnl`,
  `opt_type`, `strike`, `is_hedge`, `expiry`, and a resolved `symbol`

#### Scenario: A partial stop-half carries the closed-lot P&L

- **WHEN** a `stop_half` closes half of a leg's lots
- **THEN** its `pnl` is computed on the closed lots only and it is marked partial, leaving the
  remaining lots open for a later terminal close event
