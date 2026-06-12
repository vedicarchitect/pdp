# Design — Filtered instrument snapshots

## Filter scope

Snapshot rows where `underlying ∈ {NIFTY, BANKNIFTY, SENSEX}`, plus the three index instruments
themselves (the IDX_I index rows, which have no `underlying`). NIFTY/BANKNIFTY live on NSE
(`NSE_FNO` / `IDX_I`); SENSEX lives on BSE (`BSE_FNO` / `IDX_I`). The set SHALL be a single
constant/setting (`SNAPSHOT_UNDERLYINGS`) so widening scope is a one-line change.

## Storage

Date-stamped CSV under `data/masters/YYYY-MM-DD.csv`, matching the documented
`security-master-snapshot` plan. Rationale:

- A flat CSV per day is trivial to read in the backtest with Polars/pandas and needs no schema
  migration.
- Filtered to three underlyings, a day's file is small (thousands of rows, not 100k+).
- Re-running a given day overwrites that day's file → idempotent.

Alternative considered: a versioned DB table (`instrument_snapshots` with a `snapshot_date`
column). Rejected for now — adds a migration and a query layer for what is essentially
append-only cold history that the backtest reads sequentially. Revisit if we need indexed
cross-date queries.

## Historical lookup

```
load_master_for_date(d):
    files = sorted(data/masters/*.csv)
    valid = [f for f in files if date(f.stem) <= d]
    if not valid: raise / fall back to expired_options_data
    return read(valid[-1])
```

The "latest ≤ date" rule means a date with no exact snapshot uses the most recent prior one,
which still contains the contracts that were active on the target date (they had not yet expired).

## Scheduling

Run once per trading day before market open (≈08:45 IST) via the existing loader entrypoint,
reusing the already-fetched master CSV rather than a second download. The earliest reliable
snapshot is the first day the job runs; for dates before that, the `expired_options_data`
Mongo-warehouse fallback remains in place (see `expired-options-mongo-warehouse`).
