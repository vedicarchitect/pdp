# Tasks — option-bars-expiry-gap-backfill

## 1. Establish full scope (blocking — nothing else starts until this is answered)
- [x] 1.1 NIFTY gap audit done during `papergapfix` Phase E (2026-07-13): 763-day blackout
      (2020-12-03 → 2023-01-05) + ~25 smaller 12-21 day gaps 2023-2026. See
      `openspec/changes/bar-session-anchoring/README.md` "Combined re-baseline results" for the
      full list and the NSE spot-check confirming these are missing-ingestion, not real absences.
- [x] 1.2 Run the same `distinct("expiry_date", ...)` gap scan for BANKNIFTY and SENSEX — never
      checked. Record results in this change's README.
      **Done (2026-07-13)**: both clean — **0** cadence gaps each (BANKNIFTY: 261 stored
      expiries 2021-08-04..2026-07-29; SENSEX: 167 stored expiries 2023-05-15..2026-07-13; both
      uninterrupted ~7-day cadence). Only NIFTY has real cadence gaps (19 detected in the
      2023-2026 window alone). See README "BANKNIFTY/SENSEX gap audit" — also surfaced a
      separate, out-of-scope finding: BANKNIFTY's stored `option_bars` expiries stay
      weekly-cadence despite the real-world monthly-only regime change.
- [x] 1.3 For each NIFTY small gap (~25), spot-check at least 3 more against a real historical NSE
      expiry source (only 1 of ~25 has been verified so far) to confirm the "missing ingestion, not
      missing listing" hypothesis generalizes, not just for the one checked date.
      **Done (2026-07-13)**: 3 more spot-checked via WebSearch against NSE's real calendar/holiday
      list (2023-03-23, the holiday-shifted 2023-04-19, 2024-04-18) — all 3 confirm genuine listed
      expiries missing from `option_bars`. 4/4 checked gaps (incl. the proposal's original) confirm
      the hypothesis. See README "NIFTY small-gap spot-checks".
- [x] 1.4 Determine whether the 763-day blackout is backfillable at all — Dhan's historical
      option-chain API may not retain data that far back. If not recoverable, this becomes a
      documented, permanent gap (task group 4), not a backfill target.
      **Done (2026-07-13)**: Dhan creds confirmed live; `expired_options_data` returns real
      bars (375-376 bars/day) for probes at 2020-12-10 and 2021-06-15, both deep inside the
      blackout. The blackout **is backfillable** — not a permanent gap. See README.

## 2. Reuse vs. rebuild
- [x] 2.1 Read `backend/pdp/options/gap_backfill.py` in full — it already does rolling-window
      self-healing backfill from Dhan for `option_bars`, but is designed for a `WAREHOUSE_GAP_LOOKBACK_DAYS=30`
      rolling window (recent gaps), not multi-year historical ones. Determine whether it can be
      called directly with a wider explicit date range, or whether a new one-off script (pattern:
      `scripts/backfill_market_bars.py`) is warranted.
      **Resolved (2026-07-13): already reusable** — `scripts/backfill_options_gap.py` (the CLI
      caller) already accepts `--symbol {NIFTY,BANKNIFTY,SENSEX} --from --to --only-missing` and
      calls `gap_backfill.backfill_gaps()` with an explicit `days` list, not the rolling-window
      entry point (`run_gap_backfill`). No `--from`/`--to` gap to fill. See README.
- [x] 2.2 If reusable: add a `--from`/`--to` override path to `gap_backfill.py`'s entry point (or
      its CLI caller `scripts/backfill_options_gap.py`) rather than duplicating the Dhan-fetch /
      rate-limit / bulk-write logic.
      **N/A — already present**, see 2.1.
- [x] 2.3 If not reusable: write `scripts/backfill_option_bars_expiry_gaps.py`, sharing the
      rate-limiter and upsert helpers from `gap_backfill.py`.
      **N/A — reusable**, see 2.1.
- [x] 2.4 **Revision (2026-07-14): the "already reusable" conclusion was wrong.** The reuse path
      resolved every target expiry from the static `data/expiry/*.json` cache, which shares
      `option_bars`' own gaps, so it could never land a genuinely-missing expiry (the 3.1 finding).
      Fixed by making a DB-backed `expiry_calendar` collection the source of truth
      (`pdp.instruments.expiry_calendar.load_expiry_calendar_from_db` / `upsert_confirmed_expiries`;
      `pdp.mongo.collections._ensure_expiry_calendar`), with `scripts/seed_expiry_calendar.py`
      (`--from-option-bars` seeds all covered history authoritatively; `--add`/`--from-json` for
      confirmed gap dates). Decision recorded by the user: persist in Mongo, not JSON.

## 2b. Full expiry ladder (WEEK + MONTH) — new scope (2026-07-14)
- [x] 2b.1 Dhan's `expired_options_data` `expiry_code` is documented `0-3` only, so "all expiries
      weekly → next-month monthly" needs both flags. `gap_backfill.fill_day()` now takes a
      `(flag, code)` **ladder** (`DEFAULT_LADDER` = WEEK 1,2,3 + MONTH 1,2) and threads `expiry_flag`
      through the Dhan fetch and the stored doc (previously hardcoded `WEEK`). CLI gains
      `--week-codes`/`--month-codes` (`--codes` kept as a WEEK alias). Live self-heal loop keeps the
      lighter `SELF_HEAL_LADDER` (WEEK 1,2) to avoid a 2.5x heavier hot cycle.
- [x] 2b.2 `classify_month_expiries()` (last-of-calendar-month = MONTH; weekday-free) so seeding
      from real data populates both flags correctly. Reused by the seed script and forward-population.
- [x] 2b.3 Forward-population: `ScripRefreshScheduler._sync_expiry_calendar()` upserts upcoming real
      expiries (source `scripmaster`) each daily refresh so the calendar self-maintains and never
      re-drifts. Covers all 3 indices.
- [x] 2b.4 `--target-expiry` escape hatch (`backfill_missing_expiry`) restricted to a single
      `(flag, code)` so an override can't mislabel a multi-entry ladder; primary small-gap path is
      seed-the-expiry + `backfill_gaps(only_missing=False)`.
- [x] 2b.5 Tests: ladder/MONTH-flag threading + override path (`tests/test_gap_backfill.py`);
      `classify_month_expiries`, DB-calendar load/upsert round-trip (`tests/test_expiry_calendar.py`).
      Full suite **1146 passed** (up from 1131). ruff clean; pyright adds no new errors in `pdp/`.

## 2c. Authoritative expiry calendar from NSE+BSE archives + enrichment (2026-07-14)
- [x] 2c.1 The calendar seeded from `option_bars` alone (2b/3.4) structurally cannot fill
      genuinely-missing dates (it shares option_bars' gaps). Built `scripts/seed_expiry_from_bhavcopy.py`
      (task `expiry:seed:archive`, one-time): exchange-aware NSE **and** BSE bhavcopy seeder —
      auto-routes NIFTY/BANKNIFTY→NSE, SENSEX→BSE (different exchange). Handles legacy zip
      (pre-2024-07-08, cols INSTRUMENT/EXPIRY_DT) + UDiFF zip (2024-07-08+, FinInstrmTp=IDO/XpryDt/
      NewBrdLotQty). BSE is plain CSV needing `Referer` header and returns an HTTP-200 homepage for
      non-trading days — added `_looks_like_bhav()` content validation so HTML pages count as misses,
      not empty bhavcopies (fixed a poisoned-cache bug that silently dropped SENSEX expiries).
- [x] 2c.2 Enrichment (user-requested backtest-mapping fields): `upsert_confirmed_expiries()` now
      stamps `expiry_weekday` + `expiry_weekday_num` (always) and `lot_size` (when the bhavcopy row
      carries it) via `$set`, keeping `source`/`confirmed_at` in `$setOnInsert`. Test
      `test_upsert_confirmed_expiries_stamps_weekday_and_lot`. Enables per-weekday / lot-aware
      strategy mapping against existing option_bars.
- [x] 2c.3 `scripts/report_expiry_gaps.py` (task `expiry:gaps`): read-only per-underlying report —
      cadence gaps cross-checked against which dates the DB calendar can now label. NIFTY = **0
      unlabellable gaps** after archive seeding (all 134 missing expiries labellable). Archive proved
      a guessed date wrong: real NIFTY expiry that week was 2023-04-20, not 2023-04-19.
- [x] 2c.4 Every utility wired to `Taskfile.yml` (`expiry:seed:archive`, `expiry:seed:observed`,
      `expiry:gaps`) + `docs/RUNBOOK.md` §10 + `backend/scripts/CLAUDE.md`. Archive seed is one-time;
      forward contracts self-maintain via the scrip-master hook (2b.3).

## 3. Backfill (tooling landed 2026-07-14; NIFTY small-gap execution in progress)
- [~] 3.1 Backfill the ~19-25 small 2023-2026 NIFTY gaps first (higher confidence they're
      recoverable — real contracts, just never ingested).
      **Design issue found 2026-07-13 is now fixed (task groups 2.4/2b/2c, 2026-07-14).** With the
      archive-seeded calendar the per-`E` `--add`/NSE-confirm step is unnecessary — the calendar
      already labels every gap date. **Pilot VERIFIED (2026-07-14, fresh token, no DH-901):** filled
      2023-03-16..24 (203,761 bars); 2023-03-23 now 93,718 bars, correctly labelled with **no
      far-side mislabel** (03-16/03-23/03-29/03-30/04-06 each under its correct expiry_date).
      **In progress:** full small-gap fill — 25 missing NIFTY weekly expiries, union of `[E-10d, E]`
      windows = 202 trading days, `backfill_gaps(only_missing=False)`, ~5h live Dhan writes. Excludes
      the 763-day blackout (3.2, deferred) and 2026-07-21 (future/not-yet-expired). Verify each `E`
      appears in `distinct("expiry_date")` on completion.
- [ ] 3.2 Attempt the 763-day blackout; document the outcome either way (task 1.4/4.1). **Deferred**
      (user, 2026-07-14): source the 2020-2023 WEEK+MONTH expiry dates from NSE historical archives,
      seed as `nse_verified`, then run the full ladder in resumable monthly slices. Not run in this
      pass (multi-hour live writes).
- [ ] 3.3 Re-run the NIFTY isolation backtest (`--dte-max 400`, same window as `papergapfix`
      Phase E) after backfill and **compare against the benchmark baseline** (user-requested):
      traded-days/Net P&L vs the pre-backfill isolation run (+₹56.70L, 1105 traded days) and the
      archived per-index baselines (NIFTY +₹42.71L). Record the delta before archiving.
- [x] 3.4 Seed the DB calendar for BANKNIFTY + SENSEX from `option_bars` too
      (`--from-option-bars`), so the full-ladder path is ready for all three indices even though
      only NIFTY had detected cadence gaps.
      **Done (2026-07-14)**: `expiry_calendar` first seeded from `option_bars`, then **superseded by
      the authoritative NSE+BSE archive seed (2c)** — now **1257 docs, all weekday-stamped**: NIFTY
      WEEK 354/MONTH 88, BANKNIFTY 385/108, SENSEX 262/60 (by source: 754 option_bars_observed +
      387 nse_archive + 116 bse_archive). Cadence-gap enumeration (read-only): **NIFTY has 25 small
      gaps + the 763-day blackout; BANKNIFTY and SENSEX are clean (0 gaps)** — small-gap fills are
      NIFTY-only. The off-by-one concern from the option_bars-only seed is moot: the archive calendar
      has every real date, so `only_missing=False` over each window labels each `E` correctly with no
      per-`E` pre-seed (confirmed by the 2023-03-23 pilot).
      **Token refreshed (2026-07-14)**: the earlier `DH-901` is resolved; pilot + small-gap fills run
      against live Dhan. Dhan intraday history floor pinned by probe = **first week of Aug 2020**
      (2020-07-29 empty, 2020-08-05 = 375 bars); 2019/H1-2020 have no intraday data at all.

## 4. Guard against silent forward-fill (safe to do regardless of backfill progress)
- [x] 4.1 `nearest_real_expiry()` (`pdp/instruments/expiry_calendar.py:76`) or its caller
      (`day_loader.py::load_window`) logs when the resolved expiry is more than N days (e.g. 21)
      past the trade date — a coverage-gap signal, not silent forward-fill.
      **Done (2026-07-13)**: implemented as `expiry_cadence_gaps()` per
      `specs/market-data-coverage/spec.md` (per-underlying cadence threshold, not a fixed N).
      `day_loader.load_window()` flags `WindowData.cadence_gap_days` and logs
      `expiry_cadence_gap_trade_days`. Tests: `tests/test_expiry_calendar.py`,
      `tests/backtest/test_day_loader_cadence_gap.py`.
- [x] 4.2 `strangle_run.py`'s per-chunk summary line surfaces a count of "days resolved to a
      suspiciously distant expiry" alongside `valid`/`skipped`, so a future backtest run doesn't
      need a bespoke investigation to notice this.
      **Done (2026-07-13)**: `backtest/strangle_run.py` per-chunk log line now includes
      `N cadence-gap`; run-level warning + `cadence_gap_days` in the persisted `window` summary.
- [x] 4.3 Document the permanent (if any) unrecoverable gap in `backend/pdp/backtest/CLAUDE.md` so
      future backtest runs over that window carry a known caveat.
      **Done (2026-07-13)**: new "Known `option_bars` expiry-cadence gaps" section.

## 5. Docs + validation
- [x] 5.1 Update this change's README with the BANKNIFTY/SENSEX audit results (task 1.2) and the
      backfill outcome.
      **Done (2026-07-13)** for the audit results (BANKNIFTY/SENSEX both clean, NIFTY 19-25 gaps,
      4/4 spot-checks confirmed). The actual backfill outcome (task group 3) is still blocked on
      live Dhan creds, so that part of this task remains unfillable until creds are available.
- [x] 5.2 `task test` green. **1146 passed** (2026-07-14, up from 1131; +15 new tests total).
- [x] 5.3 `openspec validate --strict option-bars-expiry-gap-backfill`. **Valid** (2026-07-13).

## Status (2026-07-14, updated)

Scope (1), reuse assessment + correction (2/2.4), the full WEEK+MONTH ladder + DB-backed
self-maintaining calendar (2b), the **authoritative NSE+BSE archive seed + weekday/lot enrichment**
(2c), and the forward-fill guards (4) are **done** (tests 1147 passed; ruff clean). The design flaw
that blocked 3.1 is fixed and the token is refreshed.

**Live execution now underway:** the 2023-03-23 pilot is verified end-to-end (3.1), and the full
NIFTY small-gap fill (25 expiries / 202 trading days) is running. Remaining: verify all 25 `E` land,
then the NIFTY isolation backtest-vs-benchmark (3.3). The 763-day blackout (3.2) stays **deferred**
(calendar already labels its 109 dates; needs explicit go-ahead for the multi-hour live write).
