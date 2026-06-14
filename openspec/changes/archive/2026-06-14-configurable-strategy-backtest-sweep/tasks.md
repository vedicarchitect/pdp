## 1. Strategy configuration object

- [x] 1.1 Create `src/pdp/backtest/strategy_config.py` with a `StrategyConfig` dataclass holding all knobs (st_period, st_multiplier, timeframe_min, moneyness, strike_step, base_lots, add_lots, max_lots, lot_size, start_ist, squareoff_ist, leg_stop_per_lot, day_stop, roll_enabled, roll_trigger_prem, roll_target_min_prem, scale_in_gate, flip_mode) with documented defaults
- [x] 1.2 Add `StrategyConfig.from_dict(...)` and `to_dict()` (frontend seam) with round-trip equality
- [x] 1.3 Add validation (positive base_lots, lot ordering vs max_lots, timeframe_min in {3,5,15,30,60}) raising clear errors
- [x] 1.4 Add a `legacy()` / baseline factory matching the current backtest_multiday.py constants

## 2. Config-driven simulation engine

- [x] 2.1 Create `src/pdp/backtest/sim.py`; extract `simulate_day` from backtest_multiday.py (lines ~655–1055) parameterized by `StrategyConfig`, returning a `DayResult`
- [x] 2.2 Implement `select_strike(spot, opt_type, moneyness, step)` (signed: >0 OTM, 0 ATM, <0 ITM) replacing `otm_strike`
- [x] 2.3 Implement multi-leg `Position`/legs model (`{"CE","PE"}`, base + additional lots, flip-candle levels)
- [x] 2.4 First-flip base-lot entry (reuse the existing first_flip_seen gate; size at base_lots)
- [x] 2.5 Option-premium scale-in gate (add only when current option bar low < prior bar low, ≤ max_lots)
- [x] 2.6 Partial-flip + strangle: close additional legs, keep old base, open opposite base, record flip-candle high/low
- [x] 2.7 Strangle resolution by flip-candle extreme break (old base on NIFTY>flip-high, new base on NIFTY<flip-low); square-off flattens all
- [x] 2.8 Wire toggles: roll-up (roll_enabled/trigger/target), per-leg stop, day stop; exclude profit-lock and ST-touch from the engine

## 3. Thin caller refactor

- [~] 3.1 DEFERRED — `backtest_multiday.py` left untouched as the immutable −306,708 regression anchor; the sweep runs the new engine (`pdp.backtest.sim`) standalone via `scripts/backtest_sweep.py`. Rewiring is a follow-up once a config is promoted.
- [~] 3.2 N/A by design — the new engine intentionally drops profit-lock + ST-touch, so it cannot reproduce −306,708 bit-for-bit. Anchor preserved separately; the sweep reports the new-engine baseline (ST(3,1) 5m OTM1 = −291,641) for contrast instead.

## 4. Sweep / comparison harness

- [x] 4.1 Create `scripts/backtest_sweep.py`: load raw 1m spot + option chains once for the window
- [x] 4.2 Iterate the grid (ST {3,1/10,2/10,3} × TF {3,5,15,30,60}m × moneyness {ITM1-3/ATM/OTM1-3}), resampling per timeframe in memory; handle 60m IST-naive bucketing
- [x] 4.3 Aggregate per-combo metrics (net, gross profit/loss, profit factor, win rate, max drawdown, trades, days stopped)
- [x] 4.4 Print a ranked table (PF desc, net desc); add `--st/--tf/--moneyness/--days/--start` subset flags; no auto-pick
- [x] 4.5 Add single-config run path (`--config <json>`) printing full per-day/per-leg detail

## 5. Tests & verification

- [x] 5.1 Unit tests for `select_strike` (ITM/ATM/OTM signs, CE & PE)
- [x] 5.2 Unit tests for the option-premium scale-in gate
- [x] 5.3 Table-driven tests for the flip→strangle→flip-candle-break state machine
- [x] 5.4 Unit tests for sweep metric aggregation (profit factor, win rate, drawdown) and 60m resample alignment
- [x] 5.5 Run `scripts/backtest_sweep.py` end-to-end over the ~90-day window; capture the ranked table (83 traded days; surfaced + fixed a partial-close avg-entry accounting bug; ST(10,2) 15m family wins PF 2.3–3.3)
- [x] 5.6 `openspec validate --strict configurable-strategy-backtest-sweep`; then archive after the table is reviewed
