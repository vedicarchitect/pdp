## Why

Dhan's scrip master (`api-scrip-master-detailed.csv`) lists **only currently active** contracts.
Once a weekly/monthly option expires, its row disappears from the CSV and from the `instruments`
table — so a backtest of any past date can no longer resolve the correct expired-contract
`security_id`. This is the root cause of the silent wrong-expiry bug in `backtest_multiday.py`
(it falls back to a later expiry, producing unreliable near-expiry option prices). A daily
snapshot of the master fixes it permanently: given a historical `trade_date`, look up the
snapshot taken on or before that date.

Storing the **entire** master daily is wasteful (>100k rows/day). For now we only trade NIFTY,
BANKNIFTY, and SENSEX, so the snapshot SHALL be **filtered to those three underlyings** (their
index rows plus their F&O contracts). The filter is intentionally scoped "as of now" and can be
widened later without changing the mechanism.

## What Changes

- Add a **daily filtered instrument snapshot**: persist the scrip-master rows whose underlying is
  one of `NIFTY`, `BANKNIFTY`, `SENSEX` (plus those index instruments themselves) to a
  date-stamped store (`data/masters/YYYY-MM-DD.csv`), once per trading day before market open.
- Add a **historical lookup** that, given a date, returns the snapshot taken on or before that
  date (latest ≤ date), so backtests resolve the expiry/strike/security_id that was active then.
- The allowed-underlyings set SHALL be configurable (a constant/setting), defaulting to the three
  above, so the scope can expand without a code rewrite.
- Snapshotting is idempotent per day (re-running the same day overwrites that day's file).

## Capabilities

### Modified Capabilities

- `instrument-registry`: gains daily filtered snapshots and date-based historical lookup.

## Impact

- Builds on the existing master fetch/loader in the registry; reuses the already-downloaded CSV.
- Unblocks correct expired-contract resolution in `backtest_multiday.py` for NIFTY/BANKNIFTY/SENSEX.
- Storage is small (three underlyings' contracts per day); no change to the live `instruments` table.
- See memory `security-master-snapshot` and `nifty-expiry-instruments` for background.
