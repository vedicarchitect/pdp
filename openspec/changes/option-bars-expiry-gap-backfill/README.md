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

## Implementation notes (2026-07-13, `/opsx:apply`)

### Status

Task groups 1, 2, 4, and 5.2/5.3 are done. Task group 3 (the actual backfill) remains blocked on
live Dhan credentials (`DH-901 Invalid_Authentication`, same blocker as
`dhan-same-day-data`/`indicator-history-depth` as of 2026-07-13). Task 1.4 (whether the 763-day
NIFTY blackout is backfillable at all) is also blocked on those creds — it needs a live Dhan call
to test, not just a Mongo read.

### BANKNIFTY/SENSEX gap audit (task 1.2)

Ran `scripts/audit_options_coverage.py --symbol {BANKNIFTY,SENSEX}` (read-only; each took
15-25 minutes against the real `option_bars` collection — ~109M docs total across all three
underlyings; Mongo itself pings in under 2s, the aggregations are just slow at this scale) and
then ran the new `expiry_cadence_gaps()` detector against each underlying's actual distinct-expiry
set pulled from the audit:

| Underlying | Data range | Docs | Cadence gaps (`expiry_cadence_gaps`) |
|---|---|---|---|
| NIFTY | 2020-08-03 .. 2026-07-13 | 43.1M | **19** in 2023-01..2026-05 alone (proposal's "~25" figure covers a slightly wider window) |
| BANKNIFTY | 2021-08-04 .. 2026-07-13 | 47.7M | **0** — 261 stored expiries, uninterrupted ~7-day cadence throughout |
| SENSEX | 2023-05-15 .. 2026-07-13 | 17.9M | **0** — 167 stored expiries, uninterrupted ~7-day cadence throughout |

Only NIFTY has real expiry-cadence gaps. The existing per-day contract-completeness audit (the
`days_missing()` check `audit_options_coverage.py` already ran) reported **0 gap days** for NIFTY
over the same window — it is structurally blind to this bug, because the days inside a cadence gap
still have a full option chain, just against the wrong (far-side) expiry. This is the concrete
confirmation of the proposal's core thesis and the reason a dedicated cadence detector (not a
reuse of the existing per-day check) was the right fix for task group 4.

**Finding beyond this change's scope**: BANKNIFTY's real-world forward listing went monthly-only
(regime change, per `expiry-and-feed-truth`), but `option_bars`' historical distinct-expiry set
stays weekly-cadence straight through 2026-07-29 — `pdp.options.gap_backfill.fill_day()` resolves
every backfilled day against the hardcoded `"WEEK"` calendar flag regardless of the underlying's
real current regime, so that's what's actually stored. `_EXPECTED_CADENCE["BANKNIFTY"]` in
`expiry_calendar.py` was set to match what's actually persisted (weekly, `(7, 3)`) rather than the
real-world regime, since the detector operates on `real_expiries_from_option_bars` — the stored
data, not the live scrip master. Whether BANKNIFTY's *option_bars* ingestion should itself be
switched to resolve against the real (monthly) regime is a separate question, out of scope here.

### NIFTY small-gap spot-checks (task 1.3)

Proposal already confirmed one gap (2023-02-16, a genuine missing Thursday weekly expiry). Spot-
checked 3 more of the 19 detected cadence gaps against NSE's real historical calendar/holiday list
(WebSearch, 2026-07-13) — all 3 confirm the missing-ingestion (not missing-listing) hypothesis:

| Gap detected | Real NSE expiry for that week | Verdict |
|---|---|---|
| 2023-03-16 → 2023-03-29 (13d) | Thursday 2023-03-23, no holiday nearby | Genuine listed weekly expiry, missing from `option_bars` |
| 2023-04-13 → 2023-04-27 (14d) | Thursday 2023-04-20 was Ram Navami (NSE holiday) → real expiry shifted to Wednesday 2023-04-19 | The holiday-shifted expiry itself is missing from `option_bars`, not just the naive Thursday date |
| 2024-04-10 → 2024-04-25 (15d) | Thursday 2024-04-18, no holiday (NSE was closed 2024-04-11 Eid and 2024-04-17 Ram Navami, neither of which is Apr 18) | Genuine listed weekly expiry, missing from `option_bars` |

4/4 spot-checked gaps (1 from the proposal + 3 here) confirm the hypothesis generalizes: these are
missing-ingestion weeks, not weeks with no real listed contract.

### What shipped this session (task group 4 — no external blocker)

Per `specs/market-data-coverage/spec.md`'s "Expiry-cadence gap detection" requirement:

- **`pdp/instruments/expiry_calendar.py`**: new `expiry_cadence_gaps(underlying, real_expiries,
  *, cadence_days=None, tolerance_days=None)` and `expiry_cadence_threshold(underlying)`. Detects
  a gap when two consecutive claimed expiries (from `real_expiries_from_option_bars`) are further
  apart than the underlying's expected listing cadence + a holiday-shift tolerance — `(7, 3)` days
  for NIFTY/SENSEX/BANKNIFTY (all three are weekly-cadence in the *stored* data, see the BANKNIFTY
  finding above). The optional `cadence_days`/`tolerance_days` override lets a caller (or test)
  exercise a hypothetical different cadence (e.g. a genuinely monthly-only underlying) without
  needing a real underlying whose stored data matches. Returns `(underlying, gap_start, gap_end,
  gap_days)` tuples. 7 new unit tests in `tests/test_expiry_calendar.py`.
- **`pdp/backtest/day_loader.py`**: `WindowData` gained `cadence_gap_days: set[date]`.
  `load_window()` computes cadence gaps from the window's real expiries and flags every trade day
  whose `nearest_real_expiry()` resolution crosses one (strictly between the gap's near and far
  claimed expiry — the far expiry's own trade day is excluded, since trading against your own real
  expiry is correct, not a forward-fill artifact). Logs `expiry_cadence_gap_trade_days` with the
  count and gap list when any are found. 2 new unit tests in
  `tests/backtest/test_day_loader_cadence_gap.py` (using the exact NSE-confirmed 2023-02-16 gap
  from the investigation above as the scenario).
- **`backtest/strangle_run.py`**: per-chunk summary line now reports `N cadence-gap` separately
  from `valid`/`skipped`/`VIX`/`PCR`; a run-level warning fires if any traded day fell inside a
  detected gap; `writer.finalize()`'s persisted `window` summary carries `cadence_gap_days` too.
- **`backend/pdp/backtest/CLAUDE.md`**: documented the confirmed NIFTY blackout
  (2020-12-03 → 2023-01-05), the 19-25 smaller 2023-2026 gaps, and the BANKNIFTY/SENSEX clean
  results as a standing caveat/reference for any backtest window, with a pointer to
  `WindowData.cadence_gap_days` and the per-chunk log line as the mechanism that now surfaces it
  instead of silently forward-filling.

`task test`: **1139 passed** (was 1131; +8 new tests from this change). `openspec validate
--strict option-bars-expiry-gap-backfill`: valid.

### Reuse decision (tasks 2.1-2.3)

`scripts/backfill_options_gap.py` + `pdp/options/gap_backfill.py` already support everything task
group 2 asked for: `--symbol {NIFTY,BANKNIFTY,SENSEX}`, `--from`/`--to` (arbitrary historical
range, not just the rolling 30-day self-healing window), `--only-missing`, per-symbol
sid/step/exchange-segment config, and idempotent first-write-wins upserts. No new script is
needed — `scripts/backfill_options_gap.py --symbol <SYM> --from <date> --to <date>
--only-missing` is the tool for task group 3 once Dhan creds are available.

### Dhan creds live again (2026-07-13, later same day) — task 1.4 + sample backfill

Creds started working (`DHAN_CLIENT_ID`/`DHAN_ACCESS_TOKEN` both set, no more `DH-901`). Ran a
read-only probe (`dhan.expired_options_data`) against 4 dates before writing anything:

| Date | Purpose | Result |
|---|---|---|
| 2024-01-05 | sanity (known-good, no gap) | 376 bars, `status=success` |
| 2023-03-23 | confirmed small gap (task 1.3) | 375 bars, `status=success` |
| 2021-06-15 | deep inside the 763-day blackout | 375 bars, `status=success` |
| 2020-12-10 | blackout, near the start edge | 375 bars, `status=success` |

**Task 1.4 answered: the blackout is backfillable.** Dhan's historical API still serves real
option-chain data for dates inside 2020-12-03..2023-01-05 — this is not a permanent gap.

**Sample backfill finding — task group 2's reuse conclusion needs revision.** Ran the actual (write)
path scoped to just the one NSE-confirmed gap day: `scripts/backfill_options_gap.py --symbol NIFTY
--from 2023-03-23 --to 2023-03-23`. It reported `inserted=8` and looked like a success, but
verifying against Mongo directly (`distinct("expiry_date", ...)`) shows **no `2023-03-23` expiry
was created** — the 8 new bars landed under the pre-existing, still-wrong 2023-03-29/2023-04-06
far-side expiries (legitimate market data for those contracts, just not the fix needed here).

Root cause: `fill_day()` (`pdp/options/gap_backfill.py:296-299`) resolves the target expiry via
`cal.resolve_expiry(trade_date, "WEEK", code)` against the **static** `data/expiry/nifty_expiries.json`
cache, not against a fetched/known-correct expiry. That cache has the identical gap — its `WEEK`
list jumps straight from `2023-03-16` to `2023-03-29`, no `2023-03-23` entry — confirmed via direct
read. So `resolve_expiry()` can never return `2023-03-23`; it structurally cannot resolve to an
expiry the calendar doesn't know exists, no matter how many times `fill_day()` is called for trade
days in that window. The 763-day blackout has the same problem, likely worse (the cache itself is
"only monthly-granularity through most of 2020-2021" per the investigation notes above).

**This invalidates task group 2's "no new code needed" conclusion for the cadence-gap use case**
(it's still correct for the *rolling self-healing* use case the tool was originally built for,
where the calendar already has the right entries). Fixing this needs one of:
1. Patch `data/expiry/nifty_expiries.json` (and the BANKNIFTY/SENSEX equivalents, if ever needed)
   with the missing expiry dates first — the NSE spot-checks (task 1.3) already give us 4 confirmed
   real dates; the rest of the ~19-25 NIFTY gaps + the blackout would need the same treatment.
2. Add an explicit-target-expiry parameter to `fill_day()`/`backfill_gaps()` that bypasses
   `cal.resolve_expiry()` entirely when the caller already knows the exact missing expiry date (which
   `expiry_cadence_gaps()` from this same change already computes as `gap_end`).

No further live writes were attempted once this was found. Paused here pending a decision on which
of the two above to implement — this is a real design change to task group 2, not just an
execution detail of task group 3.

### Resolution (2026-07-14) — DB-backed calendar + full WEEK+MONTH ladder

The design gap is fixed. Decision (user): persist the expiry calendar in **Mongo**, not JSON, and
add an explicit-target override — do both. Implementation:

- **DB-backed `expiry_calendar` collection** is now the calendar source of truth
  (`_ensure_expiry_calendar` in `pdp/mongo/collections.py`; `load_expiry_calendar_from_db` /
  `upsert_confirmed_expiries` / `classify_month_expiries` in `pdp/instruments/expiry_calendar.py`).
  `scripts/seed_expiry_calendar.py --from-option-bars` seeds the entire covered history
  authoritatively (WEEK = all real expiries, MONTH = last-of-calendar-month); `--add`/`--from-json`
  add NSE-confirmed gap dates. `backfill_options_gap.py` reads this instead of the gapped JSON.
- **Full expiry ladder.** Dhan's `expired_options_data` caps `expiry_code` at `0-3`, so "weekly →
  next-month monthly" is `DEFAULT_LADDER` = WEEK 1,2,3 + MONTH 1,2. `fill_day()` now takes a
  `(flag, code)` ladder and threads `expiry_flag` through the fetch **and** the stored doc (was
  hardcoded `WEEK`). CLI: `--week-codes` / `--month-codes`. The live self-heal loop keeps the
  lighter WEEK 1,2 default.
- **Explicit-target override** (`backfill_missing_expiry` / `--target-expiry`) kept as an escape
  hatch, restricted to a single `(flag, code)` so it can't mislabel a multi-entry ladder.
- **Self-maintaining**: the daily scrip-master refresh upserts upcoming real expiries into the
  collection (source `scripmaster`), so it stays current and never re-drifts.
- Tests: **1146 passed** (was 1131). ruff clean; no new `pdp/` pyright errors.

### Authoritative archive seed + enrichment + live execution (2026-07-14, later same day)

- **Calendar source of truth upgraded to the NSE+BSE bhavcopy archives** (task group 2c). The
  option_bars-only seed can't supply dates it's itself missing, so `scripts/seed_expiry_from_bhavcopy.py`
  (`task expiry:seed:archive`, one-time) pulls real expiries + weekday + lot size from the exchange
  archives — NSE for NIFTY/BANKNIFTY, **BSE for SENSEX** (separate exchange, plain-CSV UDiFF needing
  a `Referer` header; homepage-HTML for non-trading days is content-validated out). `expiry_calendar`
  is now **1257 docs, all weekday-stamped** (NIFTY 354W/88M, BANKNIFTY 385/108, SENSEX 262/60).
  `report_expiry_gaps.py` (`task expiry:gaps`): NIFTY has **0 unlabellable gaps**. The archive also
  corrected a cadence-guessed date (real NIFTY expiry that week was 2023-04-20, not 2023-04-19).
- **Token refreshed** — the earlier `DH-901` is resolved. **Dhan intraday floor pinned by probe =
  first week of Aug 2020** (2020-07-29 empty → 2020-08-05 = 375 bars/day); no 2019/H1-2020 intraday
  exists. Pre-2020 option data is EOD-only from bhavcopy (~2008).
- **Pilot VERIFIED**: filled 2023-03-16..24 (203,761 bars); the previously-mislabelled 2023-03-23 is
  now 93,718 bars under its correct expiry, with no far-side mislabel across the window.

### Remaining work

- [x] 1.4 — blackout is backfillable.
- [x] 2/2b/2c — tooling complete (ladder, DB calendar, NSE+BSE archive seed, weekday/lot enrichment,
  forward-population, override) with tests (1147 passed).
- [~] 3.1/3.4 — pilot verified; full NIFTY small-gap fill (25 expiries / 202 trading days,
  `only_missing=False`) **in progress**. Verify each `E` in `distinct("expiry_date")` on completion.
- [ ] 3.3 — re-run the NIFTY isolation backtest and compare against the benchmark baseline (after fills).
- [ ] 3.2 — 763-day blackout deferred (calendar already labels its 109 dates; needs explicit
  go-ahead for the multi-hour live write).
