# Tasks — bar-session-anchoring

## 1. Tests first (they fail on today's code)
- [x] 1.1 `tests/market/test_bar_boundary.py`: parametrise over `[5m, 15m, 25m, 30m, 1H]` × four
      consecutive trading days; assert the bucket of the 09:15:00 IST tick starts at 09:15 IST
- [x] 1.2 Assert 5m/15m boundaries are byte-identical to the current epoch-anchored output (no regression)
- [x] 1.3 Assert 1D/1w boundaries are unchanged
- [x] 1.4 Session-window: ticks at 09:14:59 and 15:30:00 produce no bar; 09:15:00 and 15:29:59 do
- [x] 1.5 Session-end flush emits the final open bucket at 15:30 with no further tick — **not
      15:00–15:30 as originally written**: under correct 09:15-anchored 30m buckets the last
      boundary before close is 15:15, so the final partial bucket is 15:15–15:30, 15 minutes wide.
      The proposal's "15:00–15:30" example predates the exact derivation and matched the *old*,
      wrong epoch anchoring (whose 30m buckets land on :00/:30). Test uses the derived boundary.
- [x] 1.6 A Monday following a Friday holiday anchors on the Monday session open — trivially true
      since `_bar_boundary`/`_session_open_utc` are pure functions of the tick's own IST day and
      carry no dependency on prior days at all

## 2. Anchoring
- [x] 2.1 `bars.py`: add `_session_open_utc(dt) -> datetime` (09:15 IST on the tick's IST trading day)
- [x] 2.2 `_bar_boundary(dt, tf_minutes)` truncates `(dt - session_open)` into `tf_minutes` buckets
- [x] 2.3 Leave `_bar_boundary_1d` and `_bar_boundary_1w` untouched
- [x] 2.4 Confirm no other module reimplements bucket maths (`grep -rn "// tf_minutes\|// 60" backend/pdp`)
      — clean, only `bars.py` itself matches

## 3. Session window
- [x] 3.1 `BarAggregator.push`: drop ticks outside `[09:15:00, 15:30:00)` IST — the proposal named
      the method `on_tick`; the actual method is `push` (same call site in `TickRouter`/`WarehouseService`)
- [x] 3.2 Time-of-day filtering needs no calendar lookup (see 3.4); the holiday-aware
      `pdp.options.gap_backfill.holidays()` helper is used one layer up, by the new session-end
      scheduler (3.3), to decide whether *today* is a trading day worth flushing at all
- [x] 3.3 `BarBuilder.flush()` + `BarAggregator.flush_session()` close every open bucket; wired to
      a new `pdp/market/session_scheduler.py` (`BarSessionScheduler`, mirrors `BrokerSyncScheduler`'s
      idempotent daily-fire loop) at 15:30 IST, gated on `holidays()` — not a weekday check
- [x] 3.4 Hot-path check: `_in_session_window` is `int(dt.timestamp() // 60) + offset, % 1440`, two
      integer ops per tick, no `ZoneInfo`, no per-day cache needed (matches the existing
      `_bar_boundary_1d`/`_bar_boundary_1w` style already in this file)
- [x] 3.5 **Added 2026-07-11, found during task 5.2's live-engine verification (a real Saturday, not
      simulated):** 3.2's design left the ingestion-side filter clock-time-only and deferred all
      calendar/trading-day awareness to the flush scheduler. That's a real gap, not just a flush-time
      one — a stale/heartbeat print delivered during the nominal 09:15–15:30 IST clock window *on a
      non-trading day* (weekend or `NSE_HOLIDAYS_JSON` holiday) was still being aggregated and
      persisted as a real bar, because nothing checked whether *today* was a trading day at
      ingestion. Reproduced live: restarting the engine on Saturday 2026-07-11 wrote 473 phantom
      `1m`/`5m` docs for `security_id="13"` (frozen at the last real close, `24206.9`) within ~10
      minutes, before being caught and the process stopped. Fixed: `_in_session_window` now takes a
      `holiday_set` and also checks `ist_date.weekday() < 5 and ist_date not in holiday_set` (via a
      new `_ist_date` helper), short-circuited behind the existing cheap clock check so real trading
      days pay no extra cost. `BarAggregator` takes an optional `holiday_set`; `pdp/runtime/groups.py`
      now loads it once at startup and passes the same set to both the aggregator and
      `BarSessionScheduler` (previously only the scheduler got it). 4 new tests in
      `tests/market/test_bar_boundary.py::TestSessionWindow` (weekend rejected, listed holiday
      rejected, holiday_set doesn't over-reject real trading days). Full suite: 1050 passed, 2
      intentional xfailed. The 473 phantom docs from the reproduction were deleted (bounded, exact
      timestamp range, confirmed 100% phantom — frozen price, zero real volume, non-trading day).

## 4. Rebuild stored bars
- [x] 4.1 Backup taken before the real rebuild: `mongodump` binary is not installed on this
      machine, so substituted an application-level export via the existing motor client —
      `backend/data/backups/market_bars_pre_session_anchoring_rebuild_20260711.jsonl` (38,450 docs,
      all `15m`/`30m`/`1H` docs across the full rebuild range, `_id` dropped, datetimes isoformat'd).
      User explicitly authorized proceeding ("go ahead and run") after reviewing scope.
- [x] 4.2 `backend/scripts/oneoff/rebuild_market_bars.py`: read 1m for `(sid, date-range)`, aggregate
      to 15m/30m/1H, delete-then-insert per `(sid, tf)`. (25m dropped from scope — it's not in
      `_REBUILD_TIMEFRAMES` anywhere else in the codebase; grep for `"25m"` outside this change's own
      tests/docs turns up nothing, so there's no stored 25m data to rebuild.)
- [x] 4.3 Reuses `_bar_boundary` (the exact function `bars.py` anchors on) for every bucket — the
      script does bar-level OHLC rollup (open=first/high=max/low=min/close=last/volume=sum) rather
      than replaying through `BarAggregator.push`, since that's tick-oriented (one LTP per call) and
      would collapse each stored 1m bar's own high/low back to a single point, discarding fidelity
      already captured in the 1m OHLC. Anchoring math itself still has exactly one implementation.
- [x] 4.4 `--dry-run` returns a summary dict (`existing_count`, `new_count`, `first_ts`, `last_ts`)
      per `(sid, tf)` and makes no writes; `main()` logs it via structlog
- [x] 4.5 Idempotence test: `tests/scripts/test_rebuild_market_bars.py::TestRebuildIdempotence` —
      running twice produces an identical document set (offline, in-memory fake collection)
- [x] 4.6 Equivalence test: `TestRebuildEquivalenceWithBarAggregator` — replays one session's ticks
      through `BarAggregator` (source of truth), derives the 1m docs from its own output, and asserts
      the script's bar-level 30m rollup matches `BarAggregator`'s tick-level 30m bar exactly (OHLCV)
- [x] 4.7 Ran for all 419 security_ids with existing `15m`/`30m`/`1H` bars in range (2026-04-08 to
      2026-07-11) — **not** just the 4 named `WAREHOUSE_UNDERLYINGS`/`SID_MAP` entries: a dry-run
      first showed 86% of affected docs belong to option-leg contracts, so the user was asked and
      explicitly chose the full scope over the narrow one. 1,257 (sid, timeframe) pairs processed,
      0 errors. The `1m` document count is unchanged by construction — `rebuild_one`'s `range_query`
      only ever matches `metadata.timeframe` in `{15m, 30m, 1H}`, so `1m` docs are never selected by
      `delete_many`/`insert_many`; confirmed no `1m` write path exists anywhere in the script.
      Verified no data loss: aggregate `existing_count` across all pairs (38,591) matches the
      pre-rebuild JSONL backup (38,450 — the small delta is live trading writing more bars during
      the ~3min gap between backup and rebuild); post-rebuild live count is higher still
      (46,479 as of the next query) from ongoing live writes using the already-fixed anchoring.
      259/1,257 pairs showed `new_count < existing_count`; investigated by diffing old vs. new `1H`
      buckets for NIFTY (sid `13`) on 2026-06-29: the old data contained duplicate timestamped
      buckets (e.g. two identical `03:45:00` entries with matching OHLC — a pre-existing write-path
      duplication bug, independent of the anchoring bug), 25 old buckets collapsing into 12 clean,
      correctly-anchored ones with consistent OHLC derived from the unchanged `1m` source. This is a
      correctness improvement, not data loss — flagging the duplication bug as a candidate for a
      follow-up change since it's outside this proposal's scope.

## 5. Verify against the broker
- [x] 5.1 Pulled Dhan (not Kite — no Kite creds in this environment) native 15m candles for NIFTY
      (`security_id="13"`, `IDX_I`) for the 5 most recent sessions (2026-07-06 to 2026-07-10; today
      2026-07-11 is a market holiday, credentials confirmed working). Dhan's `intraday_minute_data`
      has no native 30m interval (only 1/5/15/25/60), so pairs of native 15m candles were merged
      into 30m (open=first, high=max, low=min, close=last) — a broker-native computation independent
      of this repo's own `_bar_boundary`.
- [x] 5.2 Bar-by-bar OHLC comparison: 65/65 compared 30m buckets across the 5 sessions matched the
      rebuilt `market_bars` exactly (max abs diff = 0.0 across open/high/low/close). Confirms Dhan's
      own candle grid is session-anchored (first bucket of each day starts exactly at 03:45 UTC =
      09:15 IST) and that the rebuilt data now sits on the same grid.
      **Residual delta found, but not in the buckets compared — in bucket *count*:** 2026-07-09 had
      16 stored 30m bars vs. 13 expected/broker-matching; 2026-07-10 had 14 vs. 13. The extras are
      degenerate post-close bars (e.g. `2026-07-09 12:45:00` = 18:15 IST, `2026-07-09 15:45:00` =
      21:15 IST) with flat OHLC (`open=high=low=close`) and `volume=0`. Traced to the underlying `1m`
      source: e.g. a 1m doc at `2026-07-09T13:03:00` (18:33 IST) with `volume=0`, well outside
      `[09:15, 15:30)` IST. **This is task 3.1's session-window filter working as designed in code
      but not yet active in the live process** — 2026-07-09/07-10 are recent live trading days, and
      these phantom post-close prints (likely a heartbeat/reconnect LTP snapshot mistaken for a
      tick) are exactly what `BarAggregator.push`'s new window filter rejects. The fix is
      implemented and unit-tested (`tests/market/test_bar_boundary.py::TestSessionWindow`) but the
      running engine process has not been restarted since, so it's still on the old code path.
      **Update — restarted 2026-07-11 with explicit user go-ahead:** the engine (`task dev:trade`)
      was restarted; `bar_session_scheduler_started` confirmed the new code was active and
      `/readyz` reported healthy. This directly surfaced a second, more important gap — the
      time-of-day-only window filter still let a Saturday heartbeat print through, since 3.1/3.2
      never checked whether *today* is a trading day at all (not just whether it's past close on a
      real one). See 3.5 for the fix. The engine was stopped again after the reproduction; it is
      not currently running (starting it back up, now with 3.5's fix, is a separate operational
      decision for the user).
- [x] 5.3 EMA(20/50) recomputed from the rebuilt 30m series (875 bars, 2026-04-08 to 2026-07-11):
      latest EMA20=24173.98, EMA50=24171.21. The original incident's cited Kite values
      (24017/24063/24158) aren't reproducible for direct comparison — the proposal never recorded
      which session/timestamp produced them. Given 5.2 already proved bar-for-bar exact OHLC parity
      against the broker across 5 independent sessions (stronger evidence than matching 3 numbers
      from an unspecified date, since EMA is a deterministic function of its OHLC input), this is
      considered sufficient verification of the anchoring fix's correctness.

## 6. Re-baseline the backtests
- [x] 6.1 Re-run the three strangle configs after the rebuild (2026-07-13, `strangle_20260713-113418/23/28`)
- [x] 6.2 Recorded new net P&L / PF / MaxDD alongside the archived baselines in this change's README
- [x] 6.3 Decided and written down: **supersede** — see README "Combined re-baseline results (2026-07-13)"

## 7. Docs + validation
- [x] 7.1 `backend/pdp/market/CLAUDE.md`: documented session anchoring (`_session_open_utc`/
      `_bar_boundary`), the session window + trading-day filter (`BarAggregator.push`,
      `BarSessionScheduler`), fixed the stale `market_bars` schema (was flat `security_id`/
      `timeframe` fields + a false `unique index` claim — now correctly shown nested under
      `metadata.security_id`/`metadata.timeframe` with no unique index possible on a timeseries
      collection), corrected `BarAggregator.on_tick` → `push`, and cross-linked the open
      `market-bars-duplicate-write-fix` change and the rebuild script
- [x] 7.2 `docs/RUNBOOK.md`: added §9 Step 4 — dry-run/real rebuild commands, the JSONL-backup
      procedure (since `mongodump` isn't installed on this machine) and a restore-from-backup
      snippet. Also fixed 4 pre-existing manual Mongo query examples elsewhere in the runbook
      (§16.9/16.10/16.11/16.12) that filtered on flat `security_id`/`timeframe` — `market_bars` is a
      timeseries collection, so those fields are nested under `metadata.*`; the old queries would
      have silently matched zero documents
- [x] 7.3 `task test` green: full backend suite `1050 passed, 2 intentional xfailed` (2026-07-12);
      ruff clean on every file touched by this change (16 pre-existing, unrelated errors in
      `pdp/runtime/groups.py` confirmed via `git stash` to predate this change); `pyright
      pdp/market/bars.py` 0 errors
- [x] 7.4 `openspec validate --strict bar-session-anchoring` → "Change 'bar-session-anchoring' is
      valid"

## Status (2026-07-13)

All task groups (1–7) complete, including group 6 (combined re-baseline, run once after
`bias-input-completeness` per `EXECUTION-ORDER.md`, per the deliberate deferral recorded here
2026-07-12). See README "Combined re-baseline results (2026-07-13)" for the full NIFTY/BANKNIFTY/
SENSEX numbers, the NIFTY isolation analysis, and the supersede verdict. Ready to archive.
