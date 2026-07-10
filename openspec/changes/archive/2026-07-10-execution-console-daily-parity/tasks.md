# Tasks — execution-console-daily-parity

## 1. Never-zero entry price
- [x] 1.1 `resolve_fill_price(sid)` helper: broker avg → `ltp_cache` → chain LTP → last bar close
- [x] 1.2 `_await_fill_avg_px` returns a resolved price or `None`; leg-open path squares + emits
      CRITICAL `MISSING_LTP` (reuses change #4) instead of storing `entry_price=0`
- [x] 1.3 Guard `_leg_pnl`/`state()` so a leg can never present MTM `= -ltp × qty`
- [x] 1.4 One-off repair: re-base any currently-open PG position with `avg_price == 0`

## 2. Position cost-basis re-base (with change #1)
- [x] 2.1 Extract pure `compute_position_update(old_qty, old_avg, fill_qty, fill_price)`
- [x] 2.2 `upsert_position` (paper + dhan) delegates to it; delete inline branches
- [x] 2.3 Covers flat→reopen and reversal-through-zero (both re-base `avg_price` to fill)

## 3. Leg rehydration on restart
- [x] 3.1 `rehydrate_legs()`: rebuild `_short_legs`/`_hedge_legs`/`_momentum_legs` from PG
      positions + last `leg_open` events (entry_price, lots, strike, hedge/momentum)
- [x] 3.2 Call on strategy startup; idempotent; skip `net_qty == 0` rows

## 4. Durable DB-first trade ledger
- [x] 4.1 `trade_ledger` reads PG `trades` ⨝ Mongo `events` (`leg_open`/`leg_close`); same
      `pair_trades()` logic; JSONL only as last-resort fallback
- [x] 4.2 `/strangle/trades` uses the durable source; never silently returns `[]` on restart

## 5. Intraday live broker-account refresh
- [x] 5.1 `broker_sync/intraday_poller.py`: market-hours loop (interval
      `BROKER_INTRADAY_POLL_SECONDS`) refreshing holdings/positions/funds via `BrokerAccountClient`
- [x] 5.2 Paper-safe no-op without `LIVE`/creds; failure keeps last good snapshot + WARNING
- [x] 5.3 Expose `last_synced_at` on `/broker-sync/{positions,holdings,funds}`

## 6. Three-way reconciliation
- [x] 6.1 `strategy/reconcile.py`: compare in-memory legs ↔ PG positions ↔ broker positions
- [x] 6.2 Emit CRITICAL `POSITION_RECONCILE_MISMATCH` beyond `RECONCILE_TOLERANCE_LOTS`
      (read-only — no auto-trade); run on timer + after each fill
- [x] 6.3 Add `POSITION_RECONCILE_MISMATCH` to `events/models.py`

## 7. Flutter
- [x] 7.1 Live account tab: `last_synced_at` + stale badge (`BROKER_STALE_SECONDS`)
- [x] 7.2 Execution tab: reconciliation-mismatch warning banner

## 8. Tests + validation
- [x] 8.1 Backend tests per Phase 3 (no-zero-entry, no-phantom-MTM, position re-base ×2,
      rehydrate, durable ledger, intraday poll, reconcile-on-divergence)
- [x] 8.2 `task test` green; `cd app && flutter analyze && flutter test` green
- [x] 8.3 Verify against a live day: no `fill_avg_px_zero`; no leg with `entry —`; day-loss cap
      cannot be tripped by a zero-entry leg
- [x] 8.4 `openspec validate --strict execution-console-daily-parity` passes
