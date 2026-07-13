# Market Feed Module

## Files

| File | Size | Role |
|------|------|------|
| `dhan_ws.py` | 11.2 KB | `DhanTickerAdapter` — WS client to Dhan feed; produces tick queue; only starts if creds set |
| `router.py` | 5.9 KB | `TickRouter.run(queue, redis)` — hot path; fan-out tick to bar/WS/strategy/alerts |
| `bars.py` | 4.9 KB | `BarAggregator` — buckets ticks into 1m/5m/15m/30m/1H OHLCV bars |
| `bar_writer.py` | 3.1 KB | `BarWriter` — async batch writer to MongoDB `market_bars` collection |
| `ws.py` | 4.8 KB | `WSHub` + `ws_router` — `/ws/market` endpoint; streams ticks to browser |
| `routes.py` | 3.6 KB | REST: subscribe/unsubscribe instruments, get latest bars |
| `subscription_model.py` | 0.7 KB | `Subscription` dataclass |
| `models.py` | 0.4 KB | `Bar` dataclass |

## Hot Path (latency budget: p99 ≤ 50ms)

```
DhanTickerAdapter.queue
  → TickRouter.run()                             # runs in the "engine" role/process
      ├── Redis SET ltp:<security_id> EX5       # LTP cache for PaperBroker
      ├── Redis PUBLISH tick.<security_id>       # pub/sub — consumed by the API
      │                                          # process's MarketBridge, which fans
      │                                          # out to WSHub there (no in-process
      │                                          # WSHub call from the engine)
      ├── BarAggregator.push(tick)          # drops ticks outside [09:15,15:30) IST
      │     │                                # or on a weekend/NSE_HOLIDAYS_JSON holiday
      │     on bar close:
      │       ├── Redis XADD bars.<id>.<tf>       # also consumed by MarketBridge
      │       ├── BarWriter.enqueue(bar)  →  MongoDB market_bars
      │       ├── IndicatorEngine.update(bar)
      │       └── StrategyHost.on_bar(bar)
      └── AlertEvaluator.on_tick(tick)
```

## Rules

- **No blocking calls in TickRouter.run()** — everything must be `asyncio`-native or offloaded.
- Bar timeframes are computed by `BarAggregator`; don't hardcode timeframe logic elsewhere.
- `DhanTickerAdapter` only starts when `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN` are set.

## Session anchoring (`bar-session-anchoring`, 2026-07-11)

Bar boundaries are anchored to the 09:15 IST session open, not the Unix epoch. `_session_open_utc`
returns 09:15 IST on a tick's own IST trading day; `_bar_boundary` truncates `(dt - session_open)`
into `tf_minutes` buckets from there. 5m/15m coincide with the epoch grid either way (225 min —
UTC midnight to 03:45 UTC session open — divides evenly into both), but 25m/30m/1H do not: under
epoch anchoring they land on `:00`/`:30` instead of the session grid, and 25m drifts by a different
offset every day. All bucket math lives in `bars.py` only — nothing else in `pdp` reimplements it
(`_bar_boundary_1d`/`_bar_boundary_1w` are separate, day/week-grid functions and were not affected).

`BarAggregator.push` also enforces the trading session itself, not just the bucket grid: a tick is
dropped (no bar opened or extended) unless its IST time-of-day falls in `[09:15:00, 15:30:00)` *and*
its IST calendar date is a trading day (`weekday() < 5` and not in the `NSE_HOLIDAYS_JSON` holiday
set, loaded once at startup in `pdp/runtime/groups.py` and passed to both `BarAggregator` and
`BarSessionScheduler`). Without the trading-day check, a stale/heartbeat print delivered during
nominal session-hours-of-day on a weekend or holiday would otherwise be aggregated as if it were a
real bar — this happened live on Saturday 2026-07-11 before the check was added. The clock-time
check is cheap integer arithmetic and runs first; the calendar check only runs once the clock check
has already passed, so real trading days pay no extra cost.

`BarSessionScheduler` (`session_scheduler.py`) force-closes every builder's open bucket once per
trading day at 15:30 IST via `BarAggregator.flush_session()`, so the final partial bucket of the day
(15:15–15:30 for 30m) is emitted even when no further tick ever arrives to trigger the usual
boundary-crossing close.

## MongoDB `market_bars` Schema

`market_bars` is a Mongo **timeseries** collection (`timeField="ts"`, `metaField="metadata"`) —
fields that identify the series live nested under `metadata`, not at the top level, and the
collection cannot carry a unique index (unlike `option_bars`, which is a regular collection built
specifically so it can enforce one via `uq_contract_ts`).

```python
{
  "ts": datetime,                    # bar open timestamp (UTC), session-anchored
  "metadata": {
    "security_id": str,
    "timeframe": str,                # "1m", "5m", "15m", "30m", "1H", "1D", "1w"
  },
  "open": Decimal,
  "high": Decimal,
  "low": Decimal,
  "close": Decimal,
  "volume": int,
  "oi": int | None,
}
```

No unique index exists or can exist on a timeseries collection. `BarWriter._flush()` deletes any
pre-existing document for each exact `(security_id, timeframe, ts)` bucket in the batch before
`insert_many` (`market-bars-duplicate-write-fix`, 2026-07-13) — idempotent regardless of why a
bucket was enqueued twice. Root cause: `BarSessionScheduler.flush_session()` force-closes every
open builder at 15:30 IST and resets it to `_bar_time = None`; a network-delayed tick whose LTT
still falls in the just-flushed bucket is then treated as a brand-new "first tick" for that same
bucket (`BarBuilder.push`), and the *next* boundary-crossing tick emits a second `BarClosed` for it
— see `test_late_tick_after_flush_reopens_and_re_closes_the_same_bucket` in
`tests/market/test_bar_boundary.py`. This affects every timeframe `flush_session()` touches,
including `1D`/`1w` (found 2026-07-11 during the session-anchoring rebuild: 259/1,257 rebuilt
`(sid, timeframe)` pairs had duplicate documents for the same bucket; a follow-up audit on
2026-07-13 found 510 duplicate buckets in the 2026-01-01→2026-04-08 window alone, all on `1D`/`1w`).
Historical duplicates outside the already-rebuilt 2026-04-08→2026-07-11 range are not yet cleaned up
— `scripts/oneoff/dedup_market_bars.py` is written and dry-run-verified but has not been run for
real against production data (needs a backup + an off-hours window). TTL controlled by
`MONGO_CHAIN_TTL_DAYS`.

## Rebuilding stored bars

`backend/scripts/oneoff/rebuild_market_bars.py` re-derives `15m`/`30m`/`1H` docs from the dense,
session-aligned `1m` source for a `(security_id, date-range)` — delete-then-insert per `(sid, tf)`,
since timeseries collections have no in-place update. `--dry-run` reports `existing_count`/
`new_count`/`first_ts`/`last_ts` per pair and makes no writes. See `docs/RUNBOOK.md` for the backup
and restore procedure before running it for real.
