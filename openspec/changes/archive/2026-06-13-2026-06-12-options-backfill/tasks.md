## 1. Abi DuckDB → option_bars migrator

- [x] 1.1 `scripts/migrate_abi_options.py` — read `nifty.db` `expired_options_ohlcv` read-only;
  scope `WEEK` codes 1&2 / ATM±10 / CE+PE (`--include-monthly`); IST→UTC; resolve `expiry_date`
  (calendar) + `trading_symbol` (symbols); upsert `source=abi`; `--from/--to`, `--codes`, `--dry-run`
- [x] 1.2 Chunked + restartable (per series / per month); progress logging via structlog
- [x] 1.3 Smoke: `--dry-run` counts match the scoped DuckDB query; migrate one month
  (83,872 bars 2026-04-01..08; re-run inserted 0; expiries 2026-04-07/2026-04-13 holiday-shifted)

## 2. NIFTY spot migrator

- [x] 2.1 `scripts/migrate_spot_bars.py` — Abi `nifty_spot_1m`/`spot_1m`
  → `market_bars` (sid `13`, `1m`), deduped by `ts` (check-then-insert);
  912,936 bars migrated (2017→2026), re-run idempotent

## 3. Dhan gap-fill

- [x] 3.1 `scripts/backfill_options_gap.py` — 2026-05-23→yesterday into `option_bars`; rolling API
  + calendar to derive `strike` from per-minute spot; carry `strike`+`trading_symbol`; idempotent
  (`--dry-run` verified offline: 14 trading days × codes 1,2 × ATM±10 × CE/PE = 1,176 planned fetches)
- [x] 3.2 Verify whether Dhan serves expired-contract bars by symbol/security_id; record the finding.
  **FINDING (2026-06-13): YES.** The rolling-option `expired_options_data` path serves expired NIFTY
  bars for the recent tail — gap-fill inserted real 1m bars for every trade day 2026-05-13→2026-06-12
  (15,375–31,498 docs/day). `intraday_minute_data` for the NIFTY spot returns a string/empty payload
  for the most-recent/incomplete days; `spot_by_minute` now skips those gracefully (`gap_fill_spot_unavailable`).
- [x] 3.3 Deprecate `scripts/backfill_expired_options.py` (superseded) — DEPRECATED header added; file retained for reference only

## 4. Validation + dedup proof

- [x] 4.1 `scripts/validate_options_warehouse.py` — Abi↔Mongo counts, OHLC sanity,
  zero-dup assertion, `expiry_date` plausibility (`ts.date ≤ expiry_date`), label↔strike consistency;
  non-zero exit on any failure (all gates pass + reconciliation 83872=83872)
- [x] 4.2 Two-producer dedup test: same `(contract, ts)` via two sources → exactly one doc
  (`tests/test_option_bars_collection.py`, real-Mongo integration, first-write-wins)

## 5. Validate + archive

- [x] 5.1 `openspec validate --strict 2026-06-12-options-backfill` → exits 0
- [x] 5.2 Migrate one month + run validation (all gates pass) before any full-history run
- [x] 5.3 `openspec archive 2026-06-12-options-backfill` (after full-history migration + live gap-fill).
  Post-fill `validate_options_warehouse.py` exits 0 — all 7 gates pass over 27,243,044 docs
  (OHLC 0, values 0, dups 0, expiry-plausibility 0, label 0, thin-abi 0, abi_post_cutoff 0;
  dhan_api_pre_cutoff=548,360 logged for the 05-13..05-22 fill, cutoff=2026-05-23).

## 6. Coverage audit + multi-year holidays (data-availability)

- [x] 6.1 `scripts/audit_options_coverage.py` — read-only per-month docs/trade-days + `source` split +
  gap-day scan (reuses `days_missing`); collapses gaps into ranges; `--out` JSON.
- [x] 6.2 `data/calendars/nse_holidays_2023_2026.json` (2023-2025 reconciled against actual
  `option_bars` trade-days; 2026 from Abi file); `settings.NSE_HOLIDAYS_JSON` default repointed.
- [x] 6.3 Audit run 2023-01-01..2026-06-13 (source=abi only; 26.38M docs). **Findings / gap inventory:**
  - Solid 1m coverage 2023-01 → 2026-05-12; partial 2020-08..12; **2021 & 2022 entirely absent**.
  - Interior data gaps: **2024-12-26..31**, **2025-12-29..31** (year-end), **2026-04-28..30,
    05-06, 05-13..05-22** (Abi export tapered before cutoff). 33 gap days total in range.
  - Post-cutoff tail **2026-05-23 → present**: not present (gap-fill never run; 0 `dhan_api` docs).
- [x] 3.2 (carried) Probe Dhan rolling-option history depth for the gap ranges above, then fill the
  Dhan-served range via `backfill_options_gap.py --only-missing`; ranges Dhan won't serve fall back
  to re-running `migrate_abi_options.py`.
  **DONE (2026-06-13):** Root cause of the post-cutoff tail gap was the expiry calendar
  (`data/expiry/nifty_expiries.json`) ending 2026-05-12 → `resolve_expiry` returned None → gap-fill
  hard-skipped every recent day. Extended the calendar forward using Dhan `expiry_list`
  (authoritative future expiries from 2026-06-16) + the 4 expired plain-Tuesday weeklies
  (05-19/05-26/06-02/06-09); WEEK 171→193, MONTH 59→74, both now to 2030-12-31.
  Ran `backfill_options_gap.py --from 2026-05-13 --to 2026-06-13 --only-missing`: filled every
  trade day 2026-05-13→2026-06-12 (15k–31k docs/day, `source=dhan_api`); re-run reports
  `gap_days=[] gaps=0 scanned=22` (idempotent, tail fully covered).
  Hardened `spot_by_minute` to skip days where Dhan returns a non-dict spot payload
  (`gap_fill_spot_unavailable`) instead of crashing the run.
  Verified `backtest_multiday.py --days 7`: 0 `opt_bars_no_warehouse_data` / `[expiry:fallback]`
  warnings, 215 trades fire, PF 2.40. No Abi fallback needed for this range — Dhan served it all.
