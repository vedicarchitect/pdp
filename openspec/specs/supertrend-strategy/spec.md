# supertrend-strategy Specification

## Purpose
TBD - created by archiving change add-supertrend-options-strategy. Update Purpose after archive.
## Requirements
### Requirement: Signal-aligned option selling
The strategy SHALL, on each closed signal-timeframe bar, sell an out-of-the-money option of
the nearest weekly expiry aligned with the current SuperTrend direction: short PE when the
trend is up (green), short CE when the trend is down (red). On process restart during the
same trading day, the strategy SHALL recover any open leg from the positions table before
processing bars, so recovered state is treated identically to state built up from live fills.

#### Scenario: Open short PE on uptrend
- **WHEN** there is no open leg and SuperTrend direction is up
- **THEN** the strategy sells the configured OTM PE at the starting lot size

#### Scenario: Open short CE on downtrend
- **WHEN** there is no open leg and SuperTrend direction is down
- **THEN** the strategy sells the configured OTM CE at the starting lot size

#### Scenario: Restart recovers open leg before first bar
- **WHEN** the strategy starts and a non-zero short position tagged to it exists in the positions table for today
- **THEN** `_current` is populated from that position before `on_bar()` is called for the first time, and the strategy does not re-enter the same instrument

### Requirement: Settings-driven SuperTrend parameters

The universal `IndicatorEngine` SHALL read its SuperTrend period and multiplier from settings
(`SUPERTREND_PERIOD`, `SUPERTREND_MULTIPLIER`) rather than hardcoded constants, so the signal can be
retuned without code edits, defaulting to period 10 / multiplier 2.

#### Scenario: Engine uses configured SuperTrend parameters
- **WHEN** the application starts and constructs the `IndicatorEngine`
- **THEN** the engine's SuperTrend trackers use `SUPERTREND_PERIOD` and `SUPERTREND_MULTIPLIER` from settings
- **AND** with defaults unset the engine computes SuperTrend(10, 2)

### Requirement: Promoted default signal configuration

The `supertrend_short` paper strategy SHALL run on the 15-minute signal timeframe with OTM-1 strike
selection and per-leg / day stops of 3,000 / 20,000, this being the backtest-promoted configuration.

#### Scenario: Strategy subscribes and signals on 15m
- **WHEN** the strategy is loaded from `strategies/supertrend_short.yaml`
- **THEN** its watchlist and `params.timeframe` are `15m`
- **AND** `on_bar` only acts on closed 15-minute NIFTY bars

#### Scenario: Promoted risk limits applied
- **WHEN** the strategy evaluates its per-leg and day stops
- **THEN** the per-leg stop is 3,000 per current lot and the day stop is 20,000 of today's realized P&L

### Requirement: Flip closes and reverses
The strategy SHALL, when the SuperTrend direction flips against the open leg, buy back the
open leg and open the opposite-side leg at the starting lot size. The new-leg SELL SHALL only be
placed after the close order has left the strategy with zero net position: the strategy SHALL read
`net_qty` from the positions table after placing the BUY and SHALL skip the new-leg open on the
current bar if `net_qty` is still non-zero. A skipped open on flip is retried on the next bar's
signal provided the position has since flattened.

#### Scenario: Up-to-down flip
- **WHEN** a short PE leg is open and SuperTrend flips to down
- **THEN** the strategy buys back the PE and sells the OTM CE at the starting lot size

#### Scenario: Flip open skipped if close not yet confirmed
- **WHEN** the BUY (close) order has been placed but `net_qty` for the old security is still non-zero at the time `_open()` would be called
- **THEN** the new-leg SELL is NOT placed on this bar; `_current` remains None; the strategy logs `flip_open_deferred`

#### Scenario: Deferred open retried on next bar
- **WHEN** the flip open was deferred on bar N and by bar N+1 the position is flat (`net_qty == 0`)
- **THEN** the strategy opens the new leg at bar N+1's signal as if entering fresh

### Requirement: Scale-in while trend holds
The strategy SHALL add a configured number of lots on each subsequent signal bar while the
SuperTrend direction is unchanged, up to a configured maximum lot count. The effective open lot
count used for the max-lots cap SHALL be derived from the positions table (`abs(net_qty) // lot_size`)
at the start of each `on_bar()` evaluation, not solely from an in-memory counter, so that restarts
and partial fills do not cause the cap to be evaluated against a stale value. The strategy SHALL add
lots only when the open leg's option premium did NOT make a new high on the current bar relative to
the immediately preceding bar (current bar high <= prior bar high). When the current bar's premium
high exceeds the prior bar's high, the strategy SHALL defer the add and re-evaluate the same gate on
each subsequent bar, adding as soon as a bar fails to exceed the prior bar's high (still subject to
the maximum lot count). When no prior bar is available, the gate SHALL allow the add. A deferred add
SHALL NOT change the position's held quantity.

#### Scenario: Add a lot on continued trend
- **WHEN** a leg is open, the direction is unchanged on a new bar, open lots < max, and the leg's
  premium high on this bar does not exceed the prior bar's high
- **THEN** the strategy sells `add_lots` more of the same option

#### Scenario: Respect the max-lots cap
- **WHEN** open lots already equal the maximum
- **THEN** the strategy does not add more lots

#### Scenario: Respect the max-lots cap — position-table derived
- **WHEN** the positions table shows `net_qty` corresponding to `max_lots` already sold
- **THEN** the strategy does not add more lots, even if the in-memory counter was reset by a restart

#### Scenario: Lots sync on recovery after restart
- **WHEN** the server restarts mid-session, `_current` is recovered from the ledger, and the positions table shows 3 lots short
- **THEN** the effective lots count for the scale-in cap is 3 (from positions table), not whatever the recovered `_current["lots"]` states

#### Scenario: Premium breakout defers the add
- **WHEN** a leg is open, the direction is unchanged, open lots < max, but the leg's premium high on
  the current bar exceeds the prior bar's high
- **THEN** the strategy adds no lot on that bar, the held quantity is unchanged, and the gate is
  re-evaluated on the next bar

#### Scenario: Add resumes once the premium stops making new highs
- **WHEN** a previously deferred add is pending and a later bar's premium high does not exceed its
  prior bar's high
- **THEN** the strategy sells `add_lots` more of the same option on that bar (subject to the max)

### Requirement: Premium-decay roll-up
The strategy SHALL, when the open leg's option premium falls below a configured roll trigger
(`roll_trigger_prem`, defaulting to 20) and the SuperTrend direction is unchanged, buy back the
entire open leg and re-sell a richer same-side strike, opening at the starting lot count. The roll
target SHALL be the furthest-out-of-the-money same-side strike within the warehouse band whose
current premium exceeds a configured floor (`roll_target_min_prem`, defaulting to 50). If no same-side
strike within the band clears the floor, the strategy SHALL NOT roll and SHALL hold the existing leg.
A direction flip against the open leg SHALL take precedence over a roll, and the strategy SHALL NOT
add scale-in lots on the same bar as a roll.

#### Scenario: Premium decays below trigger rolls into a richer strike
- **WHEN** a short leg is open, the direction is unchanged, and the leg's premium is below
  `roll_trigger_prem`
- **THEN** the strategy buys back the full leg and sells the furthest-OTM same-side strike whose
  premium exceeds `roll_target_min_prem`, at the starting lot count

#### Scenario: No qualifying strike holds the leg
- **WHEN** a roll is triggered but no same-side strike within the band has a premium above
  `roll_target_min_prem`
- **THEN** the strategy does not roll and keeps the existing leg

#### Scenario: Flip takes precedence over a roll
- **WHEN** the leg's premium is below `roll_trigger_prem` but the SuperTrend direction has flipped
  against the leg on the same bar
- **THEN** the strategy reverses the leg (flip) rather than rolling

#### Scenario: Roll opens only starting lots that bar
- **WHEN** a roll-up occurs
- **THEN** the new leg opens at the starting lot count and no scale-in lot is added on the roll bar

### Requirement: Closes settle the exact held quantity
The strategy SHALL, on every close of an open leg - flip-driven reverse, per-leg stop, daily-cap
flatten, premium-decay roll-up, and end-of-session square-off - buy back exactly the quantity
currently held in the open position (its accumulated lots after any gated scale-ins and prior rolls)
and value the close at the leg's actual average entry. The strategy SHALL read live position state
for each close and SHALL NOT assume a fixed, starting, or maximum lot count.

#### Scenario: Square-off closes only the held lots
- **WHEN** the premium-breakout gate deferred adds so the open leg holds fewer than the maximum lots
  and the square-off time is reached
- **THEN** the strategy buys back exactly the lots currently held, not the maximum

#### Scenario: Close after a roll settles the rolled leg's quantity
- **WHEN** a roll-up has reset the leg to the starting lot count and a flip or square-off then closes it
- **THEN** the buy-back quantity equals the rolled leg's current lots, not the pre-roll quantity

#### Scenario: Deferred add creates no phantom quantity
- **WHEN** a scale-in add was deferred by the premium-breakout gate
- **THEN** the position's held quantity does not include the deferred lot in any later close

### Requirement: Trading window and square-off
The strategy SHALL place no new entries before the configured start time (IST) and SHALL flat
all legs at the configured square-off time (IST), trading no more that day. The start and
square-off times SHALL be compared against the **closed bar's timestamp** (converted to IST),
not against wall-clock time, so live and backtest scheduling are identical and the strategy can
be driven deterministically from historical bars.

#### Scenario: No entries before start
- **WHEN** the current bar's IST timestamp is before the start time
- **THEN** the strategy places no orders

#### Scenario: Square-off at end of window
- **WHEN** the current bar's IST timestamp is at or past the square-off time and a leg is open
- **THEN** the strategy buys back the open leg and stops trading for the day

### Requirement: Paper-only routing
The strategy SHALL route all orders through the platform order router, which is paper unless
live trading is explicitly enabled and a broker is configured.

#### Scenario: Orders route to paper by default
- **WHEN** the strategy places an order and live mode is not enabled
- **THEN** the order is filled by the paper engine

### Requirement: Per-leg stop-loss
The strategy SHALL, on each closed signal bar before evaluating flip or scale-in, compute the
open leg's unrealized mark-to-market loss from its average entry price and the option's latest
price, and SHALL buy back the entire leg at market when that loss reaches or exceeds a
configured per-lot amount multiplied by the current open lot count
(`leg_stop_per_lot × open_lots`). The per-lot amount SHALL be configurable via `params`,
defaulting to 1000. After a stop-driven close the strategy SHALL place no new entry on the same
bar; re-entry is decided by a subsequent bar's signal.

The mark price SHALL be the open option's latest Redis LTP. Because the strategy is driven by
the NIFTY index bar, the bar's `close` is the spot level and is NOT a valid mark for the option
premium; the strategy therefore SHALL NOT substitute `bar.close` for the option price. If the
Redis LTP is absent, non-positive, OR its recorded timestamp is older than a configurable
staleness threshold (default 30 seconds), the strategy SHALL skip the stop evaluation on that bar
(leaving the leg open for a later bar with a fresh quote) and SHALL log `leg_stop_ltp_stale_fallback`.

#### Scenario: Leg stop triggers a close
- **WHEN** a leg of `n` lots is open and its unrealized loss (marked on a fresh option LTP) reaches `leg_stop_per_lot × n`
- **THEN** the strategy buys back the full leg at market with a `leg_stop` reason and opens no
  new leg on that bar

#### Scenario: Loss below threshold holds the leg
- **WHEN** the open leg's unrealized loss is less than `leg_stop_per_lot × open_lots`
- **THEN** the strategy does not close the leg for stop reasons and proceeds to its normal
  flip / scale-in logic

#### Scenario: Stale or missing option LTP skips the stop
- **WHEN** the Redis LTP for the open option is missing, non-positive, or its timestamp is older than the staleness threshold
- **THEN** the strategy does not evaluate a stop on that bar, leaves the leg open, and logs `leg_stop_ltp_stale_fallback`

#### Scenario: Fresh option LTP marks the leg
- **WHEN** the Redis LTP for the open option is present and its timestamp is within the staleness threshold
- **THEN** the strategy marks the leg against that LTP and trips the stop only when the resulting loss reaches the limit

### Requirement: Daily loss cap
The strategy SHALL accumulate realized profit and loss over the trading day and, once cumulative
realized P&L reaches or falls below the negative of a configured cap (`-day_stop`), SHALL flatten
any open leg and place no further entries for the remainder of that session. The cap SHALL be
configurable via `params`, defaulting to 10000. The accumulator SHALL reset at the start of a new
trading day (IST).

#### Scenario: Day cap halts trading
- **WHEN** cumulative realized P&L for the day reaches `-day_stop`
- **THEN** the strategy flattens any open leg and opens no further legs until the next session

#### Scenario: Accumulator resets next day
- **WHEN** a new trading day (IST) begins
- **THEN** the cumulative realized P&L used for the cap resets to zero

### Requirement: SuperTrend-touch intra-bar exit

The strategy SHALL, when a 1-minute NIFTY spot sub-bar within the current signal bar breaches
the prior completed bar's SuperTrend line (low <= ST line in an uptrend; high >= ST line in a
downtrend), close the held option leg immediately at the 1-minute option bar's close price.
The strategy SHALL NOT open a new position or add lots on the same signal bar as the touch
exit. The next signal bar's normal decision logic (flip, new entry, scale-in) resumes
unaffected.

#### Scenario: Touch fires early in the bar
- **WHEN** a held PE leg is open (ST direction UP), the prior ST value is 23,400, and a
  1-minute sub-bar at 10:12 has LOW = 23,398
- **THEN** the leg is closed at the 1-minute option bar's 10:12 close price, reason
  "st_touch"; no new entry opens until the next 5-minute bar

#### Scenario: Sub-bar does not breach — no touch
- **WHEN** all 1-minute sub-bars within the 5-minute window have LOW above the prior ST value
  (for an uptrend position)
- **THEN** the touch sweep finds no breach and the normal bar-close exit checks run as usual

#### Scenario: Touch fires — next bar opens the reverse
- **WHEN** an ST touch closed the PE leg at 10:12 (5-minute bar 10:10–10:15), AND the
  5-minute bar's close confirms ST has flipped to DOWN
- **THEN** on the NEXT 5-minute bar (10:15) the strategy opens a CE leg per the flip logic

#### Scenario: No prior ST line — first bar
- **WHEN** the first bar of the session has no prior completed bar (prev_st is None)
- **THEN** the touch sweep is skipped for that bar

### Requirement: Trailing profit lock

The strategy SHALL track the peak unrealised MTM gain on each held leg. When the peak gain
reaches `profit_lock_trigger` (default ₹2,000), the strategy SHALL arm a trailing profit
floor at `profit_lock_trail` (default 50%) of the current peak. On each bar-close check
(after the intra-bar ST-touch sweep), if the current MTM has fallen to at or below the
trailing floor, the strategy SHALL close the leg immediately, reason "profit_lock".

The trailing floor rises as peak rises: a peak of ₹3,000 sets the floor at ₹1,500.
The trailing floor never decreases — if peak subsequently falls, the floor stays at the
highest computed value.

The lock operates on per-leg unrealised MTM (`(avg_entry - current_price) × held_qty`),
not on the cumulative day P&L. The daily loss cap is a separate, orthogonal control.

#### Scenario: Lock arms and fires
- **WHEN** a held CE leg's MTM rises to ₹2,400 (peak), then falls back to ₹1,200 (50%)
- **THEN** the strategy closes the leg at bar close, reason "profit_lock"; ₹1,200 is booked

#### Scenario: Peak rises, floor rises
- **WHEN** MTM reaches ₹2,000 (armed), then rises to ₹3,200 (new peak), then falls to ₹1,600
- **THEN** floor is ₹1,600 (50% of ₹3,200) and the leg closes at ₹1,600

#### Scenario: Lock does not fire below trigger
- **WHEN** MTM rises to ₹1,800 (below ₹2,000 trigger) then falls
- **THEN** no profit lock fires; normal leg-stop or squareoff handles the exit

#### Scenario: Lock floor never decreases
- **WHEN** MTM peaks at ₹3,000 (floor = ₹1,500), then drops to ₹2,000 (above floor), then
  rises to ₹2,800, then drops to ₹1,400
- **THEN** floor remains ₹1,500 (from the ₹3,000 peak) and the leg closes when MTM = ₹1,400

### Requirement: Exit priority order

The strategy SHALL apply exit checks in this order within each bar, stopping at the first
exit that fires:

1. Square-off time reached (end-of-session)
2. Day-stop loss already hit (`done` flag)
3. ST-touch intra-bar sweep (highest-priority intra-bar exit)
4. Trailing profit lock (bar-close check)
5. Per-leg stop-loss (bar-close check)
6. ST flip close + reverse (bar-close check)
7. Roll-up (bar-close check, direction unchanged only)
8. New entry / scale-in (bar-close check)

#### Scenario: ST-touch takes priority over leg-stop on the same bar
- **WHEN** a 1-minute sub-bar breaches the ST line AND the bar-close price would also trigger
  the per-leg stop-loss
- **THEN** the ST-touch exit fires first (intra-bar, at the 1-minute price); the leg-stop is
  not evaluated because the position is already closed before the bar-close checks run

#### Scenario: Profit lock takes priority over leg-stop on the same bar
- **WHEN** the bar-close MTM is below both the profit-lock floor AND the leg-stop threshold
- **THEN** the profit-lock fires first (it is checked before the leg-stop in the bar-close
  block); the leg-stop is not evaluated
