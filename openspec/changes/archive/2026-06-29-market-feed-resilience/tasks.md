## 1. Settings

- [x] 1.1 Add to `pdp/settings.py`: `FEED_STALE_SECONDS` (int, default 60),
  `FEED_RECONNECT_BASE_DELAY` (float, default 1.0), `FEED_RECONNECT_MAX_DELAY` (float, default 30.0),
  `SCRIP_REFRESH_ENABLED` (bool, default False), `SCRIP_REFRESH_TIME` (str, IST HH:MM, default "08:45")

## 2. Stale-feed watchdog + configurable reconnect

- [x] 2.1 In `pdp/market/router.py`, stamp a monotonic `last_tick_ts` on every tick (single
  assignment; hot-path-safe) and expose a getter
- [x] 2.2 Replace the hardcoded `MAX_RECONNECT_DELAY` (and base) in `pdp/market/dhan_ws.py` with
  the new settings
- [x] 2.3 Add a 1s watchdog task: if `now − last_tick_ts > FEED_STALE_SECONDS` and inside market
  hours and socket connected → emit `feed_stale` and call the existing reconnect routine
- [x] 2.4 Reuse the existing IST market-hours helper for the gate
- [x] 2.5 Start the watchdog in `pdp/main.py` lifespan (only when the live feed is active)

## 3. Interior-gap detection in backfill

- [x] 3.1 In `pdp/options/gap_backfill.py`, after fetching a day's chunks, build `nonempty_idx`
- [x] 3.2 Flag empty chunks strictly between first/last non-empty as interior gaps; retry those
  chunks up to N times (reuse the existing retry/backoff)
- [x] 3.3 On continued interior emptiness, skip the day's `upsert_option_bars_sync` and emit
  `backfill_interior_gap` (day stays visible to `days_missing`)
- [x] 3.4 Ensure a genuinely empty leading/trailing window is NOT treated as a gap
- [x] 3.5 Unit-test: data–empty–data ⇒ refuse; empty–empty–empty ⇒ allow

## 4. Scheduled scrip-master refresh

- [x] 4.1 Add a gated daily task (model on `broker_sync/scheduler.py`) that calls the existing
  `pdp/instruments/loader.py` refresh at `SCRIP_REFRESH_TIME`
- [x] 4.2 Diff new rows vs current `lot_size`/`expiry`/`freeze_qty`; record via
  `pdp/instruments/snapshots.py`
- [x] 4.3 Start the task in `pdp/main.py` lifespan when `SCRIP_REFRESH_ENABLED`
- [x] 4.4 Failure path: log, retain last-good, retry next day (never block startup)

## 5. Validation + archive

- [x] 5.1 `task openspec:validate -- market-feed-resilience --strict` passes
- [x] 5.2 `task test` green for interior-gap unit tests
- [x] 5.3 `docs/RUNBOOK.md` — feed-health + backfill-integrity notes
- [ ] 5.4 Owner check: induce a synthetic tick gap in paper → confirm `feed_stale` + reconnect,
  subscriptions restored
