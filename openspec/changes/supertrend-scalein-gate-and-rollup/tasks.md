## 1. Scale-in premium-breakout gate

- [x] 1.1 Add `prev_curr_bars(bars, target)` helper returning `(prior_bar, current_bar)` - nearest bar to `target` within the existing tolerance plus its immediate time predecessor; `(None, current)` when no predecessor, `(None, None)` when none within tolerance
- [x] 1.2 In the scale-in branch (`backtest_multiday.py` ~`:869`), before `pos.add(...)`, read the held leg's `(prior, current)` premium candles; add only when `prior is None` or `current.high <= prior.high`; when `current.high > prior.high`, skip the add this bar (no counter touched) so the gate re-evaluates next bar
- [x] 1.3 Keep the add gated on the existing same-contract + `pos.lots < MAX_LOTS` conditions; the gate only defers, never raises the cap

## 2. Premium-decay roll-up

- [x] 2.1 Add configurable constants `ROLL_TRIGGER_PREM = 20.0` and `ROLL_TARGET_MIN_PREM = 50.0` near the sizing constants
- [x] 2.2 Add a roll-target resolver: for the desired side, scan same-side strikes in the warehouse band from furthest-OTM inward toward ATM and return the furthest-OTM strike whose current premium (priced at the bar) > `ROLL_TARGET_MIN_PREM`, or `None` if none clear it
- [x] 2.3 In the bar loop, after the flip handling and before scale-in, when `pos` exists, direction is unchanged, and the held leg's current premium < `ROLL_TRIGGER_PREM`: resolve the roll target; if found, `close_position(..., reason="roll")` the full leg then open a fresh `Position` at `START_LOTS` on the target strike, and `continue` (no same-bar scale-in); if not found, hold (no roll)
- [x] 2.4 Ensure roll-up does not fire on a flip bar (flip reverses first) nor on the square-off bar

## 3. Closes settle the exact held quantity

- [x] 3.1 Confirm flip, per-leg stop, daily-cap, roll, and square-off (intraday `:799` and end-of-loop `:888`) all close via `close_position`, which settles `pos.total_qty` at `pos.avg_entry`; remove any path that could close an assumed/partial quantity
- [x] 3.2 Confirm the gate never mutates held quantity except through `pos.add(...)`, and the roll always closes the full leg before constructing the new `Position`

## 4. Tests

- [x] 4.1 Unit: a premium-breakout bar (`current.high > prior.high`) defers the scale-in add; the next non-breakout bar performs it (held lots increment by exactly one add)
- [x] 4.2 Unit: roll-up at premium < 20 re-sells the furthest-OTM same-side strike with premium > 50 at `START_LOTS`; with no strike > 50 it does not roll
- [x] 4.3 Unit: after gated adds (held 3L, not max) a square-off/flip buys back exactly 3L; after a roll the close settles the rolled leg's current lots, not the pre-roll count (no phantom/max lots)

## 5. Verification

- [x] 5.1 Re-run `uv run python backtest_multiday.py --days 76 --start <same end>`; record scale-in count, roll count, and PF / win rate / net vs the look-ahead-corrected baseline
- [x] 5.2 Re-dump a sample day's leg summary; confirm each close's BUY qty equals the leg's held lots and roll legs appear with `roll` reason
- [x] 5.3 Update memory to capture the gated-scale-in + roll-up behavior and the corrected run
- [x] 5.4 `openspec validate --strict supertrend-scalein-gate-and-rollup`
