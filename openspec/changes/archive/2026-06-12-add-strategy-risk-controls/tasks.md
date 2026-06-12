## 1. Params

- [x] 1.1 Add `leg_stop_per_lot` (default 1000) and `day_stop` (default 10000) to `strategies/supertrend_short.yaml` params
- [x] 1.2 Parse both in `SuperTrendShort.on_init`

## 2. MTM inputs

- [x] 2.1 Source avg entry + qty for the open leg (ledger-authoritative via `ctx.orders.get_position`, robust to async/partial fills — chosen over tracking on `_current`)
- [x] 2.2 Add an LTP read for the open leg (`ctx.market.ltp` reads Redis `ltp:<sid>`); guards missing / `<= 0`

## 3. Per-leg stop

- [x] 3.1 In `on_bar`, before flip/scale, compute unrealized MTM `(avg - ltp) * qty`; if loss ≥ `leg_stop_per_lot × lots`, `_close_current("leg_stop")` and return (no re-entry this bar)

## 4. Daily loss cap

- [x] 4.1 Accumulate realized P&L via per-security day baselines (`ctx.orders.get_realized_pnl`); reset on IST date rollover (`_maybe_reset_day`)
- [x] 4.2 If cumulative realized ≤ `-day_stop`, flatten and latch `_done_for_day`; block entries until next session

## 5. Tests

- [x] 5.1 Leg-stop fires at threshold, closes, and does not re-enter on the same bar
- [x] 5.2 Leg-stop does not fire one tick below threshold
- [x] 5.3 Day-stop latches after cumulative realized ≤ `-day_stop`; no further entries
- [x] 5.4 Zero/stale LTP does not trigger a stop
- [x] 5.5 Day-stop accumulator resets on a new IST day

## 6. Validation

- [x] 6.1 `openspec validate add-strategy-risk-controls --strict`
- [x] 6.2 Paper smoke test green (`tests/strategy/test_supertrend_smoke.py`); stop-driven closes covered by unit tests 5.1–5.5
- [x] 6.3 Cross-check one backtest stop day vs paper replay produces matching close reasons (manual, follow-up)
