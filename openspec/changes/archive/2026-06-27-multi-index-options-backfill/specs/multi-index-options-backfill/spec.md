## ADDED Requirements

### Requirement: Per-symbol option backfill CLI

The `scripts/backfill_options_gap.py` CLI SHALL accept a `--symbol NIFTY|BANKNIFTY|SENSEX` flag (default `NIFTY`) that selects the underlying index to backfill. When `--symbol BANKNIFTY` is supplied the script SHALL use security ID 25, strike step 100, and the BANKNIFTY expiry calendar. When `--symbol SENSEX` is supplied it SHALL use security ID 51, strike step 100, and the SENSEX expiry calendar. The existing `--from`, `--to`, `--codes`, `--band`, `--only-missing`, and `--dry-run` flags SHALL continue to work for all symbols.

#### Scenario: NIFTY default is unchanged

- **WHEN** `task backfill:options -- --from 2026-05-23 --only-missing` is run (no `--symbol`)
- **THEN** the backfill proceeds for NIFTY (sid 13, step 50) exactly as before this change

#### Scenario: BANKNIFTY backfill selects correct config

- **WHEN** `task backfill:options:banknifty -- --from 2026-05-23 --only-missing` is run
- **THEN** Dhan calls use security ID 25, strike derivation rounds to the nearest 100, and stored docs have `underlying = "BANKNIFTY"` and `security_id = "25"`

#### Scenario: dry-run reports correct symbol

- **WHEN** `task backfill:options:sensex -- --from 2026-05-23 --dry-run` is run
- **THEN** the log reports `underlying=SENSEX`, `sid=51`, `step=100` and exits without making Dhan API calls

---

### Requirement: Parameterised gap_backfill core

The `backfill_gaps()` function in `src/pdp/options/gap_backfill.py` SHALL accept `underlying: str`, `underlying_sid: int`, and `strike_step: int` parameters so any caller (CLI or self-healing loop) can supply the correct values for a given index. Module-level hardcoded constants `UNDERLYING`, `UNDERLYING_SID`, and `STEP` SHALL be removed or replaced by defaults that callers must explicitly pass.

#### Scenario: backfill_gaps uses supplied step for strike derivation

- **WHEN** `backfill_gaps(..., underlying="BANKNIFTY", underlying_sid=25, strike_step=100)` is called
- **THEN** each option bar's strike is derived as `round(spot / 100) * 100 + offset * 100`, not the NIFTY-specific 50-point step

---

### Requirement: Generalised expiry calendar

The expiry calendar used by the gap-fill core SHALL be loadable per symbol via a `SymbolExpiryCalendar` factory or equivalent so that `NiftyExpiryCalendar` is not the only supported type. Pre-built cache files SHALL exist at `data/expiry/banknifty_expiries.json` and `data/expiry/sensex_expiries.json` before BANKNIFTY/SENSEX backfills can run. If a cache file for the requested symbol is missing the CLI SHALL exit with a clear error message naming the missing file.

#### Scenario: Missing expiry cache exits cleanly

- **WHEN** `--symbol BANKNIFTY` is requested but `data/expiry/banknifty_expiries.json` does not exist
- **THEN** the CLI logs an error naming the missing file and exits with code 1 (no partial backfill)

---

### Requirement: Taskfile convenience tasks

`Taskfile.yml` SHALL define `backfill:options:banknifty` and `backfill:options:sensex` tasks that pass `--symbol BANKNIFTY` and `--symbol SENSEX` respectively to `backfill_options_gap.py`. The existing `backfill:options` task SHALL remain unchanged (NIFTY default).

#### Scenario: Taskfile task passes correct symbol

- **WHEN** `task backfill:options:banknifty -- --from 2026-05-23` is run
- **THEN** the underlying script receives `--symbol BANKNIFTY` as an argument
