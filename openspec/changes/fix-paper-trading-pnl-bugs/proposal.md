## Why

The paper engine produces incorrect P&L in three distinct ways: (1) the position weighted-average is mathematically wrong for short positions, inflating losses by up to 6× in today's session; (2) a race between order placement and bar events creates orphan BUY orders that close positions that were never opened; (3) the Perl monitor blotter shows CANCELLED orders as phantom bad-fill rows. These bugs make the trade journal untrustworthy for evaluating strategy performance.

## What Changes

- **Fix `upsert_position` short-side weighted average** — `total_cost` formula uses signed `old_qty` (negative for shorts), inverting the average; replace with `abs(old_qty)`.
- **Guard `_current` assignment against unfilled SELL** — `_open()` must not set `_current` when the placed SELL order is in a terminal state (CANCELLED / REJECTED); squareoff will otherwise BUY against a phantom short, creating an orphan long position.
- **Cancel stale SELL before squareoff BUY** — `_close_current()` should cancel any OPEN entry SELL for `_current["security_id"]` before placing the closing BUY, so no unfilled entry survives past the close event.
- **Filter Perl monitor to FILLED orders only** — add `status eq 'FILLED'` to the SELL/BUY grep predicates in `monitor.pl`.

## Capabilities

### New Capabilities
- `paper-pnl-correctness`: Correct P&L semantics for multi-leg short positions in the paper engine — weighted average, realized P&L on close, and squareoff safety.

### Modified Capabilities
- `order-execution`: Squareoff / flip close path must cancel any open entry orders before placing the covering BUY.
- `portfolio`: Position `avg_price` and `realized_pnl` are now computed correctly for short positions.

## Impact

- `src/pdp/orders/paper.py` — `upsert_position` one-line fix (`abs(old_qty)`)
- `src/pdp/strategies/supertrend_short.py` — `_open()` terminal-state guard; `_close_current()` stale-SELL cancel
- `monitor.pl` — add `status` filter to SELL/BUY grep predicates
- Existing `positions` rows for today are stale; `reset_paper.py` should be run after the fix to start a clean session
