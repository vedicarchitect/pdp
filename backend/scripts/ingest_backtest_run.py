"""Ingest a backtest run folder (or walk-forward CSV) into the MongoDB warehouse.

Usage:
  # Ingest a single/sweep run from its artifacts folder
  python scripts/ingest_backtest_run.py --run-dir backtest/runs/strangle_20260626-120127

  # Ingest a walk-forward CSV (no run folder)
  python scripts/ingest_backtest_run.py --wf-csv backtest/runs/wf_scale2_hedge.csv \
      --run-id wf_scale2_hedge

  # Ingest a run folder AND attach walk-forward fold data
  python scripts/ingest_backtest_run.py \
      --run-dir backtest/runs/strangle_20260626-120127 \
      --wf-csv backtest/runs/wf_scale2_hedge.csv \
      --kind walkforward

  # Bulk-ingest every run folder under backtest/runs/, verify each against Mongo,
  # then remove local folders that are confirmed present (never removes unverified)
  python scripts/ingest_backtest_run.py --bulk-dir backtest/runs --remove

The script is idempotent: re-running with the same run-id upserts in place.
Requires: MONGO_URI / MONGO_DB_NAME in .env or environment.
"""
from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import structlog
from dotenv import load_dotenv

load_dotenv()

from pdp.settings import get_settings  # noqa: E402

log = structlog.get_logger()


def _verify_ingested(db, run_id: str, run_dir: Path) -> tuple[bool, str]:
    """Confirm a run's data actually landed in Mongo before its local folder is removed.

    Never trusts the ingest call's return value alone — re-reads the warehouse.
    """
    run_doc = db["backtest_runs"].find_one({"run_id": run_id}, {"_id": 1})
    if run_doc is None:
        return False, "run doc missing from backtest_runs"

    summary_path = run_dir / "summary.csv"
    if summary_path.exists():
        with open(summary_path, newline="") as fh:
            expected_days = sum(1 for _ in csv.DictReader(fh))
        actual_days = db["backtest_days"].count_documents({"run_id": run_id})
        if expected_days and actual_days < expected_days:
            return False, f"day count mismatch: expected {expected_days}, found {actual_days}"

    days_dir = run_dir / "days"
    if days_dir.exists():
        def _has_fills(trades_csv: Path) -> bool:
            with open(trades_csv, newline="") as fh:
                return any(True for _ in csv.DictReader(fh))

        expected_trade_days = sum(
            1 for d in days_dir.iterdir()
            if d.is_dir() and (d / "trades.csv").exists()
            and _has_fills(d / "trades.csv")
        )
        actual_trade_days = db["backtest_trades"].count_documents({"run_id": run_id})
        if expected_trade_days and actual_trade_days < expected_trade_days:
            return False, f"trade-day count mismatch: expected {expected_trade_days}, found {actual_trade_days}"

    return True, "verified"


def _bulk_ingest(store, db, bulk_dir: Path, *, remove: bool) -> int:
    run_dirs = sorted(
        d for d in bulk_dir.iterdir()
        if d.is_dir() and (d / "manifest.json").exists()
    )
    if not run_dirs:
        print(f"No run folders with manifest.json found under {bulk_dir}")
        return 0

    ingested = verified = removed = failed = 0
    for run_dir in run_dirs:
        run_id = run_dir.name
        try:
            summary = store.ingest_run_folder(run_dir, kind="single")
            ingested += 1
        except Exception as exc:
            print(f"  FAILED ingest {run_id}: {exc}")
            failed += 1
            continue

        ok, reason = _verify_ingested(db, run_id, run_dir)
        if not ok:
            print(f"  NOT VERIFIED {run_id}: {reason} — local folder kept")
            continue
        verified += 1
        print(f"  OK {run_id}: {summary}")

        if remove:
            shutil.rmtree(run_dir)
            removed += 1
            print(f"  removed local folder: {run_dir}")

    print(f"\nBulk ingest: {len(run_dirs)} folders, {ingested} ingested, "
          f"{verified} verified, {removed} removed, {failed} failed.")
    return 0 if failed == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingest backtest runs into the MongoDB warehouse.")
    ap.add_argument("--run-dir", default=None,
                    help="Path to a backtest/runs/<id>/ folder (has manifest.json).")
    ap.add_argument("--wf-csv", default=None,
                    help="Path to a walk-forward fold CSV (per-fold IS/OOS metrics).")
    ap.add_argument("--run-id", default=None,
                    help="Override / supply run_id (required when --wf-csv is used alone).")
    ap.add_argument("--kind", default="single", choices=["single", "sweep", "walkforward"],
                    help="Run kind (default: single; auto-set to walkforward if folds present).")
    ap.add_argument("--bulk-dir", default=None,
                    help="Ingest every run folder directly under this directory (e.g. backtest/runs).")
    ap.add_argument("--remove", action="store_true", default=False,
                    help="With --bulk-dir: remove each local run folder once verified present in "
                         "Mongo. Never removes a folder that fails verification.")
    a = ap.parse_args()

    if not a.run_dir and not a.wf_csv and not a.bulk_dir:
        ap.error("Provide at least --run-dir, --wf-csv, or --bulk-dir.")
    if a.wf_csv and not a.run_dir and not a.run_id:
        ap.error("--wf-csv without --run-dir requires --run-id.")

    from pymongo import MongoClient  # noqa: PLC0415

    from pdp.backtest.store import BacktestStore  # noqa: PLC0415

    s = get_settings()
    client = MongoClient(s.MONGO_URI)
    db = client[s.MONGO_DB_NAME]
    store = BacktestStore(
        col_runs=db["backtest_runs"],
        col_days=db["backtest_days"],
        col_folds=db["backtest_folds"],
        col_trades=db["backtest_trades"],
    )

    rc = 0
    if a.bulk_dir:
        bulk_dir = Path(a.bulk_dir)
        if not bulk_dir.exists():
            print(f"ERROR: bulk directory not found: {bulk_dir}", file=sys.stderr)
            client.close()
            return 1
        rc = _bulk_ingest(store, db, bulk_dir, remove=a.remove)
    elif a.run_dir:
        run_dir = Path(a.run_dir)
        if not run_dir.exists():
            print(f"ERROR: run directory not found: {run_dir}", file=sys.stderr)
            client.close()
            return 1
        summary = store.ingest_run_folder(
            run_dir,
            kind=a.kind,
            folds_csv=a.wf_csv,
        )
        print(f"Ingested run: {summary}")
    elif a.wf_csv:
        summary = store.ingest_wf_csv(a.wf_csv, run_id=a.run_id or Path(a.wf_csv).stem)
        print(f"Ingested walk-forward: {summary}")

    client.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
