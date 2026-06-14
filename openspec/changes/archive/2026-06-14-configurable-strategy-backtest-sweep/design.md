## Context

`backtest_multiday.py` is a 1,249-line script whose `simulate_day` holds all strategy logic with
every parameter as a module-level constant (ST `period=3,multiplier=1`; `TF_MIN=5`; `OTM_STEPS=1`;
lots; stops; roll; profit-lock; ST-touch). The current configuration produces net −306,708 / PF 0.38
over 83 days. We cannot compare alternatives without editing source, and the flip/scale-in behaviour
does not match the desired rules. The data layer is already complete (Phase-0 spot backfill done) and
the supporting pieces — `SuperTrendTracker`, `resample.py`, `chain_loader.py`, `commissions.py`,
`completeness.py`, expiry calendar, instrument snapshots — are reusable as-is.

## Goals / Non-Goals

**Goals:**
- A single `StrategyConfig` object that captures every knob and is built from a plain dict.
- An importable, unit-testable `simulate_day(config, trade_date, data)` engine extracted from the
  current script, with the new entry/scale-in/flip semantics gated by config.
- A sweep harness that loads data once and runs the full grid into a ranked comparison table.
- The legacy config path reproduces the −306,708 baseline exactly (behaviour-preserving refactor).

**Non-Goals:**
- No changes to `src/pdp/strategies/supertrend_short.py` or any paper/live/order-routing path.
- No frontend work now (the dict-config seam is the only forward provision).
- No new DB tables; the sweep writes nothing, it prints.
- Profit-lock and ST-touch intra-bar exit are not carried into the new engine.

## Decisions

**1. Two new modules, thin caller.** `src/pdp/backtest/strategy_config.py` (`StrategyConfig` +
`from_dict`) and `src/pdp/backtest/sim.py` (`simulate_day`, `select_strike`, `DayResult`,
multi-leg `Position` model). `backtest_multiday.py` keeps all data-loading/preload/printing and
calls `simulate_day` — so the existing CLI and outputs are preserved.
*Alternative considered:* edit `simulate_day` in place. Rejected — it is untestable in isolation and
the sweep needs to call the engine many times with different configs.

**2. Signed moneyness.** Replace `otm_strike` with `select_strike(spot, opt_type, moneyness, step)`:
`atm = round(spot/step)*step`; CE strike `= atm + moneyness*step`, PE strike `= atm - moneyness*step`
(`moneyness>0` = OTM, `=0` = ATM, `<0` = ITM). Feeds the existing nearest-strike fallback unchanged.

**3. Multi-leg position model.** The current single `Position` cannot express a strangle. Model each
side as its own `Position` (base lots + additional lots, avg entry, peak), held in
`legs: dict[str, Position]` keyed by `"CE"/"PE"`, plus `flip_levels` (the flip candle high/low) that
arm the strangle-resolution check. At most one side scales in (the trend-aligned side); the opposite
side, if present, is a base-only strangle remnant awaiting flip-candle break.

**4. Scale-in gate = option-premium prior-candle break.** Add `add_lots` to the active leg only when
the current option bar's low < prior option bar's low (premium continuing to decay in our favour),
capped at `max_lots`. Replaces the premium-new-high gate. Uses `prev_curr_bars` on the option series.

**5. Flip → partial close + strangle, resolved by flip-candle extreme break.** On a direction flip:
close all additional legs of the old side (keep its base), open the opposite base leg, and record the
flip candle's high/low. On each later bar, if NIFTY > flip-high close the old-side base; if NIFTY <
flip-low close the new-side base. Square-off always flattens both. A flip while already in a strangle
re-anchors to the newly-aligned side.

**6. Toggles vs removals.** Keep `roll_enabled`, `leg_stop_per_lot`, `day_stop` as config. Remove the
profit-lock and ST-touch code paths from the new engine (they stay only in git history / the old
script if ever needed for parity, but are not part of `simulate_day`).

**7. Sweep loads data once.** `scripts/backtest_sweep.py` preloads raw 1m spot + option chains for the
window a single time, then for each `(st, tf, moneyness)` combo resamples in memory and runs the day
loop. Metrics aggregated per combo: net, gross profit, gross loss, profit factor, win rate, max
drawdown, trades, days stopped. Output: a ranked table (default sort PF desc, net desc); the user
picks. A `--config <json>`/single-combo mode runs one config with full per-day/per-leg detail.

## Risks / Trade-offs

- [Hourly (60m) bars misalign under the IST 05:30 offset] → resample hourly on IST-naive timestamps so
  buckets anchor to 09:15, not UTC hour boundaries; cover with a resample unit test.
- [Refactor silently changes baseline P&L] → keep a `legacy` config path and assert the −306,708
  window total is reproduced before enabling new rules; treat any drift as a bug.
- [Sweep runtime: ~105 combos × ~83 days] → load-once design keeps Mongo round-trips at zero on the
  hot loop (mirrors current sub-minute single run); subset flags (`--st/--tf/--moneyness`) bound cost.
- [Multi-leg model regressions vs single-leg] → table-driven state-machine tests for
  entry→scale→flip→strangle→break before running the grid.

## Open Questions

- None blocking. Promotion metric is intentionally "show table, user decides"; a future change can
  add an auto-pick once a preferred objective is settled.
