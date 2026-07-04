---
name: data:coverage
description: Read-only per-index/per-family market-data coverage report — min/max date, gap ranges, coverage % for spot, options, VIX, Camarilla levels, and futures across NIFTY/BANKNIFTY/SENSEX. Complements /pdp:health. Use when the user wants to know what data exists or where the holes are before trusting a backtest.
metadata:
  author: pdp
  version: "1.0"
---

Report data coverage + gap radar across all configured underlyings and input families. This is
read-only — it never triggers a backfill (use `/data:gapfill` for that).

## Input

Optionally: a date window (`--from`/`--to`; default last 90 days) and/or a single underlying
(`NIFTY`/`BANKNIFTY`/`SENSEX`; default all three).

## Steps

1. **Fetch coverage**:

   ```
   curl -s "http://localhost:8000/api/v1/coverage?from=YYYY-MM-DD&to=YYYY-MM-DD"
   ```

   Add `&underlying=NIFTY` to scope to one index. Response shape:
   `{"window": {...}, "underlyings": {"NIFTY": {"families": {...}, "radar": {...}}, ...}}`.

   Families reported per underlying: `spot`, `options`, `vix`, `levels_daily`, `levels_weekly`,
   `futures`. Each has `min_date`, `max_date`, `covered_days`, `total_days`, `coverage_pct`,
   `gap_ranges`. `futures` will always show `status: "unavailable"` — no futures source is wired
   up yet; treat it as informational, not a real gap.

2. **Summarize per underlying**: a table of family → coverage % → gap ranges (collapse to the
   date ranges already returned, don't re-derive). Call out any family below 100% coverage in the
   requested window, and any family with `min_date`/`max_date` `null` (no data at all).

3. **Radar rollup**: from the `radar` map (per-date → per-family status), count how many trade
   dates in the window have at least one family reporting anything other than `"ready"`. List the
   distinct missing-family labels seen (e.g. "spot/VWAP missing", "weekly Camarilla missing", "VIX
   missing") with their occurrence counts — this is the language `strangle-review`/backtest
   decision traces already use for `cam_weekly missing` / `pcr None`.

## Output Format

```
Data Coverage — <from> .. <to>
================================
NIFTY
  spot          100.0%  2021-06-01 .. 2026-07-04
  options        98.2%  2021-06-01 .. 2026-07-04   gaps: 2024-08-12, 2024-09-03..2024-09-05
  vix           100.0%  2021-08-01 .. 2026-07-04
  levels_daily  100.0%  2021-06-30 .. 2026-07-04
  levels_weekly 100.0%  2021-06-30 .. 2026-07-04
  futures         0.0%  unavailable (no source ingested)

BANKNIFTY
  ...

Radar: 3 trade-dates with a missing family in this window
  - "options missing": 2024-08-12, 2024-09-03..2024-09-05 (NIFTY)
```

End with: overall verdict (clean / N gaps found), and — if any family is below 100% — suggest
`/data:gapfill` to close it.
