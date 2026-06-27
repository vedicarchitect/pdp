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

The script is idempotent: re-running with the same run-id upserts in place.
Requires: MONGO_URI / MONGO_DB_NAME in .env or environment.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import structlog
from dotenv import load_dotenv

load_dotenv()

from pdp.settings import get_settings  # noqa: E402

log = structlog.get_logger()


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
    a = ap.parse_args()

    if not a.run_dir and not a.wf_csv:
        ap.error("Provide at least --run-dir or --wf-csv.")
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

    if a.run_dir:
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
