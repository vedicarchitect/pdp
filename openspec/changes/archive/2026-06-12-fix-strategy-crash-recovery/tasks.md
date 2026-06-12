## 1. Ledger query helper

- [x] 1.1 Check `src/pdp/strategy/context.py` — does `OrderContext` expose a per-security realized P&L query? If not, add `get_realized_pnl_per_security(strategy_id) -> dict[str, float]` that queries the ledger trades table and returns `{security_id: total_realized}`.
- [x] 1.2 Verify `get_positions(strategy_id)` exists and returns `net_qty` per security; confirm the filter on `strategy_id` works correctly.

## 2. Recovery helper

- [x] 2.1 Create `src/pdp/strategy/recovery.py` with async function `recover_strategy_state(ctx, strategy_id, lot_size, today_ist) -> tuple[dict | None, dict[str, float]]` — returns `(recovered_current, day_baseline)`.
- [x] 2.2 Implement open-leg recovery: query positions for `strategy_id`, find first row with `net_qty < 0`, look up instrument for `option_type` / `strike`, derive `lots = abs(net_qty) // lot_size`. Log warning if `abs(net_qty) % lot_size != 0`.
- [x] 2.3 Implement cross-day guard: check last fill date for the recovered position; if IST date != `today_ist`, return `(None, {})` and log a warning.
- [x] 2.4 Implement day-baseline recovery: call `get_realized_pnl_per_security(strategy_id)` and return the result as `day_baseline`.
- [x] 2.5 Emit structured log event `state_recovered` with `current_security_id`, `lots`, `day_baseline_total` when a leg is recovered; emit nothing when flat.

## 3. Wire into SuperTrendShort

- [x] 3.1 In `SuperTrendShort.on_init()`, call `recover_strategy_state(...)` after initializing fields and before returning.
- [x] 3.2 Assign returned `recovered_current` to `self._current` and `day_baseline` to `self._day_baseline` (only when not `None`).
- [x] 3.3 Confirm `_direction` is NOT recovered here — it is derived from the first bar's SuperTrend indicator.

## 4. Tests

- [x] 4.1 Unit test in `tests/strategy/test_supertrend_smoke.py` (or a new `tests/strategy/test_crash_recovery.py`): mock positions table with one open short CE (5 lots); assert `_current` is populated correctly and `_day_baseline` matches the mocked ledger values after `on_init()`.
- [x] 4.2 Unit test: restart with no open positions → `_current` remains `None`, `_day_baseline` is `{}`.
- [x] 4.3 Unit test: restart with a position dated yesterday (IST) → `_current` remains `None` and a warning is logged.
- [x] 4.4 Unit test: `net_qty` not divisible by `lot_size` → lots floored, warning logged.
