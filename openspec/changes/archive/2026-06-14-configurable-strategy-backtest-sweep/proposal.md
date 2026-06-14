## Why

The SuperTrend(3,1) NIFTY option-selling strategy has regressed to **net −306,708 / profit
factor 0.38 / 34% win rate** over 83 traded days. Every knob lives as a hardcoded constant in
`backtest_multiday.py`, so we cannot compare alternatives without editing source. Before changing
the strategy by intuition, we need to make it fully configurable and sweep a grid of variants
(SuperTrend settings, signal timeframe, strike moneyness, entry/scale/flip rules) into one ranked
comparison table, then promote the winner. The strategy must also become dict-configurable so the
frontend can drive tuning later.

## What Changes

- Introduce a `StrategyConfig` dataclass capturing every strategy knob (SuperTrend period/multiplier,
  signal timeframe, signed strike moneyness ITM/ATM/OTM, base/add/max lots, session times, per-leg
  and day stops, roll-up toggle, scale-in-gate mode, flip mode), buildable from a plain dict.
- Refactor the monolithic `simulate_day` out of `backtest_multiday.py` into a reusable, testable
  `simulate_day(config, trade_date, data)` engine; `backtest_multiday.py` becomes a thin caller that
  builds a config from its constants and reproduces today's baseline.
- **New strategy semantics** (configurable):
  - Entry on the first SuperTrend flip of the day with the **base** lot.
  - Scale-in only when the **option premium** breaks the prior bar's extreme in our favour.
  - On a flip: close all **additional** legs, open the opposite **base** leg, and **keep** the old
    base leg as a strangle — resolved by **flip-candle extreme break** (old base closes when NIFTY
    breaks the flip candle's high; new base closes when NIFTY breaks the flip candle's low).
- **Generalized strike selection** by signed moneyness (ITM 1/2/3, ATM, OTM 1/2/3) for CE and PE.
- **Removed** from the configurable engine: trailing profit-lock and ST-touch intra-bar exit.
  **Retained as toggles**: roll-up on premium decay, per-leg MTM stop, daily loss cap.
- New **parameter-sweep harness** (`scripts/backtest_sweep.py`) that loads data once, runs the grid
  (ST 3,1 / 10,2 / 10,3 × timeframe 3/5/15/30/60m × moneyness ITM1-3/ATM/OTM1-3), aggregates
  metrics (net, gross profit/loss, profit factor, win rate, max drawdown, trades, days stopped), and
  prints a **ranked comparison table**. A single-config run path executes one chosen `StrategyConfig`.
- **Scope guard**: backtest only. No change to `src/pdp/strategies/supertrend_short.py` or any
  paper/live path; promotion to live is a separate, later change.

## Capabilities

### New Capabilities
- `strategy-config`: A serializable strategy configuration object (all SuperTrend option-selling
  knobs) buildable from a dict, consumed by the backtest engine and later by the frontend.

### Modified Capabilities
- `backtest`: The replay engine becomes parameterized by `StrategyConfig`; entry/scale-in/flip
  behaviour changes (first-flip base-lot entry, option-premium scale-in gate, partial-flip strangle
  resolved by flip-candle extreme break); strike selection generalizes to signed moneyness;
  profit-lock and ST-touch exits are removed while roll-up and stops become toggles.
- `backtest-compare`: Adds a parameter-sweep grid runner that produces a ranked multi-config
  comparison table (in addition to the existing backtest-vs-paper comparison).

## Impact

- **Code**: refactor `backtest_multiday.py`; new `src/pdp/backtest/strategy_config.py`,
  `src/pdp/backtest/sim.py`, `scripts/backtest_sweep.py`; new unit tests under `tests/`.
- **Reuse (unchanged)**: `SuperTrendTracker`, `resample.py`, `chain_loader.py`, `commissions.py`,
  `completeness.py`, expiry calendar + instrument-snapshot helpers.
- **Data**: relies on the now-complete NIFTY spot warehouse (Phase 0 backfill done).
- **No impact**: live/paper strategy, order routing, API/DB schemas.
