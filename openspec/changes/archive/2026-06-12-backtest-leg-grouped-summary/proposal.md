## Why

The backtest currently prints one row **per order** (each SELL, each scale-in, each BUY). To
judge whether the strategy "takes the right trades and exits," a reader has to mentally fold the
scale-in rows back into the leg they belong to. A **leg-grouped summary** — one row per leg with
entry time, exit time, average entry, exit price, lot count, leg P&L, and close reason — is the
template the user asked to standardize in the script, and it makes per-trade review (and
backtest-vs-paper comparison) immediate.

## What Changes

- Add a **leg-grouped trade summary** table to the backtest's per-day output: one row per leg
  (an open through its matching cover), showing entry IST time, square-off/exit IST time, average
  entry price, exit price, lot count, realized leg P&L, and the close reason
  (`flip` / `leg_stop` / `day_stop` / `squareoff`).
- Keep the existing per-order detail table; the leg summary is an added view, not a replacement.
- The summary groups all scale-in orders into their parent leg via the running average entry.

## Capabilities

### Modified Capabilities

- `backtest`: trade-record output gains a leg-grouped summary view.

## Impact

- Touches `backtest_multiday.py` (`print_day` and the per-leg accumulation in `simulate_day` /
  `close_position`).
- Output-only change; no effect on simulation results.
