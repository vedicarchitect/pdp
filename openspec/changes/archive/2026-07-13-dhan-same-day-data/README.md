# dhan-same-day-data — minimal context

Read only these. **Task 1 is an investigation and blocks the rest. Do not estimate this change yet.**

| File | Why |
|------|-----|
| `backend/pdp/indicators/warmup.py` | `_warm_one:140-167` (top-up trigger), `_fetch_from_dhan:342-390` (`to_date = today_ist`), `_persist_bars` |
| `backend/pdp/market/bar_writer.py` | The only other writer of `market_bars` |
| `openspec/changes/archive/2026-06-16-live-supertrend-session-warmup/` | Claims this ground; 10/10 tasks checked |
| `backend/pdp/mongo/collections.py` | `market_bars` is a timeseries collection — delete-then-insert only |

## Key facts established during investigation
- `_fetch_from_dhan:362` sets `to_date = today_ist`, so the request **asks** for today. What Dhan
  returns for an in-progress session is undocumented here and unasserted by any test.
- Three possible answers, each with a different fix: (a) today's completed candles come back —
  warmup is fine; (b) nothing for today — an intraday restart leaves a silent hole in the indicator
  input series; (c) today's candles come back **including a still-forming final candle** — which
  `_persist_bars` would write permanently into `market_bars`, poisoning every future warmup *and*
  every backtest that reads it. **(c) is the dangerous one: silent and persistent.**
- `warmup.py:359` derives the IST date as `datetime.now(UTC) + timedelta(hours=5, minutes=30)` — a
  fixed offset, not `ZoneInfo`. Correct today (IST has no DST) but it is the exact pattern behind the
  `broker-sync-visibility` snapshot-date bug. Do not propagate it.
- **Contradiction to resolve:** `live-supertrend-session-warmup` is archived with all tasks checked,
  yet memory `[[live_supertrend_warmup_gap]]` says it was never implemented. One of the two is wrong.

## Task 1.6 — contradiction RESOLVED (2026-07-12)
`live-supertrend-session-warmup` genuinely landed. Verified against current `warmup.py` +
`test_warmup.py`: `_prior_trading_day()` walks back over weekends/holidays, `required_bars()`/
`lookback_days()` replaced the fixed lookback with a full prior-session target, the Dhan fallback
range is widened to the computed prior trading day, `IndicatorEngine`'s persistent tracker is
unchanged — and all of that change's own tests are present and green. The memory's "NOT
implemented" note was written the day *before* the change was executed and never updated
afterward; it has been corrected in place (`memory/live_supertrend_warmup_gap.md`).

**The two changes don't overlap in scope.** `live-supertrend-session-warmup` guarantees warmup's
lookback reaches the prior *completed* trading session. It says nothing about whether Dhan serves
*today's own* in-progress-session candles — that's what this change (`dhan-same-day-data`)
investigates, and it remains open.

## Tasks 2 + 3 — IMPLEMENTED (2026-07-12), independent of the task-1 answer
- **Incomplete-candle guard** (tasks 2.1–2.4): `pdp/market/bars.py::bar_is_complete(bar_time,
  timeframe, now)` rejects any bar whose period (`bar_time + timeframe > now`) hasn't fully
  elapsed. Wired into `warmup.py::_fetch_from_dhan` (filters before the caller can persist or
  seed) and into the two other broker-fetch writers found by
  `grep -rn "_persist_bars\|market_bars" backend/pdp backend/scripts`: `scripts/backfill_spot.py`
  and `scripts/backfill_vix.py` (both default `--to date.today()`, so an `--only-missing` run
  during market hours would otherwise hit the exact same same-day question). 1D/1w treat the full
  calendar day/week as the period, not just session close — deliberately conservative given task
  1.4 (Dhan's daily-candle semantics for an in-progress day) is still unanswered. Tests:
  `test_fetch_from_dhan_drops_still_forming_final_candle`,
  `test_fetch_from_dhan_retains_completed_candles_after_close`,
  `test_fetch_from_dhan_mixed_batch_keeps_only_complete_bars` in `tests/indicators/test_warmup.py`.
- **Timezone fix** (tasks 3.1–3.2): `warmup.py`'s two `datetime.now(UTC) + timedelta(hours=5,
  minutes=30)` sites (`_prior_trading_day`, `_fetch_from_dhan`) now use
  `datetime.now(ZoneInfo("Asia/Kolkata"))` / `.astimezone(ZoneInfo(...))`. Boundary tests added at
  18:29/18:31 UTC on 2026-07-09 (rolls IST date from 07-09 to 07-10).
- **Task 3.3 — other fixed-offset sites, recorded as safe rather than mass-rewritten:**
  `grep -rn "hours=5, minutes=30" backend/pdp` finds ~18 more sites (`events/service.py`,
  `events/models.py`, `warehouse/coverage.py`, `strategy/trade_ledger.py`, `strategy/routes.py`,
  `options/gap_backfill.py`, `instruments/scheduler.py`, `backtest/*.py`, `broker_sync/scheduler.py`,
  `market/session_scheduler.py`, `indicators/levels_store.py`). All of them add/derive a fixed
  `+5:30` offset the same way `warmup.py` did. **This is safe, not merely "safe today":** India
  abolished DST in 1945 and has never reintroduced it, so `timedelta(hours=5, minutes=30)` and
  `ZoneInfo("Asia/Kolkata")` are bit-identical for every date this application will ever compute —
  past backtests, live data, or any future session. The `broker-sync-visibility` bug this pattern
  is compared to (`snapshot_date used the UTC date while the scheduler passed IST`) was actually an
  inconsistency bug (bare UTC used in one place, IST passed in another), not a fixed-offset-vs-DST
  bug — that failure mode doesn't apply here. `warmup.py`'s two sites were changed only for
  consistency with the established convention; the other 18 are left as fixed-offset arithmetic,
  recorded here as the task 3.3 audit rather than churned.

## Tasks 1.1–1.5 — RESOLVED (2026-07-13, live probe during market hours)

2026-07-13 is a trading day and Dhan credentials are valid — `scripts/oneoff/probe_dhan_same_day.py`
was run for real at 11:30:37 IST. **Answer: (c) for intraday, (b) for daily.**

**Intraday (`intraday_minute_data`, 5m, task 1.1/1.3):** Dhan returned 28 candles for today
(09:15–11:30 IST), and the *last* one — `bar_time_ist=11:30:00` — is a still-forming candle for the
11:30–11:35 bucket, captured only 37 seconds in. `bar_is_complete()` correctly flags it
`final_candle_complete: false`; its `volume=429,514` is roughly 10x lower than every neighboring
candle's volume (2.5M–11.5M), the same fingerprint the incomplete-candle guard (tasks 2.1–2.4) was
built to catch. **This confirms (c): today's candles come back including a still-forming final
one** — exactly the dangerous case tasks 2.1–2.4 already guard against, landed the day before this
was empirically confirmed.

**Daily (`historical_daily_data`, 1D, task 1.4):** `todays_candle_count=0` — Dhan returns nothing
for the current, in-progress trading day on the daily endpoint; the most recent candle in the
response is for an earlier date in the requested window. This is answer **(b) for the daily path
specifically** — there is no in-progress daily candle to accidentally persist, so the 1D/1w
"conservative full-period" branch of the incomplete-candle guard (task 2.4's note) is defense in
depth, not a live-confirmed necessity, but is correct to keep regardless.

**Task 1.2 (before/after diff):** not run — a single market-hours probe already gives an
unambiguous (c) determination (a partial candle with real, non-zero, anomalously-low-volume OHLC
was returned; there is nothing a post-close diff would change about that conclusion for the
already-answered a/b/c question). Anyone wanting the literal before/after diff can still run:
```
uv run python scripts/oneoff/probe_dhan_same_day.py --out probe_1100.json   # done, see below
uv run python scripts/oneoff/probe_dhan_same_day.py --out probe_1600.json   # after 15:30 IST close
```
Full JSON of the 11:30 probe reviewed inline (not committed — read-only reconnaissance output).

## Task group 4 — audit for existing corruption (since the answer is (c))

The incomplete-candle guard (tasks 2.1–2.4) landed *before* this live confirmation, so any warmup
Dhan-fallback fetch since that guard shipped was already protected. The audit question is whether
any partial candle was persisted to `market_bars` **before** the guard existed (i.e., from an
intraday-restart warmup fetch prior to 2026-07-12).

**Deferred, not run.** A reliable query needs a volume-anomaly heuristic scoped per `(security_id,
timeframe, time-of-day)` — the `high==low==open==close` heuristic from task 4.1's original wording
does not catch this failure mode (the 2026-07-13 probe's partial candle has real, distinct OHLC
values; only its volume is anomalous, and "anomalous" is only meaningful relative to the
time-of-day's typical volume, which needs a baseline computed from the surrounding data rather than
a fixed threshold). Building and running that query against the live `market_bars` collection
during market hours carries the same caution as `market-bars-duplicate-write-fix` task 3 (a
currently-being-written-to production collection) for a comparatively low-probability, bounded-blast
window (only intraday-restart fetches before 2026-07-12, on 5m/15m/30m/1H series only). Recommend
running this audit off-hours if it's prioritized; not blocking on it here.

Task groups 5 (answer-(b) fix) and 6 (answer-(a) verify) do not apply — the daily path's (b) needs
no fix (nothing to accidentally persist), and the intraday path's (c) fix already shipped.

## Related
`[[live_supertrend_warmup_gap]]`, `[[fast_backtest_and_coverage]]`, `[[supertrend_coldstart_gap]]`.
Independent of the strangle sequence — this affects any strategy that restarts intraday.
Cleanup, if needed, folds into `bar-session-anchoring`'s rebuild.
