# execution-console-daily-parity

## Why

The live execution console shows a **different set of positions and trades every day** than what
actually happened. Investigating the 2026-07-08 monitor snapshot pinned three independent,
reproducible root causes — the "daily discrepancy" is all three overlapping:

1. **Phantom P&L from `entry_price = 0` (CONFIRMED, arithmetic-proven).** When a strangle leg is
   opened on a **freshly-subscribed option whose `ltp:` cache is still cold**, the paper broker
   cannot fill from cache and `_await_fill_avg_px` (`directional_strangle.py:654-663`) falls
   through to `return Decimal("0")`. The leg is stored with `entry_price=0`, so `state()`
   computes MTM as `_leg_pnl(entry=0, ltp) = -ltp × qty` — a pure phantom loss. In the snapshot,
   SENSEX `SHORT PE` MTM `-16,324` is exactly `-204.05 × (4 lots × 20)` and `SHORT CE` `-14,706`
   is exactly `-122.55 × (6 × 20)`. These phantom losses corrupt day P&L **and** feed the
   hard-cap auto-kill. The console shows these legs with `entry —`.

2. **PG cost basis lost on reopen / reversal (CONFIRMED, sibling of C1).** `upsert_position`
   (`orders/paper.py:382-419`) only sets `avg_price` when opening from an absent row or adding to
   a same-sign position. When a **flat row (net_qty=0, avg_price=0) is reopened**, or a fill
   **reverses through zero**, control lands in the `else` (reducing) branch, `reduce_qty` clamps
   to 0, and `avg_price` is **never re-based to the new fill** — it stays `0`/stale. Any consumer
   reading PG `Position.avg_price` (`/api/v1/positions`, leg rehydration) then shows `entry —`.

3. **In-memory legs are lost on restart (CONFIRMED).** `_short_legs`/`_hedge_legs`/
   `_momentum_legs` are in-memory only (initialised `[]` at `directional_strangle.py:205`, with
   **no rehydration path** — only the done-for-day halt marker is restored). After an intraday
   restart the console's `/legs` + `/monitor` under-report or drop open legs that still exist in
   PG and at the broker → the "paper execution tab not covering all trades for the day."

4. **The trade ledger is file-based, not DB-first (CONFIRMED, violates a project rule).**
   `/api/v1/strangle/trades` derives the round-trip ledger from **local JSONL log files**
   (`trade_ledger.read_day_events` → `logs/<sid>/<day>.log`). A different cwd, a rotated file, or
   a restart silently yields `[]`. This breaks the DB-first "no local files once in DB" rule
   ([[db_first_no_local_files]]).

5. **The Live Dhan account tab is stale all day (CONFIRMED).** Holdings/positions/funds come from
   the `broker_sync` PG mirror, refreshed **only once per day at 15:45 IST EOD**
   (`broker_sync/scheduler.py:50-64`) or a manual `POST /broker-sync/run`. There is **no intraday
   poll**, so the tab shows the previous EOD snapshot and **manual positions opened in the Dhan
   terminal today are invisible** until 15:45.

Underneath all five: there are **three uncorrelated views of "my positions"** — the strategy's
in-memory legs, the PG `orders.Position` ledger, and the broker's own `BrokerPosition` — and
**nothing reconciles them intraday**, so any drift surfaces as the daily discrepancy.

## What Changes

- **Never store a zero entry price.** `_await_fill_avg_px` must resolve a real fill price (broker
  avg → cached LTP → chain LTP → last bar close) before a leg is recorded; if none resolves, the
  leg open is **aborted and squared, and a CRITICAL event is emitted** (reuses change #4's
  `emit_critical` / `MISSING_LTP`), rather than storing `entry_price=0`. One reusable
  `resolve_fill_price()` helper, single-responsibility.
- **Re-base cost basis generically.** Refactor `upsert_position` so that after booking realized
  P&L on the closed quantity, the residual/new leg's `avg_price` is set to the fill price whenever
  the position opens from flat or reverses sign — one branch-free helper computing the new
  `(net_qty, avg_price)` from `(old_qty, old_avg, fill_qty, fill_price)`. (Shared with change #1's
  C1 fix; this change extends it to the flat-reopen case and adds the parity test.)
- **Rehydrate strategy legs on restart** from the durable position ledger: on startup the strategy
  reconstructs `_short_legs`/`_hedge_legs`/`_momentum_legs` (with correct `entry_price`, lots,
  strike, hedge/momentum classification) from PG positions + the last `leg_open` events, so the
  console reflects reality after a restart.
- **DB-first durable trade ledger.** Derive `/strangle/trades` from a durable store — PG `trades`
  joined to the Mongo `events` `leg_open`/`leg_close` stream — instead of local JSONL, with the
  file reader kept only as a last-resort fallback. Same pairing logic, durable source.
- **Intraday live broker-account refresh.** Add a market-hours poller (interval-configurable,
  paper-safe no-op without `LIVE`/creds) that refreshes the `broker_sync` holdings/positions/funds
  mirror via the existing read-only `BrokerAccountClient`, and expose `last_synced_at` on the
  broker-sync read endpoints so the Flutter tab can show freshness / a stale badge.
- **Three-way reconciliation + alert.** A reconciler compares in-memory legs ↔ PG positions ↔
  broker positions and emits a CRITICAL event (reuses change #4) on divergence beyond tolerance
  (a leg with no broker position, a broker position with no leg, a qty/side mismatch).

## Impact

- **Affected specs:** `execution-console-daily-parity` (new — entry-price integrity, leg
  rehydration, durable ledger, intraday broker refresh, reconciliation). Distinct from the
  in-flight `execution-console-accuracy` (indicator/warmup parity) — this is position/trade
  completeness.
- **Affected code:** `strategies/directional_strangle.py` (`_await_fill_avg_px`, leg open,
  startup rehydration, reconcile hook), `orders/paper.py` + `orders/dhan_broker.py`
  (`upsert_position` re-base helper), `strategy/trade_ledger.py` (durable source) +
  `strategy/routes.py` (`/strangle/trades`), `broker_sync/scheduler.py` (+ new intraday poller) +
  `broker_sync/service.py` + `broker_sync/routes.py` (`last_synced_at`), new
  `strategy/reconcile.py`, `settings.py` (poll interval + reconcile tolerance), `app/lib/` (stale
  badge + reconciliation warning on the Live/Execution tabs).
- **Reuses:** change #4's `emit_critical`/event types (`MISSING_LTP`, `NAKED_POSITION`,
  a new `POSITION_RECONCILE_MISMATCH`); the read-only `BrokerAccountClient`; the existing
  `events`/Mongo + PG `trades` stores; the existing `pair_trades` pairing logic.
- **Depends on / cross-refs:** change **#1 api-reliability-hardening** (owns the `upsert_position`
  C1 cost-basis fix — this change extends + tests it) and change **#4
  strategy-critical-data-alerts** (owns `emit_critical` + the missing-data event types this change
  publishes). Ship after #1 and #4.
- **Infra:** no new managed resource; the intraday poll interval is env-tunable via
  `get_settings()`. After the split (change #3) the poller runs in the `ops`/`engine` process.
