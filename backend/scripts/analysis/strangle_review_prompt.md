# Strangle Session Review — Claude prompt

You are reviewing one trading day of the `directional_strangle` strategy. The input is the
JSON returned by `GET /api/v1/analysis/session?date=YYYY-MM-DD` — a bar-anchored session
narrative reconstructed from the `pdp-strangle-events-*` OpenSearch index.

## Input shape

```json
{
  "date": "YYYY-MM-DD",
  "strategy_id": "directional_strangle",
  "summary": {
    "total_bias_events": 0, "total_leg_opens": 0, "total_leg_closes": 0,
    "total_stops": 0, "total_tps": 0, "total_rolls": 0,
    "day_realized_pnl": null, "buckets_seen": []
  },
  "bars": [
    {
      "bar_time": "ISO ts", "bucket": "STRONG_BULL", "score": 0.0, "spot": 0.0,
      "bias_votes": { "ema_1h": 1, "vwap": -1 },
      "leg_status": { "legs": [ ... ] },
      "actions": [ { "event_type": "leg_open", "opt_type": "CE", "strike": 0, "...": "..." } ]
    }
  ]
}
```

## Your task

1. **Most consequential decisions** — identify the 3 actions (opens / stops / rolls / take-profits)
   that mattered most to the day's P&L, with the bar time and why.
2. **Was the bias predictive?** — for each distinct `bucket`, judge whether the NIFTY `spot`
   moved in the implied direction over the following bars. Call out where the bucket led or
   lagged the move.
3. **Stop-gate & risk** — did stops / the re-entry cooldown protect capital or cut winners
   early? Note any `stop_gate_wait` clusters.
4. **1–2 parameter adjustments** — concrete, with rationale tied to today's bars (e.g. roll
   trigger premium, hedge band, stop tier %, bucket→ratio mapping).

Keep it tight and evidence-based — cite bar times. End with a one-line verdict:
**KEEP / TUNE / REVIEW**.
