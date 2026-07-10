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

## Related
`[[live_supertrend_warmup_gap]]`, `[[fast_backtest_and_coverage]]`, `[[supertrend_coldstart_gap]]`.
Independent of the strangle sequence — this affects any strategy that restarts intraday.
Cleanup, if needed, folds into `bar-session-anchoring`'s rebuild.
