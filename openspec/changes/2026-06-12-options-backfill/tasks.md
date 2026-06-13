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
- [ ] 3.2 Verify whether Dhan serves expired-contract bars by symbol/security_id; record the finding
  (deferred — requires `DHAN_CLIENT_ID`/`DHAN_ACCESS_TOKEN`; live gap-fill run also needs creds)
- [ ] 3.3 Deprecate `scripts/backfill_expired_options.py` (superseded)

## 4. Validation + dedup proof

- [x] 4.1 `scripts/validate_options_warehouse.py` — Abi↔Mongo counts, OHLC sanity,
  zero-dup assertion, `expiry_date` plausibility (`ts.date ≤ expiry_date`), label↔strike consistency;
  non-zero exit on any failure (all gates pass + reconciliation 83872=83872)
- [x] 4.2 Two-producer dedup test: same `(contract, ts)` via two sources → exactly one doc
  (`tests/test_option_bars_collection.py`, real-Mongo integration, first-write-wins)

## 5. Validate + archive

- [x] 5.1 `openspec validate --strict 2026-06-12-options-backfill` → exits 0
- [x] 5.2 Migrate one month + run validation (all gates pass) before any full-history run
- [ ] 5.3 `openspec archive 2026-06-12-options-backfill` (after full-history migration + live gap-fill)
