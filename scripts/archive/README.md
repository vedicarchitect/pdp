# scripts/archive — One-Time Debug Scripts

These scripts were written for a specific debugging session and are **no longer actively used**. Kept for reference only.

| File | Date | Purpose |
|------|------|---------|
| `backtest_full_day.py` | 2026-06-08 | Full-day backtest for Jun8 with hardcoded STRIKES map; fetches option bars live from Dhan API. |
| `backtest_today.py` | 2026-06-08 | Bar-by-bar ST replay + actual fill overlay for Jun8 session. Contains hardcoded `ACTUAL_FILLS` from that specific day. |

Do **not** use these as templates — use `scripts/backtest_compare.py` (generalised, date-parameterised) or `scripts/backtest_sweep.py` (multi-config sweep) instead.
