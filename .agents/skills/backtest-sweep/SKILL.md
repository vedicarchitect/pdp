---
name: backtest:sweep
description: Launch a directional-strangle parameter sweep (grid over StrangleConfig fields) and summarize the persisted leaderboard and best_param once it completes. Use when the user wants to tune params rather than run a single config.
metadata:
  author: pdp
  version: "1.0"
---

Launch a real in-process grid sweep and report the ranked leaderboard.

## Input

Optionally specify after `/backtest:sweep`:
- a base config file/JSON
- a date window (`--from`/`--to`)
- a grid: `{field: [values]}` over `StrangleConfig` fields, e.g.
  `{"hedge_enabled": [true, false], "day_loss_limit": [10000, 15000]}`
- objective (`pf` default; `net`/`sharpe` also valid)

If the grid is empty or unclear, ask — a sweep with no grid is rejected server-side.

## Steps

1. **Launch the sweep job**:

   ```
   curl -s -X POST http://localhost:8000/api/v1/strangle-backtests/sweeps \
     -H "Content-Type: application/json" \
     -d '{"config": {...}, "date_from": "YYYY-MM-DD", "date_to": "YYYY-MM-DD",
          "grid": {...}, "objective": "pf"}'
   ```

   Returns `{"job_id": ..., "type": "sweep", "status": "PENDING"}`.

2. **Poll job progress**:

   ```
   curl -s http://localhost:8000/api/v1/jobs/<job_id>
   ```

   The sweep loads the market window once, then replays every grid combination in-process
   (`pdp/backtest/sweep_engine.py`) — progress messages report combo count as it goes.

3. **Fetch the leaderboard** once `status` is `SUCCEEDED` (the job result includes `sweep_id`):

   ```
   curl -s http://localhost:8000/api/v1/strangle-backtests/sweeps/<sweep_id>
   ```

4. **Summarize**: total combos run, the objective used, the top 5 ranked combos (rank, params,
   net, PF, win rate), and the `best_param` set. Call out any combo that's a clear standout vs
   the base config.

5. **Offer next action**: "Run `/backtest:run` with `best_param` merged into the base config to
   get the full per-day detail for the winning combo, or `/backtest:sweep` again with a narrower
   grid around it."
