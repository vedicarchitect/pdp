## Why

Three feed/data-integrity gaps put live trading and backtests at risk:

1. **Silent feed death.** `DhanTickerAdapter` reconnects with backoff, but nothing detects a feed
   that is *connected yet silent* — the Dhan SDK can stop delivering ticks without raising. A
   strategy then trades on stale LTP with no warning.
2. **Backfill holes.** `gap_backfill.py` chunks intraday history, but if Dhan returns an empty
   **HTTP 200** for a middle chunk of a valid window, the day is persisted with a hole. OpenAlgo
   detects this as server flakiness (data before *and* after, empty in between) and refuses to
   persist a partial day.
3. **Stale reference data.** The Dhan scrip master (lot sizes, expiries, new strikes, freeze
   limits) is only loaded on demand, so lot-size or expiry changes can go unnoticed.

The reconnect max delay is also hardcoded (`MAX_RECONNECT_DELAY = 30.0`) rather than configurable.

## What Changes

- **Stale-feed watchdog** — track `last_tick_time`; if no ticks arrive for `FEED_STALE_SECONDS`
  during market hours, emit a `feed_stale` structlog event and force a reconnect. Never auto-evict
  (quiet markets are legitimate) — warn + reconnect only.
- **Configurable reconnect** — move the hardcoded backoff ceiling/base into `get_settings()`.
- **Interior-gap detection** in `gap_backfill.py` — if a chunk returns 0 candles but chunks before
  and after it have data, retry and refuse to persist a partial day (port the `nonempty_idx` /
  `interior_empty` logic from OpenAlgo's `data.py`).
- **Scheduled scrip-master refresh** — a daily pre-open refresh wrapping the existing loader,
  recording lot-size/expiry diffs via `instruments/snapshots.py`. Gated, default off.

## Capabilities

### New Capabilities
- `feed-health`: stale-feed detection and configurable reconnection for the live tick feed; emits
  a `feed_stale` signal that the ops-safety-net change consumes for safe-halt.

### Modified Capabilities
- `market-data`: backfill SHALL NOT persist a day containing an interior empty chunk; the scrip
  master SHALL be refreshable on a daily pre-open schedule.

## Impact

- **`backend/pdp/market/dhan_ws.py`**: `last_tick_time` tracking; watchdog task; reconnect delays
  from settings.
- **`backend/pdp/market/router.py`**: surface the freshest-tick timestamp for the watchdog/health.
- **`backend/pdp/options/gap_backfill.py`**: interior-gap detection in the chunk loop; per-day
  all-or-nothing persistence on detected flakiness.
- **`backend/pdp/instruments/loader.py` + `snapshots.py`**: scheduled refresh + diff recording.
- **`backend/pdp/settings.py`**: `FEED_STALE_SECONDS`, `FEED_RECONNECT_BASE_DELAY`,
  `FEED_RECONNECT_MAX_DELAY`, `SCRIP_REFRESH_ENABLED`, `SCRIP_REFRESH_TIME` (IST HH:MM).
- **`backend/pdp/main.py`**: start the watchdog + scrip-refresh tasks in lifespan (gated).
- **`docs/RUNBOOK.md`**: feed-health + backfill-integrity notes.
