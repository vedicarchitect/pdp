---
name: data:gapfill
description: Read the coverage/gap-radar API, list gaps for an underlying, trigger the matching one-click housekeeping backfill job, watch it over /ws/jobs, then re-check coverage until the gap is closed. Use when the user wants to fix a data gap found by /data:coverage rather than just see it reported.
metadata:
  author: pdp
  version: "1.0"
---

Close a market-data gap end-to-end: radar → backfill job → verify.

## Input

An underlying (`NIFTY`/`BANKNIFTY`/`SENSEX`) and optionally a family (`spot`/`options`/`vix`/
`levels`). If no family is given, run `/data:coverage` first and ask which gap to fill (or fill
every non-`futures` family below 100% for that underlying).

## Family → housekeeping task map

| Family (coverage response) | Task name          | Notes |
|-----------------------------|--------------------|-------|
| `spot`                       | `backfill-spot`     | run before `options`/`levels` — they derive from spot |
| `options`                    | `backfill-options`  | |
| `vix`                         | `backfill-vix`      | single global series, not per-underlying |
| `levels_daily` / `levels_weekly` | `backfill-levels` | one task backfills both periods |
| `futures`                    | — no task; report as unavailable, do not attempt |

## Steps

1. **Read current coverage** for the underlying to find the gap window:

   ```
   curl -s "http://localhost:8000/api/v1/coverage?underlying=NIFTY"
   ```

   Note the family's `gap_ranges` — that is the window to delta-fill (use its earliest date as
   `from`; leave `to` unset so the job fills through today).

2. **Trigger the one-click backfill** — delta semantics (`only_missing: true`, filled to today):

   ```
   curl -s -X POST http://localhost:8000/api/v1/housekeeping/<task> \
     -H "Content-Type: application/json" \
     -d '{"symbol": "NIFTY", "from": "<earliest gap date>", "only_missing": true}'
   ```

   `symbol` is ignored by `backfill-vix` (VIX has no per-underlying variant). Returns
   `{"job_id": ..., "status": ...}`.

3. **Watch progress** over the jobs WebSocket (`/ws/jobs`) if the harness can attach to it;
   otherwise poll:

   ```
   curl -s http://localhost:8000/api/v1/jobs/<job_id>
   ```

   Report status transitions (PENDING → RUNNING → SUCCEEDED/FAILED) and the tail of `log_tail`
   from the result once it finishes. If it fails, show the last few log lines — don't retry
   silently.

4. **Re-check coverage** for the same underlying/family once the job succeeds:

   ```
   curl -s "http://localhost:8000/api/v1/coverage?underlying=NIFTY"
   ```

   Confirm `gap_ranges` for that family is now empty (or smaller than before). If a gap remains
   (e.g. Dhan doesn't serve that historical range), say so plainly rather than declaring success.

5. **If multiple families were requested**, run spot first (other families derive from it), then
   options/levels/vix in any order, summarizing each before moving to the next.

## Output Format

```
Gap-fill: NIFTY options
=======================
Gap before: 2024-08-12, 2024-09-03..2024-09-05 (2 gap days)
Job housekeeping:backfill-options submitted (job_id=...)
  PENDING → RUNNING → SUCCEEDED (12s)
Gap after: none — closed
```

End with a one-line summary per (underlying, family) attempted: closed / partially closed /
unchanged (with reason).
