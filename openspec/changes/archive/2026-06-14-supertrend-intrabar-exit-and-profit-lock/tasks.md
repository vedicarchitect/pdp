## 1. Data layer — 1-minute option chain store

- [x] 1.1 Declare `_chain_store_1m: dict[tuple, dict] = {}` alongside `_chain_store` in the
      module-level cache block
- [x] 1.2 In `main()`, after the existing 5-minute chain preload loop, add a second loop
      calling `load_expiry_chain(mdb["option_bars"], exp, tds, tf_min=1)` for each expiry
      and update `_chain_store_1m`; log the count as `chain_preload_1m`
- [x] 1.3 Add inner helper `_pos_bars_1m(p: Position) -> list` inside `simulate_day`
      (mirrors `_pos_bars` but reads from `_chain_store_1m`; returns `[]` on cache miss
      rather than re-fetching)

## 2. Position class — peak_mtm tracking

- [x] 2.1 Add `peak_mtm: float = 0.0` to the `Position` dataclass/class; it initialises to
      zero and is updated externally in the bar loop (not inside `pos.add`)

## 3. New constants

- [x] 3.1 Add `PROFIT_LOCK_TRIGGER = 2_000.0` and `PROFIT_LOCK_TRAIL = 0.5` near the other
      strategy constants (LEG_STOP_PER_LOT block)

## 4. Bar loop — prev_st tracking

- [x] 4.1 Declare `prev_st = None` before the series loop in `simulate_day`
- [x] 4.2 At the END of each bar's processing (after all branches, before the next iteration),
      set `prev_st = st` when `st is not None` — must be after any `continue` that skips
      the rest of the bar, so use a `finally`-like pattern (set it unconditionally at the
      end of the loop body rather than before early `continue` exits)

  > Implementation note: the cleanest pattern is to move `prev_st = st` to the LAST line
  > of the for-loop body (after all exits). Python `for` loops do not have a `finally`
  > block; place the assignment just before the implicit loop advance by structuring the
  > loop so `prev_st = st` runs even when other branches fire `continue`. One approach:
  > wrap the existing loop body in a `try/finally`, or use a sentinel value updated at
  > the loop end. Prefer the simpler pattern: put `prev_st = st` as the very last
  > statement (it runs only when no `continue` fires mid-loop — that is acceptable
  > since `continue` bars still have a valid `prev_st` from the prior bar).
  >
  > Actually simplest: initialize `prev_st = None` and set it at the top of the loop
  > BEFORE any branches: `prev_bar_st = prev_st; prev_st = st`. Then use
  > `prev_bar_st` as the reference inside the loop. This guarantees every bar's
  > "prior ST" is the `st` emitted by the previous completed bar regardless of `continue`.

## 5. Bar loop — ST-touch intra-bar exit

- [x] 5.1 After the square-off block and `if done: continue`, and BEFORE the leg-stop check,
      add the ST-touch sweep:
      ```
      if pos and prev_bar_st is not None:
          spot_1m = [sub-bars in [ist_dt, ist_dt + TF_MIN minutes) from _spot_raw_by_day]
          for each sub-bar (with IST timestamp and high/low):
              if direction UP: breach = sub_low <= float(prev_bar_st.value)
              if direction DOWN: breach = sub_high >= float(prev_bar_st.value)
              if breach:
                  touch_px = price_at(_pos_bars_1m(pos), sub_ist, prefer="close")
                              or price_at(_pos_bars(pos), ist_dt, prefer="close")  # fallback
                  if touch_px:
                      close_position(sub_ist, sub_close_nifty, touch_px, "st_touch")
                  st_touch_fired = True
                  break
          if st_touch_fired:
              continue  # no entry, scale-in, or roll-up on this bar
      ```
- [x] 5.2 Declare `st_touch_fired = False` at the top of each bar iteration (reset per bar)
- [x] 5.3 `_spot_raw_by_day[trade_date]` stores raw Mongo docs; convert ts to IST-naive
      (`(ts + IST).replace(tzinfo=None)`) when scanning sub-bars; filter to the window
      `[ist_dt, ist_dt + timedelta(minutes=TF_MIN))` by IST timestamp
- [x] 5.4 The `desired` variable (direction for new entries) is computed after the first-flip
      gate; for the touch sweep, derive direction from `prev_bar_st.direction` directly
      (no dependency on `desired`)

## 6. Bar loop — trailing profit lock check

- [x] 6.1 Inside the bar-close leg-stop block (where `bar_close_px` is already computed),
      BEFORE the leg-stop MTM comparison, add:
      ```
      pos.peak_mtm = max(pos.peak_mtm, pos.mtm(bar_close_px))
      if pos.peak_mtm >= PROFIT_LOCK_TRIGGER:
          lock_floor = pos.peak_mtm * PROFIT_LOCK_TRAIL
          if pos.mtm(bar_close_px) <= lock_floor:
              close_position(ist_dt, bar_close, bar_close_px, "profit_lock")
              continue
      ```
- [x] 6.2 `pos.peak_mtm` is automatically reset to 0.0 when a new `Position` is constructed
      (roll-up, flip-entry, new entry); confirm no explicit reset is needed

## 7. Tests

- [x] 7.1 Unit: `prev_bar_st` pattern — given two consecutive bars, `prev_bar_st` at bar 2
      equals the `st` emitted by bar 1; `prev_bar_st` is None at bar 1
- [x] 7.2 Unit: touch detection — with `prev_bar_st.direction = +1` and `value = 100`,
      a 1m sub-bar with LOW = 99 triggers touch; LOW = 101 does not; symmetric for DOWN
- [x] 7.3 Unit: profit lock arms and fires — MTM sequence [500, 1800, 2400, 1800, 1200]:
      lock arms at 2400 (peak), floor = 1200; fires when MTM = 1200 (50% of 2400)
- [x] 7.4 Unit: trailing floor rises — peak 2000 (floor 1000) → MTM rises to 3200 (new
      floor 1600) → MTM drops to 1500 → fires at 1500 < 1600 floor
- [x] 7.5 Unit: no lock below trigger — MTM peaks at 1900, drops to 900; no profit_lock fires

## 8. Verification

- [x] 8.1 Re-run `uv run python backtest_multiday.py --days 76 --start 2026-06-12`; record
      ST-touch count, profit-lock count, and PF / win rate / net vs gate+rollup baseline
      (PF 0.55, net -187k)
- [x] 8.2 Re-dump a sample day with at least one ST-touch event; confirm the exit timestamp
      is a 1-minute bar time within the 5-minute window, not the window's close time
- [x] 8.3 Update memory with the new baseline PF and change behaviour
- [x] 8.4 `openspec validate --strict supertrend-intrabar-exit-and-profit-lock`
