## Why

When the strategy host process crashes mid-session, `SuperTrendShort` restarts with blank in-memory state: `_current = None` and `_day_baseline = {}`. It has no knowledge of the open position left by the crashed run, so it trades as if flat — accumulating ghost lots in the positions table alongside new live lots. The first flip order then covers far more qty than intended (e.g. 585 qty / 9 lots instead of 4), causing large unintended P&L swings. Additionally, the day-stop guard under-counts realized losses because the baseline is rebuilt from zero at restart.

Observed on 2026-06-12: a crash at ~10:10 IST left CE 50574 (5 lots short) open; after restart at 11:38, the strategy re-entered CE 50574 at 12:10, accumulating 9 lots total; the flip at 12:25 bought 585 qty instead of 260.

## What Changes

- `SuperTrendShort.on_init()` SHALL query the positions table on startup and, if an open short position exists for any of the strategy's instruments, reconstruct `_current` from it (security_id, segment, option_type, strike, lots derived from `net_qty`).
- `SuperTrendShort.on_init()` SHALL reconstruct `_day_baseline` by reading each security's realized P&L from the ledger at startup so `_day_realized()` correctly reports cumulative day loss from before the restart.
- The same recovery logic SHALL be extracted into a reusable mixin / base-class method so other strategies can adopt it without duplicating code.

## Capabilities

### New Capabilities

- `strategy-crash-recovery`: Defines the requirement that a strategy recovers its open-position state and day P&L baseline from durable storage on restart, preventing ghost-position accumulation and day-stop bypass.

### Modified Capabilities

- `supertrend-strategy`: Add scenario: strategy recovers open leg and day P&L baseline after restart.

## Impact

- `src/pdp/strategies/supertrend_short.py`: `on_init()` modified to call recovery logic.
- `src/pdp/strategy/context.py` or a new `src/pdp/strategy/recovery.py`: recovery helper reads `ctx.orders.get_positions()` and `ctx.orders.get_realized_pnl()` (or equivalent ledger query).
- `tests/strategy/test_supertrend_smoke.py` and new unit test: cover restart-with-open-position scenario.
- No API or schema changes; purely runtime state recovery.
