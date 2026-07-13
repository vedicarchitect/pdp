# option-bars-expiry-gap-backfill

## Why

While isolating the `dte_max` effect during `papergapfix`'s combined re-baseline (2026-07-13), we
found that NIFTY's `option_bars` collection has real, structural gaps in its expiry coverage:

1. **A 763-day blackout** — zero NIFTY expiry data 2020-12-03 → 2023-01-05, confirmed via direct
   `mdb["option_bars"].distinct("expiry_date", {"underlying": "NIFTY"})` and corroborated by the
   static `data/expiry/nifty_expiries.json` fallback calendar, which shows the same blackout
   (377+ days) and is itself only monthly-granularity through most of 2021.
2. **~25 smaller 12-21 day gaps** scattered 2023-2026, mostly around monthly-expiry transition
   weeks. Spot-checked one against NSE's real historical calendar (WebSearch, 2026-07-13): NIFTY
   had a genuine weekly expiry on Thursday 2023-02-16, absent from both `option_bars` and the
   static calendar. These are missing-ingestion weeks, not weeks NIFTY had no listed contract.

`day_loader.py::load_window` (`backend/pdp/backtest/day_loader.py:82-93`) resolves each trade day's
expiry via `nearest_real_expiry()` — the first *distinct expiry with any ingested rows* on or after
that day. When a gap exists, every day inside it silently resolves to the far side of the gap,
producing either a phantom zero-trade day (chain data doesn't exist for the mismatched
expiry+historical-date pair — the big blackout) or a real trade against an unexpectedly far-dated
contract (the small gaps, where the far expiry's price history genuinely does cover the trade date).
Neither failure mode is visible in a normal backtest run — there's no log line distinguishing "no
real weekly contract existed here" from "one existed but we never ingested it."

This is a data-completeness bug in the historical warehouse, not a strategy or bias-input bug. It
was found and scoped during `papergapfix`'s Phase E re-baseline but is unrelated to that program's
three fixes (`bar-session-anchoring`, `indicator-history-depth`, `bias-input-completeness`) —
filed separately per explicit user decision (2026-07-13) rather than folded into an already-large
diff.

## What Changes

- Audit `option_bars` expiry coverage for NIFTY, BANKNIFTY, and SENSEX against each underlying's
  real historical expiry calendar (NSE circulars / a reliable third-party source), producing a
  per-underlying list of missing expiry weeks.
- Backfill the missing weekly contracts' option chains from Dhan's historical option-chain API
  (same mechanism as `scripts/backfill_market_bars.py`'s Dhan fallback, but for `option_bars`
  rather than `market_bars`).
- For weeks with no real contract at all (the 2021-2022-era blackout, if confirmed unrecoverable —
  Dhan's historical option-chain API may not go back that far), document the gap explicitly rather
  than leaving it silently discoverable only via `nearest_real_expiry`'s forward-fill.
- Add a coverage-gap detector (reusing `real_expiries_from_option_bars` +
  `nearest_real_expiry`'s logic) that a backtest run can log against, so a future `strangle_run.py`
  invocation surfaces "N trade days resolved to an expiry >X days away" instead of silently
  counting them as ordinary traded (or skipped) days.

## Impact

- Affected specs: none yet — likely a delta to `specs/multi-index-warehouse/spec.md` or a new
  `backtest-data-coverage` capability, TBD during design.
- Affected code: `backend/pdp/backtest/day_loader.py`, `backend/pdp/instruments/expiry_calendar.py`,
  `backend/scripts/backfill_market_bars.py` (pattern reference), new
  `backend/scripts/backfill_option_bars_expiry_gaps.py`.
- Out of scope: BANKNIFTY/SENSEX gap audit is listed but not yet run — do that as this change's
  first task, since their `option_bars` coverage has never been checked for gaps at all.
