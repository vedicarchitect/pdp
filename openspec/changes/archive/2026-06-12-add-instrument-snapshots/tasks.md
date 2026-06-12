## 1. Snapshot writer

- [x] 1.1 Add `SNAPSHOT_UNDERLYINGS` (settings, default `["NIFTY","BANKNIFTY","SENSEX"]`) + module default `DEFAULT_SNAPSHOT_UNDERLYINGS`
- [x] 1.2 `filter_for_underlyings` + `create_snapshot`/`write_snapshot` → `data/masters/<YYYY-MM-DD>.csv` (keeps the underlyings' derivatives + their index rows)
- [x] 1.3 CLI reuses the already-downloaded master CSV (single `download_dhan_master`); per-day write overwrites (idempotent)
- [x] 1.4 CLI entrypoint `pdp instruments snapshot [--date] [--dir]`

## 2. Historical lookup

- [x] 2.1 `load_master_for_date(d)` → latest snapshot with date ≤ `d`; raises `FileNotFoundError` when none (documented fallback)
- [x] 2.2 `resolve_instrument(...)` resolves `security_id` (+ expiry/strike/option_type) for an underlying + date from the snapshot

## 3. Scheduling

- [x] 3.1 Pre-market (≈08:45 IST) scheduled run documented in `design.md`; run `pdp instruments snapshot` daily (Windows task / cron)

## 4. Tests

- [x] 4.1 Filter keeps only the three underlyings + their index rows
- [x] 4.2 `load_master_for_date` picks the latest snapshot ≤ date; raises when absent
- [x] 4.3 Re-running the same day overwrites (idempotent), row counts stable

## 5. Validation

- [x] 5.1 `openspec validate add-instrument-snapshots --strict`
