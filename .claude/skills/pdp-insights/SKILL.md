---
name: pdp:insights
description: Generate trading insights by analyzing multiple days of strangle activity logs, broker sync snapshots, and backtest data. Identifies patterns, systematic biases, and improvement opportunities. Use when reviewing the week's performance or preparing for the next session.
metadata:
  author: pdp
  version: "1.0"
---

Generate multi-day PDP trading insights from structured logs and broker data.

## Input

Optionally specify a date range: `/pdp:insights 2026-06-23 2026-06-28`
Default: last 5 trading days.

## Steps

### 1. Collect data sources

For each trading day in the range:
- `backend/logs/directional_strangle/<date>.log` — canonical strangle events
- `GET /api/v1/broker-sync/runs?limit=30` — sync run history and recon
- `GET /api/v1/broker-sync/holdings` + `/positions` — current state

### 2. Bias + bucket analysis

From `bias_evaluated` events across all days:
- Score distribution histogram (binned to 0.1 intervals)
- Time-of-day bias: show average score by 30-min window (10:15–15:10 IST) — are there
  systematic AM/PM biases?
- Bucket frequency: how many bars spent in each bucket? What % traded?
- Vote consistency: which signals were most often missing (None) vs contributing?

### 3. Trade performance

From `leg_open`/`leg_close`/`take_profit`/`stop_half`/`stop_all` events:
- Total trades, win rate (TP closes vs stop closes)
- Average holding time per exit reason
- Best and worst trades of the period
- P&L by side (PE vs CE): is one side consistently losing?
- Daily P&L trend chart (ASCII bar chart)

### 4. Rollup and stop-gate analysis

- How many rollups fired? Which strikes? How much premium recovered?
- How many stop-gate waits? Did the gate protect against re-entry in the right direction?
- If rollup or stop-gate never fired, note it (may indicate market was calm — or thresholds
  need tuning)

### 5. Broker recon check

From `GET /api/v1/broker-sync/runs`:
- Any `recon.mismatches` in the period? List them (security_id, internal vs broker qty)
- Any partial syncs? Which reports failed?

### 6. Data quality flags

- Days where `cam_weekly` was consistently missing (weekly pivot not warmed)
- Days where `pcr` was always None (PCR source not wired yet)
- Days with `dropped_ticks > 0` (market feed lag)
- Time gaps in `bias_evaluated` (missed bars — API restart during session?)

### 7. Improvement suggestions

Based on the analysis, produce 3–5 actionable suggestions ranked by expected impact:
- Example: "PCR was None on all 5 days — wiring it could shift score by ±0.1 on average"
- Example: "CE side stopped out 3× in 5 days — consider tighter hedge for CE in BEAR buckets"
- Example: "Score was neutral (|score| < 0.2) for 40% of bars — neutral_no_trade=True may
  reduce churn without impacting realized P&L"
- Example: "Rollup fired 0 times in 5 days — premium hasn't decayed to Rs 20; check if
  roll_trigger_prem needs adjustment for current volatility regime"

## Output Format

```
PDP Insights: 2026-06-23 → 2026-06-28
======================================

BIAS SUMMARY
  Score distribution: [-1,-0.5): 5% | [-0.5,0): 22% | [0,0.5): 38% | [0.5,1]: 35%
  Dominant bucket: MOST_BULL (31% of bars)
  Missing signals: cam_weekly (100% days), pcr (100% days)

TRADE PERFORMANCE
  Trades: 12 | Win rate: 67% | Avg hold: 2h 15m
  Day P&L:  Mon +2,340  Tue -1,100  Wed +4,220  Thu +890  Fri +1,450
  Week P&L: +7,800

NOTABLE EVENTS
  Rollups: 1 (Thu, CE from 23800 → 24000 strike)
  Stop-gates: 3 (Mon ×2, Thu ×1)
  Day halts: 0

RECON
  Mismatches: 0 (all syncs clean)

TOP SUGGESTIONS
  1. Wire live PCR — was None all week; estimated score impact ±0.05–0.15
  2. cam_weekly missing — subscribe 1w bar (task 4.1 in strangle-execution-console)
  3. CE side: 2 of 3 stops on CE — review CE short sizing in NEUTRAL bucket
```

End with: "Run `/strangle:review <date>` for a single day deep-dive."
