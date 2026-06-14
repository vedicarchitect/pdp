## Context

The backtest bar loop processes a 5-minute signal series `(ist_dt, bar_open, bar_close, st)`.
`st.value` is the active SuperTrend line emitted at the END of the completed bar — the lower
band in an uptrend (+1), the upper band in a downtrend (-1). All current exits (leg-stop,
flip, roll-up, squareoff) fire at bar-close resolution.

Two new exits are added. Both are higher priority than the existing bar-close exits.

## Decision 1: ST-touch intra-bar exit

### Touch detection
For each 5-minute signal bar at `ist_dt`, scan the 1-minute NIFTY spot raw bars in the
window `[ist_dt, ist_dt + 5 min)` (exclusive end, IST-naive). Compare each 1-minute bar
against `prev_st.value` — the ST line emitted by the PRIOR completed 5-minute bar (tracked
in the loop as `prev_st` across iterations). `prev_st` is used because the current bar's
`st.value` is computed from the current bar's own close, which is not yet known intra-bar.

- Direction UP (`prev_st.direction > 0`, SELL PE): touch when `1m_bar_low <= prev_st.value`
- Direction DOWN (`prev_st.direction < 0`, SELL CE): touch when `1m_bar_high >= prev_st.value`

Stop at the FIRST 1-minute bar that breaches the level.

### Option exit price
A secondary `_chain_store_1m` (identical structure to `_chain_store` but preloaded with
`tf_min=1`) provides 1-minute option bars. On touch at 1-minute timestamp `touch_dt`:
- Call `price_at(_pos_bars_1m(pos), touch_dt, prefer="close")` for the exit price.
- If the 1-minute option bar is unavailable, fall back to the 5-minute bar's close price.

`_pos_bars_1m(pos)` is an inner helper mirroring `_pos_bars` but reading from
`_chain_store_1m`. It is only used for the intra-bar exit path.

### After touch exit
- `close_position(touch_dt, touch_nifty, touch_px, "st_touch")` settles the full leg.
- Set `st_touch_fired = True` (local flag, reset each bar).
- `continue` to the next 5-minute bar — no new entry, no scale-in, no roll-up on this bar.
- Next bar: normal decision logic; if ST flipped on the touch bar's close, open the
  reverse side as usual.

### Ordering in the bar loop
ST-touch sweep runs BEFORE all bar-close checks (before leg-stop, before flip). Rationale:
the touch happened during the bar, so the correct simulation order is to close on the
sub-bar event first, then — because the bar has ended — apply bar-close logic on the NEXT
bar. In practice, `continue` after the touch close skips all remaining checks for this bar.

### Data requirement: `_chain_store_1m`
In `main()`, after the existing chain preload, add a second preload with `tf_min=1`:
```
store_1m, _ = load_expiry_chain(mdb["option_bars"], exp, tds, tf_min=1)
_chain_store_1m.update(store_1m)
```
This doubles the in-memory chain footprint but avoids any MongoDB round-trips on the hot path.

### `prev_st` tracking
Initialize `prev_st = None` before the series loop. At the end of each bar's processing
(before `continue` or advancing), set `prev_st = st` if `st is not None`. On the first bar
where `prev_st is None`, skip the touch sweep (no prior ST line available).

## Decision 2: Trailing profit lock

### Mechanism
`Position` gains `peak_mtm: float = 0.0`. After computing `current_mtm = pos.mtm(bar_close_px)`
at bar close:
1. Update: `pos.peak_mtm = max(pos.peak_mtm, current_mtm)`.
2. If `pos.peak_mtm >= PROFIT_LOCK_TRIGGER (2_000)`:
   - lock_floor = `pos.peak_mtm * PROFIT_LOCK_TRAIL (0.5)`
   - If `current_mtm <= lock_floor`: close via `close_position(..., reason="profit_lock")`.

### Ordering relative to other exits
Profit-lock check runs AFTER the ST-touch sweep (intra-bar) and BEFORE leg-stop (bar-close).
Order within bar-close checks: profit_lock → leg_stop → flip. Rationale: protecting a
locked profit takes precedence over the fixed-loss leg-stop; the flip check follows because a
flip can reverse the position rather than simply closing it.

### `peak_mtm` resets
`peak_mtm` is an attribute of `Position`, so it resets to 0.0 automatically when a position
is closed and a new `Position` is constructed (new entry or roll-up). No explicit reset needed.

### Only on current MTM, not cumulative day P&L
The lock is per-leg unrealised gain (`pos.mtm(current_px)`), not the day's cumulative
`day_pnl`. The day-stop (₹10,000 cumulative realized loss) is a separate, orthogonal control.

## Decision 3: `_pos_bars_1m` helper

A thin inner function inside `simulate_day` mirroring `_pos_bars` but resolving from
`_chain_store_1m`. If the 1-minute chain is unavailable for the held contract, returns `[]`
(causing the touch exit to fall back to the 5-minute close price).

## Risks / trade-offs

- **Memory:** `_chain_store_1m` is 5× larger than `_chain_store` (5 bars per 5-minute bar).
  For a 76-day window with 2 expiries: ~76 × 21 × (ATM ± 10) × 375 ≈ 6M bars. RAM use
  increases substantially; monitor if the pre-load time becomes prohibitive.
- **Touch vs close delta:** Closing at 1-minute close instead of 5-minute close will sometimes
  be more adverse (1m close is mid-bar); sometimes more favourable. Net effect is empirical.
- **prev_st granularity:** Using the prior 5-minute bar's ST value as the touch line is an
  approximation. The current bar's ST is strictly not known until its close. This is the
  correct causal ordering for a live system.
- **Roll-up interaction:** If ST-touch fires on a bar, the roll-up check is skipped
  (`continue`). If ST fires AND the premium was below 20 on that same bar, the roll never
  happens — the touch exit takes priority. This is correct (the ST level was breached; rolling
  a leg whose trend just reversed makes no sense).

## Verification

- Unit: with `prev_st.direction > 0` and `prev_st.value = 100`, a 1m bar with LOW=99 triggers
  touch; LOW=101 does not. Symmetric for downtrend.
- Unit: peak_mtm trails — armed at 2000, floor rises with peak; fires when current drops to floor.
- Integration: re-run 76-day; record ST-touch count, profit-lock count, and delta PF vs the
  gate+rollup baseline (PF 0.55, net -187k).
