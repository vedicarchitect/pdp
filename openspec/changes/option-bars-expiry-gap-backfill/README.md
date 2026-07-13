# option-bars-expiry-gap-backfill — minimal context

Read only these to work this change.

| File | Why |
|------|-----|
| `backend/pdp/backtest/day_loader.py` | `load_window:60-100` — `real_expiries_from_option_bars`/`nearest_real_expiry` forward-fill across gaps, silently |
| `backend/pdp/instruments/expiry_calendar.py` | `real_expiries_from_option_bars:54-73`, `nearest_real_expiry:76-81`, `within_dte:42-51` |
| `data/expiry/nifty_expiries.json` | Static fallback calendar (`WEEK`/`MONTH` keys) — corroborates the gap, itself incomplete pre-2022 |
| `backend/scripts/backfill_market_bars.py` | Pattern reference for a Dhan-fallback backfill script (spot bars, not option chains — this change needs the option-chain equivalent) |
| `backend/pdp/options/gap_backfill.py` | Existing options warehouse self-healing gap-backfill loop — check whether it already covers historical (not just live-forward) gaps before writing a new script |

## Key facts established during investigation (2026-07-13, during `papergapfix` Phase E)

- NIFTY `option_bars` has zero expiry data 2020-12-03 → 2023-01-05 (763 days), confirmed via
  `mdb["option_bars"].distinct("expiry_date", {"underlying": "NIFTY"})`.
- The static `data/expiry/nifty_expiries.json` calendar shows the same-era blackout (377+ days,
  2021-12-24 → 2023-01-05) and is only monthly-granularity (28/35-day spacing) through most of
  2020-2021 — it was never populated with real weekly cadence for that period either. Both sources
  likely share a root ingestion gap rather than being independent confirmations of "no market data
  existed" (NIFTY has had continuous weekly expiries since 2019 in reality).
- ~25 smaller 12-21 day gaps exist 2023-2026, concentrated around monthly-expiry transition weeks.
  Spot-checked one (2023-02-09 → 2023-02-23) against a live web search of NSE's real calendar:
  Thursday 2023-02-16 was a genuine NIFTY weekly expiry day, confirming this is a missing-ingestion
  gap, not a real absence of a listed contract.
- `nearest_real_expiry()` has no concept of "this gap is suspiciously large" — it forward-fills to
  whatever the next *ingested* expiry is, however far away, with no logged signal. A backtest
  consuming this silently either (a) counts a phantom zero-trade day as "traded" (if the mismatched
  far expiry has no chain data covering the historical trade date — true for the big blackout), or
  (b) trades a real but unexpectedly-far-dated contract (true for the small gaps, where the far
  expiry's own price history does extend back far enough to cover the gap days).
- BANKNIFTY and SENSEX `option_bars` coverage has not yet been checked for analogous gaps — this
  change's first task.

## Related

Surfaced during `papergapfix`'s Phase E combined re-baseline — see
`openspec/changes/bar-session-anchoring/README.md` "Combined re-baseline results (2026-07-13)" for
the full trace of how this gap confounded (and was disentangled from) the NIFTY P&L comparison.
Unrelated to that program's three fixes; filed separately by explicit user decision.
