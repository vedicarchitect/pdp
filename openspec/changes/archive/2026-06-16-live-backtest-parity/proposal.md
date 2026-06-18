## Why

On 2026-06-12, the backtest simulation produced +₹25,058 while live paper trading produced -₹1,176 — a ₹26,234 delta on the same strategy, same day, same parameters. Five concrete bugs in the live strategy host cause this divergence and must be closed before the strategy can be trusted in live trading.

## What Changes

- **IndicatorEngine warmup on startup**: Seed the SuperTrend tracker from MongoDB before the first live bar arrives, so the live indicator state matches what a fully-seeded backtest sees.
- **Atomic flip**: Confirm the close fill (check net_qty from positions table) before placing the new-leg SELL on a direction flip, preventing overlapping short positions.
- **Lots sync from positions table**: Derive `_current["lots"]` from `net_qty // lot_size` at bar start instead of relying solely on the in-memory counter, so restarts and partial fills don't desync the scale-in cap.
- **Paper broker subscription race fix**: Ensure the paper broker's Redis `tick.{sid}` subscription is active before the MARKET order is placed, so the first tick fills the order rather than being missed.
- **LTP staleness fallback for leg-stop**: When Redis LTP is absent or older than a configurable threshold, fall back to the just-closed bar's `close` price for the leg-stop check, matching backtest semantics.

## Capabilities

### New Capabilities

- `indicator-warmup`: IndicatorEngine seeding from MongoDB historical bars on strategy host startup.

### Modified Capabilities

- `supertrend-strategy`: Requirements change for flip atomicity, lots-sync, and leg-stop LTP fallback (all directly affect observable trade behaviour).
- `strategy-host`: Startup sequence must include indicator warmup before subscribing to live feed.

## Impact

- `src/pdp/strategies/supertrend_short.py` — flip logic, lots-sync, leg-stop check
- `src/pdp/indicators/engine.py` — new `seed_from_bars()` or equivalent warmup method
- `src/pdp/strategy/host.py` (or equivalent startup entrypoint) — warmup call before live bar dispatch
- `src/pdp/orders/paper.py` — subscription timing relative to order placement
- MongoDB `market_bars` collection — read at startup for warmup (read-only, no schema change)
- No API or DB schema changes required
