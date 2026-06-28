---
name: strangle:review
description: Analyze today's directional strangle activity log and produce a structured trade-session review with decisions, P&L, anomalies, and suggestions. Use when the user wants to review the live strangle session after market hours or during the day.
metadata:
  author: pdp
  version: "1.0"
---

Analyze the directional strangle trading session and produce a structured review.

## Input

Optionally specify a date after `/strangle:review` (e.g., `/strangle:review 2026-06-28`).
If omitted, use today's IST date.

## Steps

1. **Locate the log file**

   The strategy daily log is at `backend/logs/directional_strangle/<YYYY-MM-DD>.log` (IST date).
   Each line is a JSON object (one event per line).

   If the file doesn't exist yet (chunk 6 not yet implemented), fall back to reading today's
   structlog output from `backend/logs/app.log` and filter for `strategy_id=directional_strangle`.

   Read the log file. If it is empty or missing, say so and stop.

2. **Parse events by type**

   Group lines by `event_type`. Expected types (after chunk 4):
   - `bias_evaluated` — score, bucket, votes per signal
   - `leg_status` — open legs with LTP/MTM at each 5m bar
   - `leg_open` — entry: side, strike, lots, entry_price, is_hedge, mode
   - `leg_close` — exit: reason, pnl
   - `take_profit` — TP close: entry_price, ltp, pnl
   - `stop_half` / `stop_all` — premium stop: entry, ltp, remaining_lots
   - `rolled` — rollup: old_strike, new_strike, old_ltp, new_ltp
   - `stop_gate_wait` — blocked re-entry: opt_type, n_below
   - `bucket_change` — regime shift: old_bucket → new_bucket
   - `day_loss_cap` — day halt
   - `square_off` — EOD close

3. **Produce the session review**

   Output the following sections:

   ### Session Summary
   - Date, underlying, mode (paper/live)
   - Opening bucket + score (first `bias_evaluated`)
   - Final bucket + score (last `bias_evaluated`)
   - Total bars evaluated (count of `bias_evaluated`)
   - Net day P&L (sum of `leg_close.pnl` + TP + stop events)
   - Trade count (entries), leg count (by side: PE shorts, CE shorts, hedges)

   ### Bias Timeline
   A compact table or list of bucket changes through the day:
   `HH:MM IST | bucket | score | trigger (bucket_change reason)`

   ### Per-Signal Vote Analysis
   From `bias_evaluated.votes`, show the average vote per signal across all bars.
   Flag signals that were consistently neutral (always 0 or always None) — those may
   indicate data gaps (e.g. cam_weekly missing, PCR unavailable).

   ### Trades
   For each `leg_open` → `leg_close` pair (matched by `security_id`):
   - Side, strike, entry price, exit price, exit reason, P&L, holding time

   ### Notable Events
   - Any `rolled` events (rollup fired — good sign if premium decayed as expected)
   - Any `stop_gate_wait` events (stop-gate working)
   - Any `day_loss_cap` (halt triggered — investigate why)
   - Any `bucket_change` with direction reversal within the same hour

   ### Parity Check (if backtest available)
   If `backend/backtest/runs/<date>/` exists with a status log, compare the first and last
   bias `score` + `bucket` from live vs backtest for the same date. Flag any difference > 0.05.

   ### Suggestions
   Based on the session:
   - If PCR was always None: "Wire live PCR (task 4.3)"
   - If cam_weekly was always missing: "Weekly Camarilla not warmed (task 4.2)"
   - If no rollup in N days: "Consider reviewing roll_trigger_prem threshold"
   - If day halt fired: "Review day_loss_limit config (currently Rs X)"
   - If score stayed neutral all day: note it; may indicate flat market — expected

4. **Offer next action**

   End with: "Run `/strangle:review <date>` for a different date, or `/pdp:health` for
   infrastructure status."
