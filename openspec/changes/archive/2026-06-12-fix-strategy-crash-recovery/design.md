## Context

`SuperTrendShort` holds all session state in memory (`_current`, `_direction`, `_day_baseline`, `_done_for_day`). When the host process crashes mid-session, that state is lost. On restart the strategy believes it is flat, so it freely opens new entries in instruments that already have short positions in the positions table. The first flip then calls `_close_current`, which reads `net_qty` from the positions table (ghost + live lots combined) and issues a cover order for the full accumulated qty — far more than the strategy intended.

The positions table and ledger are durable (Postgres). All the information needed to reconstruct in-memory state survives the crash.

## Goals / Non-Goals

**Goals:**
- On strategy startup, recover `_current` (open leg) from the positions table if a non-zero short position exists for this strategy.
- On strategy startup, recover `_day_baseline` from the ledger's per-security realized P&L so `_day_realized()` correctly counts losses accrued before the restart.
- Extract recovery into a reusable helper so future strategies can adopt it.

**Non-Goals:**
- Recover `_direction` — it is re-derived from the next incoming bar's SuperTrend indicator, which is the correct source of truth.
- Recover positions from the broker (live mode) — only paper positions table is in scope for now.
- Automatic replay of missed bars during the crash window — that is a separate operational concern.

## Decisions

### Decision 1: Where to put the recovery logic

**Chosen**: A standalone async helper function `recover_strategy_state(ctx, strategy_id, lot_size, instruments)` in `src/pdp/strategy/recovery.py`, called from `SuperTrendShort.on_init()`.

**Alternatives considered**:
- Mixin class: adds inheritance complexity; a plain function is simpler and just as reusable.
- Base-class method on `StrategyBase`: couples all strategies to recovery semantics they may not need; plain function is opt-in.

### Decision 2: How to identify the open leg on restart

Query `ctx.orders.get_positions()` filtered by `strategy_id = self.strategy_id`. Iterate results; pick the first entry with `net_qty < 0` (we only sell, so a short position is the open leg). Derive:
- `lots = abs(net_qty) // lot_size`
- `option_type` from the instrument record (look up by `security_id` from the instruments table)
- `strike` from the instrument record
- `segment` from the position record

If multiple non-zero positions exist (shouldn't happen, but defensive), log a warning and recover from the most recently opened one (highest `id`).

If `net_qty >= 0` for all positions, treat as flat — no recovery needed.

### Decision 3: How to recover day_baseline

`_day_realized()` computes: `sum(ledger.realized_pnl(sec) - baseline[sec] for sec in touched)`. At startup, call `ctx.orders.get_realized_pnl_per_security(strategy_id)` (or equivalent ledger query) and store the result directly as `_day_baseline`.

**Known limitation**: seeding the baseline with the *current* ledger value means `_day_realized()` returns **0** immediately after recovery, not the pre-crash intraday loss. Any realized P&L from legs that closed earlier the same day before the crash is not re-counted toward the day cap at restart. Computing the exact "realized P&L before today" would require historical position snapshots that the schema does not store. The trade-off is accepted: the day cap resets to the recovery point, not the calendar-day boundary.

If the strategy's ledger API only exposes total realized (not per-security), fall back to querying per-security via the same path `_day_realized()` already uses.

### Decision 4: Guard against cross-day recovery

Check `_day_key` (the IST date string) before applying recovered state. If today's IST date does not match the date of the recovered position's last fill, skip recovery — the position is from a prior day and should have been squared off.

## Risks / Trade-offs

- **Partial ghost**: If the ghost position was partially covered manually before restart, `net_qty` reflects the remainder — recovery is still correct (it recovers what's actually open).
- **Wrong lot_size rounding**: If `abs(net_qty) % lot_size != 0`, the lot count will be floored. Log a warning; this is an ops issue, not a code bug.
- **`get_realized_pnl_per_security` may not exist**: If the method is missing from `OrderContext`, it must be added. This is a small ledger query; risk is low.
- **Trade-off**: Recovery adds ~1 DB roundtrip at startup. Acceptable since `on_init` runs once.

## Migration Plan

1. Add `src/pdp/strategy/recovery.py` with `recover_strategy_state()`.
2. Add `get_realized_pnl_per_security(strategy_id)` to `OrderContext` if not present.
3. Call `recover_strategy_state()` from `SuperTrendShort.on_init()`.
4. Add unit test: mock positions table with ghost short → verify `_current` and `_day_baseline` are recovered correctly.
5. Add smoke test: manual restart scenario.

No migration of existing data needed. No rollback required (recovery is additive; if it returns nothing, strategy behaves as before).

## Open Questions

- Does `OrderContext` already expose per-security realized P&L? Check `src/pdp/strategy/context.py` before implementing.
- Should recovery log a structured event (e.g., `state_recovered`) to the strategy log so operators know the restart was clean? (Recommend yes.)
