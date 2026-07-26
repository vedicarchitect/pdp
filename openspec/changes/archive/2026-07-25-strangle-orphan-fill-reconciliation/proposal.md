# strangle-orphan-fill-reconciliation

## Why

On 2026-07-24 (live paper session, all three strangles trading), NIFTY's `_open_short` closed both
legs cleanly on a legitimate `bucket_change` (11:55:11 IST, correct P&L logged for both), then
placed two reopen MARKET orders (security_ids 63925 and 63963) at 11:55:20 IST — directly into a
sustained `tick_dropped` backpressure storm in `pdp/market/dhan_ws.py`'s WS ingest queue
(`maxsize=1000`, drop-oldest under `full()`), itself triggered by two live restarts done that
session (each forcing a full-instrument resubscription burst).

Read-only log/DB diagnosis (`GET /api/v1/positions`) proved the resulting state:

- `_resolve_fill_price` (`directional_strangle.py:1245-1279`) exhausted all three fallback layers
  (broker-avg poll ~1.2s, in-process LTP cache, Redis market-feed LTP) inside the drop window and
  returned `None` for both reopen orders.
- `_open_short`'s abort path (`:1345-1358`) called `cancel_open_entry_orders(sid)` and returned
  `False` **without confirming the cancel actually removed the order** from
  `PaperBroker._open_orders` (`pdp/orders/paper.py`). Both orders filled for real once the tick
  backlog drained a few seconds later — after the strategy had already discarded them.
- One landed as an **orphan** Position (`strategy_id: None`, sid 63925, `net_qty: 650`,
  `unrealized_pnl: -73,139.63`) that no strategy code has any handle on. The other landed
  correctly-tagged (`strategy_id: directional_strangle_nifty`, sid 63963, `net_qty: -650`) but was
  never registered in the strategy's in-memory `_legs` — a live short leg the strategy does not
  know it holds and therefore cannot manage, stop, or square off.
- No exception, error, or divergence alert was logged anywhere for either case.

The `_add_leg` `ValueError` branch (`:1371-1379`) already anticipates a version of this exact
failure and has a comment deferring to "the next `_reconcile_divergences()` poll" — but
`_reconcile_divergences` (`:2094-2138`) is only ever invoked from `state()`
(`pdp/strategy/routes.py`), a REST-only code path with no timer or bar hook. Nobody polled the
console during the ~7-minute drop window, so the safety net the code already relies on never ran
and nothing alerted. (`strangle-reconcile-latch-clears`, in-flight, fixes the divergence flag's
*stickiness* once it fires — complementary to this change, not overlapping.)

Separately, sid 63925's now-flat strategy-tagged Position row still carries a stale
`unrealized_pnl: -18,343.91` that was never zeroed when `net_qty` reached 0 — a distinct P&L
display/reset bug in `pdp/orders/paper.py`'s fill/close path, surfaced by the same incident.

This `strategy_id: null` orphan pattern is not new to yesterday — the ledger holds several older
such rows (sids 44573, 44643, 44654, 44662, 44686, 61850, dating back to 2026-07-01), which
suggests this failure mode has fired silently before without being caught.

**Second root cause, found during this change's own `dev:trade` smoke test (2026-07-25).** Starting
the API reloaded **36** `status: OPEN` orders from Postgres, all `strategy_id: null`, all placed in a
single ~3-second burst on 2026-07-24T06:25:18-21Z — the exact restart-storm window above, and the
true source of the "several older orphan rows" noted above (they are the same incident, not older
ones). `PaperBroker._load_open_orders` (`pdp/orders/paper.py:174-183`) unconditionally reloads every
`OPEN` order on boot with no age or trading-day check, and re-arms it to fill against whatever tick
comes next. One of the 36 (order 2958, sid 63963, `BUY 650`) had been sitting `OPEN` for almost 25
hours; the instant a live tick landed for it on this boot, it **filled for real** at 2.5505 — a
third, brand-new orphaned position, discovered live, mid-verification of this very change. The other
35 were cancelled by hand (`DELETE /api/v1/orders/{id}`, confirmed via user) before they could do the
same. This is a distinct bug from the cancel/fill race above: even a *perfectly* cancelled order is
safe, but any order that is merely abandoned (crash, restart mid-flight, or a future bug this change
didn't anticipate) stays `OPEN` in the DB forever and is a live landmine on every subsequent boot.

## What Changes

- **Independent periodic reconciliation.** `_reconcile_divergences()` runs on a background timer
  (~60s) alongside the strategy's other periodic loops, not only when a REST `state()` call happens
  to occur. Its `LEG_STATE_DIVERGED` / orphan alerts reach the events feed reliably regardless of
  whether the console is being watched.
- **No leg is discarded out from under a live order.** `_open_short`'s fill-timeout abort path
  awaits `cancel_open_entry_orders(sid)` and checks whether the cancel actually took effect. If the
  order could not be cancelled (already filled, or a fill was already in flight), the strategy
  registers the leg from the real fill instead of silently walking away from it — this closes the
  race itself, not just its aftermath.
- **`unrealized_pnl` is zeroed with `net_qty`.** Wherever a paper Position's `net_qty` transitions
  to 0 in `pdp/orders/paper.py`, `unrealized_pnl` is reset to 0 in the same update.
- **Stale `OPEN` orders expire on boot instead of being re-armed.** `PaperBroker._load_open_orders`
  now only re-arms `OPEN` orders placed on the current IST trading day; anything older is expired
  (`status: CANCELLED`) in the same pass instead of being reloaded into the tick-watch list. Closes
  the second root cause found live during this change's own smoke test (see Why).
- **`PortfolioService` never re-clobbers a flattened position's zero.** `_flush_dirty`'s update is
  scoped to `net_qty != 0` rows only, closing the reload-ordering race described above.
- One-time live cleanup (tracked in `tasks.md` §6, gated on this change landing and passing a
  `dev:trade` smoke test): flattened the two originally-known stuck NIFTY positions plus a third
  one this change's own smoke test produced (via the same legitimate manual-order path used for
  the SENSEX incident the same day), and retroactively zeroed all 119 pre-existing
  `net_qty = 0 AND unrealized_pnl <> 0` rows found across the ledger.

**Third root cause, found while flattening the orphans found above.** Closing the two known
orphans exposed a second, independent race in `PortfolioService._flush_dirty`
(`pdp/portfolio/service.py:266-291`): `_run_flush` calls `_flush_dirty()` (push the in-memory
cache's `unrealized_pnl` to Postgres) *before* `_load_positions()` (reload the cache from
Postgres) in the same cycle. A fill landing between one reload and the next flush — exactly what
`upsert_position`'s zero-on-flatten fix produces — gets its correct zero clobbered back to the
stale cached value on the very next flush, because the cache doesn't yet know the position went
flat. Observed live: flattening orphan 63925 correctly zeroed `unrealized_pnl` in the same commit
as the fill, then it silently reverted to the pre-close value moments later. Fixed by adding
`Position.net_qty != 0` to `_flush_dirty`'s `UPDATE ... WHERE` clause — the same "trust the DB's
authoritative state over an in-memory snapshot" pattern as the `_fill` race fix above — so a flush
can never write over a position the DB already knows is flat.

**Scale of the retroactive display bug.** Auditing the full `positions` table for the
`net_qty = 0 AND unrealized_pnl <> 0` pattern this bug produces found **119** affected rows across
the entire trading history, all three strategies, not just the incident-adjacent ones. These are
pre-existing and not caused by this change; the fix above only stops new ones. All 119 were
corrected in one statement as part of this change's live cleanup (task 6.1c) — the correction only
touches the stale `unrealized_pnl` display field, never `net_qty`/`avg_price`/`realized_pnl`, so no
trading history changed.

Out of scope: reworking `dhan_ws.py`'s tick-queue drop policy (raises the tick→WS p99 ≤ 50ms
latency risk for a lower-value fix — the reconciliation timer and the confirmed-cancel fix close
the actual gap without touching the hot ingest path).

## Impact

- Affected specs: `strangle-observability-gaps` (reconciliation runs independently of `state()`),
  `directional-strangle` (an entry order's outcome is never silently discarded), `paper-pnl-correctness`
  (unrealized P&L is never stale on a flat position), `order-execution` (paper engine does not re-arm
  stale OPEN orders on boot).
- Affected code: `backend/pdp/strategies/directional_strangle.py` (`_open_short`,
  `_reconcile_divergences`, wherever periodic loops are started), `backend/pdp/orders/paper.py`
  (`_fill`/`upsert_position`/cancel path/`_load_open_orders`), `backend/pdp/portfolio/service.py`
  (`_flush_dirty`).
- No schema/migration changes. No change to backtest (this is a live/paper-only order-fill and
  reconciliation concern).
- Risk: low-to-moderate — touches the live order-abort path directly, so needs careful testing
  (new regression test reproducing the cancel/fill race) before a market-day smoke test.
