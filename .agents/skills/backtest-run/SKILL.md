---
name: backtest:run
description: Launch a single directional-strangle backtest (strategy config + date window + index) as an async job, then summarize the resulting metrics and verdict. Use when the user wants to run one backtest and see how it performed.
metadata:
  author: pdp
  version: "1.0"
---

Launch a single backtest run against the Mongo-backed backtest warehouse and report the result.

## Input

Optionally specify after `/backtest:run`:
- a config file path (e.g. `backtest/configs/strangle_nifty_hedged.yaml`) or inline JSON config
- `--from YYYY-MM-DD --to YYYY-MM-DD` (or a day count)
- underlying (NIFTY/BANKNIFTY/SENSEX — from the config's `underlying` field)

If any of config/window is missing, ask the user rather than guessing dates or a strategy.

## Steps

1. **Prefer the API job path** (DB-first, non-blocking, progress-tracked):

   ```
   curl -s -X POST http://localhost:8000/api/v1/strangle-backtests/runs \
     -H "Content-Type: application/json" \
     -d '{"config": {...}, "date_from": "YYYY-MM-DD", "date_to": "YYYY-MM-DD"}'
   ```

   This returns `{"job_id": ..., "type": "single", "status": "PENDING"}`. Poll:

   ```
   curl -s http://localhost:8000/api/v1/jobs/<job_id>
   ```

   until `status` is `SUCCEEDED` or `FAILED`. Mongo persistence is DB-first by default — no
   `out_dir` is needed unless the user explicitly wants a local artifact archive too.

2. **If the API isn't running**, fall back to the CLI directly (also DB-first by default):

   ```
   cd backend && uv run python backtest/strangle_run.py \
     --config-file <path> --from <date> --to <date>
   ```

   Add `--no-mongo` only if the user explicitly wants a console-only run with no persistence.

3. **Fetch the persisted run** once complete:

   ```
   curl -s http://localhost:8000/api/v1/strangle-backtests/runs/<run_id>
   ```

   (`run_id` is `strangle_<YYYYMMDD-HHMMSS>` — printed by the CLI, or in the job result.)

4. **Summarize**: net P&L, profit factor, win rate, max drawdown, trade count, halted-day count,
   `verdict` if this was a walk-forward run. Note the window and underlying traded.

5. **Offer next action**: "Run `/backtest:sweep` to tune params, `/backtest:explain <run_id> <date>`
   to see why a specific day traded the way it did, or `/backtest:promote <run_id>` if this is a
   PASS walk-forward run."
