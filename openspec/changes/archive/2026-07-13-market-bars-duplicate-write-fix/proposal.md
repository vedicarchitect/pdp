## Why

`market_bars` has been silently accumulating duplicate documents for the same
`(ts, metadata.security_id, metadata.timeframe)` tuple. Discovered as a byproduct of the
`bar-session-anchoring` rebuild (2026-07-11): diffing NIFTY's (`security_id="13"`) pre-rebuild `1H`
bars for 2026-06-29 against the corrected rebuild showed 25 stored documents where only 12 correctly
anchored buckets exist — 5 of the 7 intraday buckets had an exact duplicate (identical `ts` **and**
identical OHLC), e.g. two `03:45:00` documents with `open=24061.75, high=24110.75, low=24005.45,
close=24061.8`. This wasn't isolated: 259 of the 1,257 `(security_id, timeframe)` pairs touched by
the rebuild had `existing_count > new_count`, consistent with the same duplication pattern.

The structural gap: `market_bars` is a MongoDB **time-series** collection
(`pdp/mongo/collections.py:_ensure_market_bars`), and time-series collections cannot carry a unique
index — confirmed by the comment already on `option_bars`' index setup one function below it
("Mongo time-series collections cannot carry a unique index, and we need DB-enforced dedup..."),
which is precisely why `option_bars` was built as a **regular** collection with a
`uq_contract_ts` unique index instead. `market_bars` never got the equivalent treatment: `BarWriter._flush`
(`pdp/market/bar_writer.py:73`) calls `insert_many(batch, ordered=False)` with no existence check and
no DB constraint to reject a re-write of an already-stored bucket.

Worth noting: `openspec/specs/market-bars/spec.md`'s "Duplicate bar silently skipped" scenario
describes `insert_many` skipping a document whose `(ts, metadata)` already exists — that behavior
requires a unique index, which is impossible here. The scenario currently describes intended
behavior that the storage layer cannot actually provide.

## What Changes

- Investigate how a `BarClosed` event (or the resulting write) for the same `(security_id,
  timeframe, bar_time)` bucket happens more than once. Candidate mechanisms to check first: engine
  process restart re-aggregating a tick window already flushed (this repo has a documented history
  of overlapping/duplicate engine processes — see `task_dev_reload_conflict` — and of the feed
  engine group dying and restarting silently — see `dead_command_channel_import`); interaction
  between the new `BarSessionScheduler.flush_session()` (added earlier in `bar-session-anchoring`)
  and a subsequent regular boundary-crossing close of the same bucket.
- Make duplicate writes to `market_bars` structurally impossible (or, if a true unique index remains
  infeasible on a time-series collection, add an application-level existence check or idempotency
  key before `insert_many`, or move to a delete-then-insert-per-bucket write path — same technique
  `rebuild_market_bars.py` already uses for corrections).
- Add a regression test that reproduces the duplicate-write path (whatever it turns out to be) and
  asserts it no longer produces a second document for the same bucket.
- Correct `openspec/specs/market-bars/spec.md`'s "Duplicate bar silently skipped" scenario to match
  whatever dedup mechanism is actually implemented (it cannot be a DB-level unique index skip on a
  time-series collection).
- Fix `backend/pdp/market/CLAUDE.md`'s stale `market_bars` schema doc, which currently claims a flat
  (non-`metadata`-nested) schema **and** a unique index that does not exist — both wrong, and the
  unique-index claim is part of what let this go unnoticed.
- One-off cleanup: audit `market_bars` for existing duplicate `(ts, metadata)` tuples outside the
  `bar-session-anchoring` rebuild's date range (2026-04-08 to 2026-07-11) and dedupe them.

## Capabilities

### Modified Capabilities
- `market-bars`: the "Duplicate bar silently skipped" requirement/scenario changes from a DB-level
  unique-index claim to whatever dedup mechanism is actually implemented (app-level check, or
  delete-then-insert per bucket).

## Impact

- `pdp/market/bar_writer.py` (write path)
- `pdp/market/bars.py` / `pdp/market/session_scheduler.py` (possible duplicate `BarClosed` emission)
- `pdp/mongo/collections.py` (index/collection definition)
- `openspec/specs/market-bars/spec.md`, `backend/pdp/market/CLAUDE.md` (docs)
- `market_bars` collection data (one-off dedup cleanup)
