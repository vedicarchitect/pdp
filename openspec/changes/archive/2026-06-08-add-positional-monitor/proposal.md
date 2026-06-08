## Why

(STUB.) Swing / F&O positional traders need different ergonomics from intraday: expiry tracker, rollover cost calculator, Greek aggregation across a multi-leg book, and weekend P&L snapshots.

## What Changes

- `/positional` page: leg-grouped strategy view with combined Δ, Γ, Θ, V.
- Expiry alerts (T-7, T-3, T-1).
- Rollover-cost helper (current vs. next expiry mid + slippage estimate).
- Daily EOD snapshot table for P&L curve.

## Capabilities

### New Capabilities

- `positional-monitor`: Multi-leg book view, Greek aggregation, expiry/rollover tooling.

### Modified Capabilities

(none)

## Impact

Depends on `market-data`, `order-execution`, `options-analytics`.
