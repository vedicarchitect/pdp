---
name: backtest:explain
description: Reconstruct the why-entry / why-exit narrative for a backtest run + date from the persisted backtest_decisions events (and, on request, the full per-minute replay). Use when the user asks why a backtest traded the way it did on a specific day.
metadata:
  author: pdp
  version: "1.0"
---

Explain a backtest day's decisions as a causal narrative, mirroring `/strangle:review` but for
a backtest run instead of the live session.

## Input

A `run_id` and a `date` (YYYY-MM-DD) after `/backtest:explain`. Both are required — ask if either
is missing.

## Steps

1. **Fetch the persisted decision events** (bounded, events-by-default):

   ```
   curl -s "http://localhost:8000/api/v1/strangle-backtests/runs/<run_id>/decisions?date=<date>"
   ```

   Each event has `event` (one of `st_flip | entry | scale_in | rollup | exit | reentry`),
   `sub_reason` (e.g. `premium_decay`, `tp`, `stop_all`, `cooloff_15m`, `momentum_add`), `action`,
   and a `snapshot` (score, bucket, votes, ST state, VIX, PCR, legs, P&L at that instant).

2. **Reconstruct the narrative** in chronological order, e.g.:

   > 09:35 ST flipped bearish (score −0.62 → complete_bear) → increased lots (scale_in) →
   > 09:40 entered 3 PE / 1 CE → 11:15 rolled up PE leg after premium decayed to ₹18 (trigger 20)
   > → 11:20 stop-gate 15m cool-off started on PE → 11:35 re-entered PE after cool-off cleared →
   > 15:10 square-off, day net ₹+4,200.

3. **If the user wants the every-minute detail** (not just decision points), fetch the on-demand
   full replay — this re-simulates the day deterministically from the run's pinned config/window,
   it is never pre-stored:

   ```
   curl -s "http://localhost:8000/api/v1/strangle-backtests/runs/<run_id>/decisions?date=<date>&full=true"
   ```

   Returns `status_log` (every-minute `BarStatus` lines) alongside the same `decisions`.

4. **If no decisions exist for that date**, check whether the run predates decision-trace
   instrumentation (legacy ingested runs won't have any) and say so — offer `full=true` replay as
   the only way to get any day-level detail for such a run, since it recomputes rather than reads
   stored events.

5. **Offer next action**: "Run `/backtest:explain <run_id> <other_date>` for another day, or
   `/strangle:review <date>` to compare against the live session for the same date."
