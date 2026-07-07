## MODIFIED Requirements

### Requirement: Leg entry metadata

Each open leg SHALL record `entry_time` (IST timezone-aware), `entry_reason` (a short string
capturing the bias bucket and score at entry, e.g. `NEUTRAL@0.10`), and `expiry` (the resolved
option expiry date) when the leg is opened, for short, hedge, and momentum legs. The `state()`
API SHALL include `entry_time`, `entry_reason`, and each strategy's `underlying` so the monitor
can display when and why each leg was opened and group per index. Closed-leg exit reasons remain
sourced from the existing `_activity` event buffer. The `expiry` recorded at open SHALL be
reused at close time — the close path SHALL NOT re-query the expiry.

#### Scenario: Entry metadata captured on open

- **WHEN** a short, hedge, or momentum leg is opened
- **THEN** the leg records `entry_time`, `entry_reason`, and `expiry`, and `state()` exposes
  `entry_time`, `entry_reason`, and the strategy `underlying`

#### Scenario: Expiry recorded at open is reused at close

- **WHEN** a leg is closed
- **THEN** the close event's `expiry` is the value recorded at open, without a fresh expiry
  lookup on the close/tick path

### Requirement: Leg lifecycle and exits

The simulator SHALL implement: rollup of a leg when its premium falls below 20 (buy back, re-sell a strike with premium at least `roll_target_min_prem`); take-profit closing a leg at `take_profit_pct` of collected credit; tiered premium stops (half-close at 30% above entry, full-close at 40% above entry) with a 15-minute stop-recovery cooldown gate before re-entry on the stopped side; trend-flip adjustment that rolls the tested side when the 15m or 1h 50-EMA is crossed against the position; a daily loss cap that flattens and halts trading for the day when day P&L reaches −15000 INR; and square-off of all legs at session end. Every terminal close event (`leg_close`, `take_profit`, `stop_all`, and the partial `stop_half`, including the closes driven by `square_off` / `day_loss_cap`) SHALL carry the full round-trip economics — `entry_price`, `exit_price`, `lots`, `entry_time`, `exit_time`, `pnl`, `opt_type`, `strike`, `is_hedge`, `expiry`, and a resolved human `symbol` — with the `pnl` sign matching the engine's unrealized convention (short: `(entry − exit) × lots × lot_size`; hedge/long: `(exit − entry) × lots × lot_size`).

#### Scenario: Rollup on premium decay
- **WHEN** an open leg's premium drops below 20
- **THEN** the leg is bought back and a new same-side strike with premium ≥ `roll_target_min_prem` is sold

#### Scenario: Terminal close carries full round-trip economics

- **WHEN** any terminal close event is emitted for a leg
- **THEN** it carries `entry_price`, `exit_price`, `lots`, `entry_time`, `exit_time`, `pnl`,
  `opt_type`, `strike`, `is_hedge`, `expiry`, and a resolved `symbol`

#### Scenario: A partial stop-half carries the closed-lot P&L

- **WHEN** a `stop_half` closes half of a leg's lots
- **THEN** its `pnl` is computed on the closed lots only and it is marked partial, leaving the
  remaining lots open for a later terminal close event
