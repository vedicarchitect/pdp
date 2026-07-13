# dhan-same-day-data

## Why

When the backend restarts mid-session — which, before `dev-reload-scoping`, happened several times a
day — the indicator engine must reconstruct the current session's bars. It does this by warming up
from Mongo `market_bars` and topping up from Dhan. Whether that top-up actually includes **today's**
candles has never been verified, and nothing in the test suite covers it.

`_fetch_from_dhan` (`backend/pdp/indicators/warmup.py:342`) builds its window as:

```python
today_ist = (datetime.now(UTC) + timedelta(hours=5, minutes=30)).date()   # :359
from_d = prior_day if prior_day is not None else today_ist - timedelta(days=1)  # :360
from_date = from_d.strftime("%Y-%m-%d")   # :361
to_date = today_ist.strftime("%Y-%m-%d")  # :362
```

So the request *asks* for data up to and including today. What Dhan returns for an in-progress
session is undocumented in this repository and unasserted anywhere. There are three possibilities and
we do not currently know which is true:

1. Dhan returns completed candles for today up to the request time. Warmup is correct; the restart
   hole closes itself.
2. Dhan returns nothing for today (a common broker-API behaviour — historical endpoints often serve
   only settled sessions). Then a restart at 11:00 IST leaves `market_bars` missing every bar from
   the last successful `BarWriter` flush to the restart, and the indicator engine resumes with a
   silent gap in its input series. EMA and SuperTrend continue from stale state; the values are wrong
   in a way no assertion catches.
3. Dhan returns today's candles but including an incomplete, still-forming final candle. Seeding an
   indicator with a partial bar corrupts it — and `_persist_bars` would write that partial bar into
   `market_bars`, where it becomes permanent, poisoning every future warmup and backtest that reads
   the collection.

Case 3 is the dangerous one, because it is silent and it persists. `market_bars` is the shared
substrate for warmup, backtests and the console.

The related concern is the boundary itself. `_fetch_from_dhan` computes `today_ist` from
`datetime.now(UTC) + timedelta(hours=5, minutes=30)` — a fixed offset rather than
`ZoneInfo("Asia/Kolkata")`. That happens to be correct for IST, which has no DST, but it is the same
pattern that produced the UTC/IST snapshot-date bug fixed in `broker-sync-visibility`, and it should
not be copied further.

This change is an **investigation with a defined outcome**, not a predetermined fix. The first task
is to find out what Dhan actually returns; the remaining tasks branch on the answer. It is held apart
from the data-correctness sequence because its scope cannot be fixed until that question is answered.

## What Changes

- **Establish the ground truth.** A one-off script calls `intraday_minute_data` and
  `historical_daily_data` for NIFTY during market hours and after close, and records exactly which
  candles come back for the current day, including whether the final candle is complete. The result is
  written into this change's README as the basis for everything else.

- **Never persist an incomplete candle.** Regardless of the answer, `_persist_bars` rejects any bar
  whose `bar_time + timeframe > now`, and warmup discards it rather than seeding an indicator with
  it. This is correct under all three possibilities and is the one fix that can be written before the
  investigation completes.

- **Close the restart hole explicitly.** If Dhan does not serve the current session (case 2), warmup
  reconstructs today's bars from a source that does: the 1-minute series already persisted by
  `BarWriter` up to the crash, plus a replay of the tick cache. If it cannot reconstruct a complete
  series, it reports the gap as a `blocked` readiness component (see `strangle-observability-gaps`)
  rather than starting the strategy on a holed series.

- **Assert the session boundary.** Replace the fixed `+5:30` offset at `:359` with
  `ZoneInfo("Asia/Kolkata")`, matching the convention `broker-sync-visibility` established, and test
  the boundary at 18:29 and 18:31 UTC.

## Impact

- **Affected specs:** `dhan-same-day-data` (new). Amends `openspec/specs/indicator-warmup.md` and
  `openspec/specs/market-data-coverage/spec.md`.
- **Affected code:** `backend/pdp/indicators/warmup.py` (`_fetch_from_dhan:342-390`,
  `_persist_bars`, `_warm_one` around `:140-167`), possibly `backend/pdp/market/bar_writer.py`,
  new `backend/scripts/oneoff/probe_dhan_same_day.py`.
- **Scope is genuinely unknown until task 1 completes.** If Dhan serves today's completed candles,
  this change shrinks to the incomplete-candle guard and the timezone fix — perhaps a day's work. If
  it does not, closing the restart hole is a real piece of engineering. Do not commit to an estimate
  before probing.
- **Possible existing corruption.** If case 3 holds, `market_bars` may already contain partial
  candles from every historical warmup that ran during market hours. Audit for bars whose
  `high == low == open == close` or whose volume is anomalously low for their timeframe, and fold the
  cleanup into `bar-session-anchoring`'s rebuild, which already rewrites 15m/30m/1H from the 1m series.
- **`live-supertrend-session-warmup` (archived 2026-06-16) claims this ground.** All ten of its tasks
  are checked. Either it solved the restart hole and the memory
  `[[live_supertrend_warmup_gap]]` calling it "NOT implemented" is stale, or it was archived without
  landing. **Resolve that contradiction in task 1** — do not build on top of an unverified
  assumption in either direction.
- Runs independently of the strangle sequence. It affects any strategy that restarts intraday, not
  just the strangle. Ties into [[live_supertrend_warmup_gap]], [[fast_backtest_and_coverage]].
