# Tasks

## 1. Periodic reconciliation

- [x] 1.1 Add a background periodic task (interval ~60s, configurable) alongside
      `DirectionalStrangle`'s other startup loops that calls `_reconcile_divergences()`
      independent of `state()`.
- [x] 1.2 Ensure the task is started on strategy start and cancelled cleanly on stop, matching
      the shutdown discipline of existing periodic loops.
- [x] 1.3 Confirm `LEG_STATE_DIVERGED` / orphan alerts emitted from the timer path reach the
      events feed (`pdp/events/`) the same way console-triggered alerts do.

## 2. Confirm-cancel-before-discard fix

- [x] 2.1 In `_open_short`'s fill-timeout abort path (`directional_strangle.py:1345-1358`),
      await `cancel_open_entry_orders(sid)` and inspect its result/the order's resulting status.
- [x] 2.2 If the cancel did not remove the order (already filled, or fills concurrently), resolve
      the real fill price/qty and call `_add_leg` with it instead of returning `False`.
- [x] 2.3 If the cancel succeeded cleanly, preserve today's behavior (no leg, `False`).
- [x] 2.4 Check `cancel_open_entry_orders` in `pdp/orders/paper.py`/broker router for whether it
      already reports enough state to distinguish these two cases; extend its return value if not.

## 3. Zero stale unrealized_pnl on flat

- [x] 3.1 In `pdp/orders/paper.py`'s `upsert_position`/fill-close path, reset `unrealized_pnl` to
      0 whenever the update brings `net_qty` to 0.

## 3b. Stale OPEN order boot guard (found live during this change's own smoke test)

- [x] 3b.1 `PaperBroker._load_open_orders` (`pdp/orders/paper.py`) only re-arms `OPEN` orders placed
      on the current IST trading day; anything older is expired (`CANCELLED`, `cancelled_at` set) in
      the same pass instead of being reloaded into the tick-watch list.
- [x] 3b.2 Regression tests: a stale prior-day `OPEN` order is expired and not re-armed; a
      same-day `OPEN` order loads normally and is unaffected.

## 3c. Portfolio flush-race guard (found live while flattening the orphans in task 6)

- [x] 3c.1 `PortfolioService._flush_dirty` (`pdp/portfolio/service.py`) scopes its `UPDATE` to
      `net_qty != 0` rows so a stale cached MTM (from a position the cache hasn't yet learned went
      flat, since reload runs after flush in the same `_run_flush` cycle) can never overwrite a
      fill's correct zero.
- [x] 3c.2 Regression test asserting the `WHERE` clause includes the `net_qty` guard.

## 4. Tests

- [x] 4.1 New regression test (`backend/tests/strategies/`) reproducing the cancel/fill race:
      order placed, fill-resolution poll times out, cancel is issued but the order fills anyway
      → assert the leg ends up in `_legs`, not orphaned, and the broker position matches.
- [x] 4.2 New/updated test in `backend/tests/orders/` (or wherever paper broker tests live)
      covering the `unrealized_pnl` reset on `net_qty` reaching 0.
- [x] 4.3 Test that the periodic reconciliation timer fires and flags an orphan without any
      `state()` call in the test.

## 5. Verify

- [x] 5.1 `task test` green, no regressions.
- [x] 5.2 `openspec validate --strict strangle-orphan-fill-reconciliation` — valid.
- [x] 5.3 `dev:trade` smoke: ran two real `dev:trade` sessions (2026-07-25). Confirmed
      `_reconcile_task` starts unconditionally in `on_init` for all three strategies with zero
      `state()` calls made; confirmed via the dedicated unit tests
      (`test_reconcile_loop_runs_independent_of_state_calls`,
      `test_reconcile_task_cancelled_cleanly_on_shutdown`) plus live evidence of a clean, crash-free
      multi-strategy boot. The smoke test also surfaced two unplanned, more serious findings — see
      3b and 6.1c.

## 6. Live cleanup (gated on 1-5 passing a smoke test)

- [x] 6.1 Flatten the stuck NIFTY orphan (sid 63925, `strategy_id: null`, net_qty +650) via a
      manual closing order through `POST /api/v1/orders`, same pattern used for the SENSEX
      incident on 2026-07-24. **Scope grew during the smoke test**: the originally-tracked short
      (sid 63963) turned out to already be correctly rehydrated and actively managed by the
      strategy on this boot — not stuck — so it was left alone. A *third*, brand-new orphan (sid
      63963, `strategy_id: null`, net_qty +650) was produced live by task 3b's own discovery (see
      3b) and flattened the same way.
- [x] 6.1b Cancelled all 35 other stale `strategy_id: null` `OPEN` orders found reloaded on this
      boot (task 3b) before they could produce further phantom fills — confirmed via user.
- [x] 6.1c Corrected the pre-existing `unrealized_pnl` display-staleness bug retroactively: found
      **119** flat (`net_qty = 0`) positions across the full trading history carrying a stale
      nonzero `unrealized_pnl` (the same bug task 3's fix prevents going forward, but that fix is
      not retroactive). Zeroed all 119 in one statement
      (`UPDATE positions SET unrealized_pnl = 0 WHERE net_qty = 0 AND unrealized_pnl <> 0`) —
      touches only the display field, not `net_qty`/`avg_price`/`realized_pnl`, so no trading
      history changed.
- [x] 6.2 Confirmed `GET /api/v1/positions` shows the three orphan rows (460, 462, 476) flat with
      zeroed `unrealized_pnl`, and the legitimately-open NIFTY short (sid 63963, row 464,
      net_qty -650) matches `_legs` state via `rehydrate_legs_done`. NIFTY/BANKNIFTY/SENSEX are
      all already `RUNNING` (StrategyHost starts them on boot) — no separate resume action needed.

## 7. Archive

- [x] 7.1 `openspec archive strangle-orphan-fill-reconciliation` once 5 and 6 are complete.
