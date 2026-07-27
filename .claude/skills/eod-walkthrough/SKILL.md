---
name: eod:walkthrough
description: Generate the per-day strategy walkthrough for a trading date — one markdown file per day in backend/backtest/manual/ with per-minute indicators, spot, orders, decisions and a ranked FINDINGS list — then summarise what needs fixing. Use when the user wants the end-of-day report, asks to walk through a specific date (today or any past date), or wants to work through the findings one at a time.
metadata:
  author: pdp
  version: "1.0"
---

Replay every strategy over one trading day and write a single self-contained report, then
tell the user what it found. This is the daily loop for hunting real bugs: read the
findings, fix one, re-run the same date, confirm it cleared. The reports are committed
(`backend/backtest/manual/` is not git-ignored), so the before/after diff is the evidence.

## Input

An optional date after `/eod:walkthrough`:

- **nothing** — today (the EOD case)
- **a date** — `2024-03-14`, any past trading day
- **a range** — `2026-07-21..2026-07-24`, one file per day
- optionally an underlying — `2024-03-14 BANKNIFTY` (default NIFTY)

Nothing is required. Do **not** ask for a date — no argument means today.

## Steps

1. **Run the generator** for the requested date. Only the no-argument *today* case is
   time-sensitive: if it is before 15:35 IST, say the session has not closed and offer to
   run it anyway. A historical date is always allowed.

   ```bash
   task eod:walkthrough                                     # today
   task eod:walkthrough -- --date 2024-03-14                # any past day
   task eod:walkthrough -- --from 2026-07-21 --to 2026-07-24
   task eod:walkthrough -- --days 20 --underlying BANKNIFTY
   ```

   Add `--force` to overwrite an existing report for that date, or to generate a NIFTY
   date inside the 2020-12-03 → 2023-01-05 `option_bars` blackout (refused by default,
   because every day in there trades against a mismatched far-side expiry).

2. **Read the generated file's FINDINGS section** — `backend/backtest/manual/<date>.md`.
   Findings arrive ranked, most severe first, each with an ID (`F-AVG-DRIFT`,
   `F-STRADDLE`, `F-HALT-BREACH`, …), a severity, and the evidence lines behind it.

3. **Summarise the top 3 in chat**, each with the code location that would have to change.
   Trace a finding to its source before asserting a cause — a finding says "look here",
   not "this is the bug". If the day is clean, say so plainly and note that clean means
   the engine's own books reconcile, not that the strategy traded well.

4. **Point at the day's shape** in one line — spot change, day type, each strategy's net,
   and any banner (data-gap warning) at the top of the file. On a zero-trade day, quote
   the *why-no-trade census* rather than speculating.

5. **Offer next action**: "Fix `F-xxx`, then re-run `/eod:walkthrough <date>` — the report
   regenerates to the same path, so `git diff` shows exactly which minutes and which P&L
   moved." For a multi-day sweep, point at `backend/backtest/manual/INDEX.md`, which
   carries one row per day with its top finding IDs.
