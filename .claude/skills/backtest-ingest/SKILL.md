---
name: backtest:ingest
description: Ingest local backtest/runs/<id>/ folders into the Mongo warehouse, verify each landed correctly, and only then remove the local folder. Never removes an unverified run. Use when migrating legacy local run artifacts into the DB-first warehouse.
metadata:
  author: pdp
  version: "1.0"
---

Bulk-ingest legacy local backtest run folders into Mongo, then prune only what's verified.

## Input

Optionally a specific `--run-dir` (single folder) after `/backtest:ingest`. Default: bulk-ingest
every folder under `backend/backtest/runs/`.

## Steps

1. **Ingest without removing first** (always — never combine ingest+remove in one unreviewed step):

   ```
   cd backend && uv run python scripts/ingest_backtest_run.py --bulk-dir backtest/runs
   ```

   This upserts every run's `manifest.json` + `summary.csv` + `equity.csv` + `days/` (incl. the
   full trades/legs detail) into `backtest_runs`/`backtest_days`/`backtest_trades`, then
   independently re-reads Mongo to verify each run's day-count and trade-day-count match what's
   on disk (`_verify_ingested` in the script — never trusts the ingest call's own return value).
   Report per-run OK / NOT VERIFIED, and the final tally.

2. **Show the user the verification tally** before removing anything: N folders, N ingested,
   N verified, any NOT VERIFIED (and why — e.g. day-count mismatch). A NOT VERIFIED run's local
   folder must never be deleted; leave it and flag it for investigation.

3. **Only after the user confirms**, re-run with `--remove` to prune verified folders:

   ```
   cd backend && uv run python scripts/ingest_backtest_run.py --bulk-dir backtest/runs --remove
   ```

   This is a destructive, hard-to-reverse local-filesystem action (even though `backtest/runs/`
   is git-ignored and reproducible) — always get explicit confirmation before passing `--remove`,
   even if the user asked for "ingest and clean up" in the same breath.

4. **Confirm the result**: query a couple of the ingested runs back via
   `GET /api/v1/strangle-backtests/runs/<run_id>` to prove they're queryable, and report the
   final local-folder count remaining (should be 0, or only the NOT VERIFIED ones).
