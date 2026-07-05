"""Unit tests for the ingest-then-remove retention guard in scripts/ingest_backtest_run.py.

Loaded by file path since ``scripts/`` is a directory of runnable scripts, not a package.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "ingest_backtest_run.py"
_spec = importlib.util.spec_from_file_location("ingest_backtest_run", _SCRIPT_PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["ingest_backtest_run"] = _mod
_spec.loader.exec_module(_mod)
_verify_ingested = _mod._verify_ingested


class _FakeCol:
    def __init__(self, doc=None, count=0):
        self._doc = doc
        self._count = count

    def find_one(self, filt, proj=None):
        return self._doc

    def count_documents(self, filt):
        return self._count


class _FakeDb(dict):
    def __getitem__(self, name):
        return super().get(name, _FakeCol())


def _write_run_dir(tmp_path, *, summary_rows=3, trade_days_with_fills=2, header_only_days=1):
    """Build a minimal run folder: summary.csv (N days) + days/<date>/trades.csv per day."""
    run_dir = tmp_path / "strangle_20260101-000000"
    days_dir = run_dir / "days"
    days_dir.mkdir(parents=True)

    with open(run_dir / "summary.csv", "w", newline="") as fh:
        fh.write("date,net\n")
        for i in range(summary_rows):
            fh.write(f"2026-01-0{i + 1},100.0\n")

    trades_header = "time,side,opt_type,strike,qty,price,nifty,cum_lots,avg_entry,leg_pnl,day_pnl,commission,note\n"
    for i in range(trade_days_with_fills):
        d = days_dir / f"2026-01-0{i + 1}"
        d.mkdir()
        (d / "trades.csv").write_text(
            trades_header + "10:15,SELL,PE,20000,65,80.0,20000,1,80.0,,0.0,20.0,open\n",
            encoding="utf-8",
        )
    for i in range(header_only_days):
        idx = trade_days_with_fills + i + 1
        d = days_dir / f"2026-01-0{idx}"
        d.mkdir()
        (d / "trades.csv").write_text(trades_header, encoding="utf-8")  # header only, no fills

    return run_dir


def test_verify_ingested_missing_run_doc_fails(tmp_path):
    run_dir = _write_run_dir(tmp_path, summary_rows=1, trade_days_with_fills=0, header_only_days=0)
    db = _FakeDb(backtest_runs=_FakeCol(doc=None))
    ok, reason = _verify_ingested(db, "strangle_20260101-000000", run_dir)
    assert ok is False
    assert "run doc missing" in reason


def test_verify_ingested_day_count_mismatch_fails(tmp_path):
    run_dir = _write_run_dir(tmp_path, summary_rows=5, trade_days_with_fills=0, header_only_days=0)
    db = _FakeDb(
        backtest_runs=_FakeCol(doc={"run_id": "x"}),
        backtest_days=_FakeCol(count=3),  # fewer than the 5 rows in summary.csv
    )
    ok, reason = _verify_ingested(db, "strangle_20260101-000000", run_dir)
    assert ok is False
    assert "day count mismatch" in reason


def test_verify_ingested_header_only_trades_csv_does_not_count_as_a_trade_day(tmp_path):
    """A day with only a trades.csv header (no fills) must not inflate the expected count.

    Regression guard: an earlier version of this check used file size > 0, which
    false-flagged every header-only day as an unverified trade-day mismatch.
    """
    run_dir = _write_run_dir(tmp_path, summary_rows=3, trade_days_with_fills=2, header_only_days=1)
    db = _FakeDb(
        backtest_runs=_FakeCol(doc={"run_id": "x"}),
        backtest_days=_FakeCol(count=3),
        backtest_trades=_FakeCol(count=2),  # matches the 2 real fill-days, not all 3 day-dirs
    )
    ok, reason = _verify_ingested(db, "strangle_20260101-000000", run_dir)
    assert ok is True, reason


def test_verify_ingested_real_trade_day_shortfall_fails(tmp_path):
    run_dir = _write_run_dir(tmp_path, summary_rows=3, trade_days_with_fills=2, header_only_days=0)
    db = _FakeDb(
        backtest_runs=_FakeCol(doc={"run_id": "x"}),
        backtest_days=_FakeCol(count=3),
        backtest_trades=_FakeCol(count=1),  # one of the two real fill-days didn't land
    )
    ok, reason = _verify_ingested(db, "strangle_20260101-000000", run_dir)
    assert ok is False
    assert "trade-day count mismatch" in reason


def test_verify_ingested_fully_matching_run_passes(tmp_path):
    run_dir = _write_run_dir(tmp_path, summary_rows=2, trade_days_with_fills=2, header_only_days=0)
    db = _FakeDb(
        backtest_runs=_FakeCol(doc={"run_id": "x"}),
        backtest_days=_FakeCol(count=2),
        backtest_trades=_FakeCol(count=2),
    )
    ok, reason = _verify_ingested(db, "strangle_20260101-000000", run_dir)
    assert ok is True
    assert reason == "verified"
