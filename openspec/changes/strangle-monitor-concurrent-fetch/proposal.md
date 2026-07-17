# strangle-monitor-concurrent-fetch

## Why

A `/fastapi-code-review` pass (2026-07-17) on the uncommitted `execution-panel-freshness-and-events`
+ `indicator-matrix-kite-parity` diffs found that `GET /api/v1/strangle/monitor`
(`routes.py:718`, `response_model=StrangleMonitorOut`) awaits four independent I/O chains
**sequentially** instead of concurrently, and the diff deepened this on two of them:

1. `routes.py:762-767` — 3 indices (`_INDEX_SIDS`) x 2 Redis calls each (`_get_ltp_redis` +
   the new `_get_ltp_age_redis`), none depending on another index.
2. `routes.py:780-797` — one `_get_greeks_for_strike` await per open leg, in a `for` loop; each
   leg's chain-snapshot lookup is independent of the others.
3. `routes.py:889-898` — `_build_indicator_cell` awaited once per (sid, tf) pair, 3 sids x 5
   timeframes (`_MATRIX_TFS`) = 15 sequential calls; in the Redis-fallback role (`engine is None`,
   the decoupled `pdp-api` deployment) each cell now does 4 sequential `redis.get()`s instead of 3
   (this diff added `st_variants_raw`), so up to 60 sequential Redis round trips for the matrix alone.
4. `routes.py:700-714` (new `_build_atm_option_rows`) — CE and PE resolved sequentially even though
   they're fully independent lookups.

This is the same endpoint whose live Mongo-timeout behavior (`atm_option_rows_failed`, ~every
9-10s) was root-caused and fixed this session (missing `option_bars(security_id, timeframe, ts)`
index — see `backend/pdp/mongo/collections.py`). The route is polled every few seconds by the
Flutter Execution Console; stacking sequential round trips on top of a route with a proven
real-world latency problem compounds it directly.

## What Changes

- Replace each of the four sequential loops/chains above with `asyncio.gather(*...)` so independent
  I/O runs concurrently. No response shape, field, or ordering changes — purely a concurrency
  refactor of already-independent awaits.
- Add/extend tests in `tests/strategy/test_monitor_route.py` asserting the payload is unchanged and
  (where practically observable) that the underlying async calls are issued concurrently rather than
  serialized.

## Impact

- Affected specs: `strategy-execution-monitor` (sharpen "Realtime strangle monitor endpoint" to
  require independent per-item/per-chain I/O to run concurrently).
- Affected code: `backend/pdp/strategy/routes.py` (`strangle_monitor`, `_build_atm_option_rows`)
  only. No schema, migration, or behavior changes — same fields, same values, lower latency.
