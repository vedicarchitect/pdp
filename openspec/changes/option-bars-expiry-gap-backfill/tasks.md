# Tasks — option-bars-expiry-gap-backfill

## 1. Establish full scope (blocking — nothing else starts until this is answered)
- [x] 1.1 NIFTY gap audit done during `papergapfix` Phase E (2026-07-13): 763-day blackout
      (2020-12-03 → 2023-01-05) + ~25 smaller 12-21 day gaps 2023-2026. See
      `openspec/changes/bar-session-anchoring/README.md` "Combined re-baseline results" for the
      full list and the NSE spot-check confirming these are missing-ingestion, not real absences.
- [ ] 1.2 Run the same `distinct("expiry_date", ...)` gap scan for BANKNIFTY and SENSEX — never
      checked. Record results in this change's README.
- [ ] 1.3 For each NIFTY small gap (~25), spot-check at least 3 more against a real historical NSE
      expiry source (only 1 of ~25 has been verified so far) to confirm the "missing ingestion, not
      missing listing" hypothesis generalizes, not just for the one checked date.
- [ ] 1.4 Determine whether the 763-day blackout is backfillable at all — Dhan's historical
      option-chain API may not retain data that far back. If not recoverable, this becomes a
      documented, permanent gap (task group 4), not a backfill target.

## 2. Reuse vs. rebuild
- [ ] 2.1 Read `backend/pdp/options/gap_backfill.py` in full — it already does rolling-window
      self-healing backfill from Dhan for `option_bars`, but is designed for a `WAREHOUSE_GAP_LOOKBACK_DAYS=30`
      rolling window (recent gaps), not multi-year historical ones. Determine whether it can be
      called directly with a wider explicit date range, or whether a new one-off script (pattern:
      `scripts/backfill_market_bars.py`) is warranted.
- [ ] 2.2 If reusable: add a `--from`/`--to` override path to `gap_backfill.py`'s entry point (or
      its CLI caller `scripts/backfill_options_gap.py`) rather than duplicating the Dhan-fetch /
      rate-limit / bulk-write logic.
- [ ] 2.3 If not reusable: write `scripts/backfill_option_bars_expiry_gaps.py`, sharing the
      rate-limiter and upsert helpers from `gap_backfill.py`.

## 3. Backfill (blocked — needs live Dhan creds; `DH-901 Invalid_Authentication` in this
   environment as of 2026-07-13, same blocker as `dhan-same-day-data`/`indicator-history-depth`)
- [ ] 3.1 Backfill the ~25 small 2023-2026 gaps first (higher confidence they're recoverable —
      real contracts, just never ingested).
- [ ] 3.2 Attempt the 763-day blackout; document the outcome either way (task 1.4/4.1).
- [ ] 3.3 Re-run the NIFTY isolation backtest (`--dte-max 400`, same window as `papergapfix`
      Phase E) after backfill; compare traded-days/Net P&L against the pre-backfill isolation run
      (+₹56.70L, 1105 traded days) to quantify what the gap was actually costing.

## 4. Guard against silent forward-fill (safe to do regardless of backfill progress)
- [ ] 4.1 `nearest_real_expiry()` (`pdp/instruments/expiry_calendar.py:76`) or its caller
      (`day_loader.py::load_window`) logs when the resolved expiry is more than N days (e.g. 21)
      past the trade date — a coverage-gap signal, not silent forward-fill.
- [ ] 4.2 `strangle_run.py`'s per-chunk summary line surfaces a count of "days resolved to a
      suspiciously distant expiry" alongside `valid`/`skipped`, so a future backtest run doesn't
      need a bespoke investigation to notice this.
- [ ] 4.3 Document the permanent (if any) unrecoverable gap in `backend/pdp/backtest/CLAUDE.md` so
      future backtest runs over that window carry a known caveat.

## 5. Docs + validation
- [ ] 5.1 Update this change's README with the BANKNIFTY/SENSEX audit results (task 1.2) and the
      backfill outcome.
- [ ] 5.2 `task test` green.
- [ ] 5.3 `openspec validate --strict option-bars-expiry-gap-backfill`.

## Status (2026-07-13)

Filed from a finding made during `papergapfix`'s Phase E re-baseline. Task 1.1 (NIFTY scope) is
done; everything else is unstarted. Task group 3 (the actual backfill) is blocked on live Dhan
credentials, same as two other in-flight changes. Task group 4 (silent-forward-fill guard) has no
external blockers and could land first, independent of the backfill itself.
