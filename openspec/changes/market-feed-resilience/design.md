## Context

`pdp/market/dhan_ws.py` (`DhanTickerAdapter`) already has exponential-backoff reconnect
(`MAX_RECONNECT_DELAY = 30.0`), DB-backed subscription persistence, and queue backpressure. What
it lacks is any notion of "connected but silent." `pdp/market/router.py` (`TickRouter`) is the
fan-out point where every tick passes through — the natural place to stamp a freshest-tick time.

`pdp/options/gap_backfill.py` already has a token-bucket rate limiter, DH-904 retry/backoff, and a
day-level `days_missing()` gap scanner. Its chunk loop does not, however, distinguish "Dhan has no
data for this window" from "Dhan flaked and returned an empty 200 in the middle of a window that
otherwise has data." OpenAlgo's `data.py` resolves this by indexing non-empty chunks and treating
an empty chunk *between* two non-empty ones as a retryable server error, refusing to persist.

`pdp/instruments/loader.py` downloads and upserts the Dhan scrip master on demand; `snapshots.py`
exists but is not wired to any schedule. `broker_sync/scheduler.py` is the existing pattern for an
IST-time daily loop and is the reference for the scrip-refresh scheduler.

## Goals / Non-Goals

**Goals:**
- Detect a silent feed within `FEED_STALE_SECONDS` during market hours and self-heal (reconnect),
  emitting a `feed_stale` event other modules can consume.
- Never persist a backfilled day that has an interior empty chunk; retry, and on repeated failure
  leave the day untouched (visible to the next gap scan) rather than half-written.
- Refresh the scrip master once before the open, recording what changed (lot size, expiry, freeze).
- Make reconnection timing configurable instead of hardcoded.

**Non-Goals:**
- Replacing the Dhan SDK's own socket handling — the watchdog forces a reconnect through the
  existing path, it does not reimplement the transport.
- Auto-evicting or pausing strategies on stale feed — that decision belongs to the kill-switch in
  the `ops-safety-net` change; here we only emit the signal and reconnect.
- Parallelising the option backfill (it remains `max_workers=1` per the existing rate budget).

## Decisions

### D1 — Watchdog stamps freshest tick at the router, evaluates in the adapter
`TickRouter` updates a `last_tick_ts` monotonic stamp on every tick (cheap, hot-path-safe — one
assignment). A periodic watchdog task (1s tick) in/near `DhanTickerAdapter` reads it; if
`now − last_tick_ts > FEED_STALE_SECONDS` and we are inside market hours and the socket claims
connected, emit `feed_stale` and trigger the existing reconnect routine.

### D2 — Market-hours gate
Stale detection only runs Mon–Fri inside the trading session (reuse the existing IST/market-hours
helper used by `broker_sync`/risk). Outside hours a silent feed is expected and not flagged.

### D3 — Interior-gap = retry then refuse-to-persist
After fetching all chunks for a day, build `nonempty_idx`. If any empty chunk index falls strictly
between the first and last non-empty index, the day is flaky: retry the empty chunks up to N times;
if still interior-empty, **do not write the day** and log `backfill_interior_gap` so the next gap
scan re-attempts. A genuinely empty leading/trailing region (no data either side) is *not* a hole.

### D4 — Scrip refresh reuses the loader, records diffs
A gated daily task calls the existing loader, then diffs the new rows against current
`lot_size`/`expiry`/`freeze_qty` and writes changes through `snapshots.py`. Default off so it never
surprises an owner; turned on per environment.

### D5 — Settings, not constants
`FEED_RECONNECT_BASE_DELAY` / `FEED_RECONNECT_MAX_DELAY` replace the literals in `dhan_ws.py`.

## Failure Modes

- **Watchdog false positive in a genuinely quiet market** → mitigated by D2 (market-hours gate) and
  a conservative default `FEED_STALE_SECONDS`; cost is one reconnect, not a halt.
- **Repeated interior gaps** → day stays unwritten and keeps surfacing in the gap scan (visible,
  not silent) instead of a hidden hole.
- **Scrip refresh download failure** → logged, last-good master retained, retried next day; never
  blocks startup.
