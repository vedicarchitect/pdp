## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Exit priority order

The strategy SHALL apply exit checks in this order within each bar, stopping at the first
exit that fires:

1. Square-off time reached (end-of-session)
2. Day-stop loss already hit (`done` flag)
3. **ST-touch intra-bar sweep** (NEW — highest-priority intra-bar exit)
4. **Trailing profit lock** (NEW — bar-close check)
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
