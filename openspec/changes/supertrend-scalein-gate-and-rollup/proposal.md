## Why

The reverse-bias premium-selling strategy (live/paper and the backtest's embedded copy) manages a
single short option leg per side. Two management gaps and one accounting risk were identified while
auditing the backtest:

1. **Scale-in is indiscriminate.** Today the strategy adds a lot on *every* signal bar while the
   trend holds, up to the max (`Scale-in while trend holds`). For a short seller, adding while the
   leg's premium is spiking to new highs averages into an adverse move that often recovers
   immediately. The add should wait until the adverse momentum stalls.

2. **No premium-decay roll.** When a short leg's premium decays to near-worthless, almost no profit
   remains in it but the capital stays committed and the leg still carries tail risk into a reversal.
   The strategy should harvest the decay by rolling into a richer same-side strike.

3. **Held quantity now varies, so closes must settle the live position.** Once scale-in is gated
   (some adds deferred) and roll-ups reset the leg to starting lots at a new strike, the open lot
   count is dynamic. Any close (flip, per-leg stop, daily-cap flatten, roll-up, square-off) must buy
   back exactly what is held - never an assumed or maximum lot count.

## What Changes

- **Gate scale-in on the leg's premium.** Add a lot only when the open leg's option premium did NOT
  make a new high on the current bar versus the immediately preceding bar (current high <= prior
  high). When the prior high is broken, defer the add and re-evaluate the gate on each subsequent
  bar, adding as soon as a bar fails to break the prior high (still under the max-lots cap). With no
  prior bar, allow the add.
- **Add premium-decay roll-up.** When the open leg's premium falls below a configured trigger
  (default 20) and the SuperTrend direction is unchanged, buy back the entire leg and re-sell the
  furthest-OTM same-side strike whose premium exceeds a configured floor (default 50), opening at
  the starting lot count. If no same-side strike within the warehouse band clears the floor, hold
  the existing leg (no roll). A flip against the leg takes precedence over a roll.
- **Make every close settle the exact held quantity.** Flip, stop, daily-cap, roll-up, and
  square-off closes buy back the position's current accumulated quantity at its actual average
  entry, reading live position state - not a fixed/max lot assumption.

## Capabilities

### Modified Capabilities
- `supertrend-strategy`: `Scale-in while trend holds` is sharpened with the premium-breakout gate;
  two requirements are added - `Premium-decay roll-up` and `Closes settle the exact held quantity`.

## Impact

- `backtest_multiday.py` - the scale-in branch gains the premium-breakout gate; a roll-up branch is
  added before scale-in (close current leg + open furthest-OTM >floor leg at starting lots); new
  configurable constants `ROLL_TRIGGER_PREM` (20) and `ROLL_TARGET_MIN_PREM` (50); a
  `prev_curr_bars` helper reads the leg's current and prior premium candle. Closes already settle
  `pos.total_qty`/`pos.avg_entry`; the new branches preserve that (gate never increments a counter
  without `pos.add`; roll closes the full leg then opens a fresh `Position`).
- Live/paper parity: these are strategy rules, so the spec is the single source; the live strategy
  adopts the same gate/roll/settlement behavior (tracked under the live-backtest parity initiative).
- Result interpretation: scale-in count drops on choppy bars; roll-ups add same-side turnover and
  shift realized P&L; the multiday summary changes and is re-recorded.
- Tests: gate defers an add on a premium breakout and resumes when it stalls; roll-up re-sells the
  furthest-OTM strike above the floor at starting lots; a close after gated adds / a roll settles
  exactly the held quantity (no phantom or max lots).
