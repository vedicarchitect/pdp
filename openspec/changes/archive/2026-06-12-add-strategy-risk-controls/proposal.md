## Why

The `supertrend_short` live/paper strategy has **no risk controls**, but the
`backtest_multiday.py` simulation enforces two stops on every run:

- **Per-leg stop**: close the open leg when its mark-to-market loss reaches
  `1,000 × current_lots`.
- **Daily loss cap**: stop trading for the rest of the day once cumulative realized
  P&L reaches `-10,000`.

Because the live strategy implements neither, paper trades **diverge from the backtest**
on exactly the days that matter most — strongly-trending days where stops fire (all three
losing days in the 8-day study hit the day stop). A stable product must trade the same
rules it was validated on.

## What Changes

- Add a **per-leg stop-loss** to `supertrend_short`: on each closed signal bar, evaluate the
  open leg's unrealized MTM using its average entry and the option's latest price; if the loss
  reaches `leg_stop_per_lot × open_lots`, buy the leg back at market and do **not** re-enter on
  that bar (the next bar's signal decides re-entry).
- Add a **daily loss cap** to `supertrend_short`: track cumulative realized P&L for the day;
  once it reaches `-day_stop`, place no further entries and flatten any open leg.
- Expose both thresholds as YAML `params` (`leg_stop_per_lot`, `day_stop`) defaulting to the
  backtest values (1000, 10000) so the live strategy and the backtest share one rule set.
- The stop check runs **before** the flip / scale-in logic on each bar, matching the backtest
  evaluation order.

## Capabilities

### Modified Capabilities

- `supertrend-strategy`: gains per-leg stop-loss and daily-loss-cap requirements.

## Impact

- Depends on `supertrend-strategy`, `order-execution` (paper engine, `get_net_qty`), and a
  source of the option's latest price (Redis `ltp:<sid>` hot cache).
- Paper-first: stop-driven covers route through the same paper order path; no live behavior.
- Aligns paper results with `backtest_multiday.py` (`LEG_STOP_PER_LOT`, `DAY_STOP_LOSS`).
