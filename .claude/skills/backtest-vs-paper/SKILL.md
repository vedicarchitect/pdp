---
name: backtest:vs-paper
description: Compare a warehoused backtest run against its live paper results for the same strategy_id + window — per-day P&L alignment, flag divergence, and drill into a minute-level decision diff root-caused via the gap radar + bias votes. Use when the user asks whether paper is tracking a backtest, or why it's diverging.
metadata:
  author: pdp
  version: "1.0"
---

Compare a backtest run against paper using the generic `backtest-paper-comparison` capability —
supersedes the retired, SuperTrend-only `backtest:compare` CLI.

## Input

A `run_id` after `/backtest:vs-paper`. Optionally a `date` (YYYY-MM-DD) to drill into a
minute-level decision diff for one day. Ask for `run_id` if missing — `/backtest:run` or the
warehouse `GET /runs` listing can supply one.

## Steps

1. **Fetch the per-day alignment** (backtest vs paper net P&L, aligned by date):

   ```
   curl -s "http://localhost:8000/api/v1/strangle-backtests/runs/<run_id>/vs-paper"
   ```

   Each row has `date`, `backtest_net`, `paper_net`, `divergence` (backtest − paper, `null` when
   either side has no data for that date), `diverges` (bool), and `cause` (a concrete gap-radar
   label when one exists, else `null`).

2. **If `paper_data_available` is `false`**, say so plainly — the strategy has no paper trades in
   this window yet (e.g. paper only just started, or the run predates paper going live). This is
   not an error; report the backtest series only.

3. **Summarize divergence**: call out the days with the largest `|divergence|`, and lead with
   their `cause` when set (e.g. "weekly Camarilla missing" — the live side didn't have an input
   the backtest had). Days with `cause: null` diverged for reasons the gap radar and bias votes
   don't explain — say so rather than guessing.

4. **If the user wants a specific day's minute-level detail**, fetch the decision diff:

   ```
   curl -s "http://localhost:8000/api/v1/strangle-backtests/runs/<run_id>/vs-paper?date=<date>&granularity=minute"
   ```

   Each minute row has `backtest`/`live` event lists (normalized onto the shared vocabulary:
   `bias | entry | scale_in | rollup | exit | reentry | stop_gate_wait`), `mismatch` (bool — the
   action sets differ), and `cause` (gap-radar label, else `vote missing: <signal>` when a bias
   vote is absent on one side, else `null`). Narrate mismatched minutes chronologically, e.g.:

   > 09:35 backtest saw `entry` (bucket `complete_bear`) but live only logged `bias` — no leg
   > opened. Cause: weekly Camarilla missing that day.

5. **Offer next action**: "Run `/backtest:vs-paper <run_id> <other_date>` for another day's
   minute detail, or `/backtest:explain <run_id> <date>` for the backtest's own why-entry/why-exit
   narrative, or `/data:coverage` to see the full gap picture behind a `cause`."
