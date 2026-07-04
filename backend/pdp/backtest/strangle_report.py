"""Per-run artifact writer for directional-strangle backtest runs.

DB-first by default (``settings.BACKTEST_ARCHIVE_LOCAL=False``): ``RunWriter`` builds
run/day/trade/decision documents in memory as each day is simulated and upserts them
straight to Mongo (+ OpenSearch dual-sink) via ``BacktestStore`` at ``finalize()`` — no
local files. Every run is captured in the warehouse without ever touching disk.

Set ``archive_local=True`` (or ``BACKTEST_ARCHIVE_LOCAL=1``) to fall back to the legacy
local-folder archive — kept as a short-lived rollback path, not the default::

    backtest/runs/<run_id>/
      manifest.json          run config, window, data coverage, git sha, timing totals
      summary.csv            one row per day (P&L, trades, drawdown, build/sim timing)
      equity.csv             cumulative realized equity by day
      run.log                high-level run log
      days/<YYYY-MM-DD>/
        status.log           every-minute BarStatus trace (score, votes, VIX/PCR, legs, P&L)
        trades.csv           every fill: time, side, type, strike, qty, price, leg/day P&L, comm
        legs.csv             closed-leg records (entry/exit/lots/pnl/reason; incl. hedges)
        day.json             that day's summary + timing

``backtest/runs/`` is git-ignored — legacy-mode artifacts are reproducible, not source.
"""
from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from pdp.backtest.strangle_sim import format_status_line

if TYPE_CHECKING:
    from pdp.backtest.sim import DayResult
    from pdp.backtest.store import BacktestStore
    from pdp.backtest.strangle_config import StrangleConfig
    from pdp.backtest.strangle_sim import BarStatus

log = structlog.get_logger()
_BUCKET_RE = re.compile(r"\[(\w+)\]")


class RunWriter:
    """Accumulates per-day results for one backtest invocation and persists the run.

    DB-first (default): nothing touches disk; ``finalize()`` upserts the run + every
    day/trade/decision doc built in memory straight to ``store``.
    Legacy local-archive mode (``archive_local=True``): unchanged file-based behavior,
    with ``finalize()`` still ingesting the folder into ``store`` when one is given.
    """

    def __init__(self, out_root: str | Path | None, cfg: StrangleConfig, *, run_id: str | None = None,
                 store: BacktestStore | None = None, archive_local: bool | None = None):
        from pdp.settings import get_settings

        self.run_id = run_id or f"strangle_{datetime.now():%Y%m%d-%H%M%S}"
        self.archive_local = (
            get_settings().BACKTEST_ARCHIVE_LOCAL if archive_local is None else archive_local
        )
        self._cfg = cfg
        self._store = store
        self._t0 = time.perf_counter()
        self._eq = 0.0
        self._peak = 0.0
        self._n_days = 0
        self._n_trades = 0

        # DB-first accumulators — built as each day is simulated, upserted at finalize().
        self._day_docs: list[dict[str, Any]] = []
        self._trade_docs: list[dict[str, Any]] = []
        self._decision_docs: list[dict[str, Any]] = []
        self._equity_rets: list[float] = []

        self.root: Path | None = None
        self.days_dir: Path | None = None
        if self.archive_local:
            if out_root is None:
                raise ValueError("out_root is required when archive_local=True")
            self.root = Path(out_root) / self.run_id
            self.days_dir = self.root / "days"
            self.days_dir.mkdir(parents=True, exist_ok=True)

            self._summary_fh = (self.root / "summary.csv").open("w", newline="")
            self._summary = csv.writer(self._summary_fh)
            self._summary.writerow([
                "date", "expiry", "nifty_open", "nifty_close", "nifty_chg", "trades",
                "gross_pnl", "commission", "net", "cum_equity", "drawdown", "halted",
                "build_ms", "sim_ms",
            ])
            self._equity_fh = (self.root / "equity.csv").open("w", newline="")
            self._equity = csv.writer(self._equity_fh)
            self._equity.writerow(["date", "net", "cum_equity", "peak", "drawdown"])

            self._journal_fh = (self.root / "trade_journal.csv").open("w", newline="")
            self._journal = csv.writer(self._journal_fh)
            self._journal.writerow([
                "date", "first_entry", "last_exit", "conditions_matched",
                "gross_pnl", "net_pnl", "cum_equity",
            ])

            self._log_fh = (self.root / "run.log").open("w", encoding="utf-8")

    # -- logging --------------------------------------------------------------- #
    def log(self, msg: str) -> None:
        if self.archive_local:
            line = f"{datetime.now():%H:%M:%S}  {msg}"
            self._log_fh.write(line + "\n")
            self._log_fh.flush()
        else:
            log.info("backtest_run_log", run_id=self.run_id, msg=msg)

    # -- per-day --------------------------------------------------------------- #
    def write_day(self, result: DayResult, trace: list[BarStatus] | None,
                  build_ms: float, sim_ms: float, decisions: list[dict[str, Any]] | None = None) -> None:
        self._eq += result.realized
        self._peak = max(self._peak, self._eq)
        self._equity_rets.append(result.realized)

        from pdp.backtest.store import (
            build_day_doc_from_result,
            build_decision_docs,
            build_trade_doc_from_result,
        )

        if decisions:
            strategy_id = re.split(r"_\d{8}", self.run_id)[0]
            self._decision_docs.extend(build_decision_docs(self.run_id, strategy_id, decisions))

        if not self.archive_local:
            self._day_docs.append(build_day_doc_from_result(
                self.run_id, result, cum_equity=self._eq, peak=self._peak,
                build_ms=build_ms, sim_ms=sim_ms,
            ))
            trade_doc = build_trade_doc_from_result(self.run_id, result)
            if trade_doc is not None:
                self._trade_docs.append(trade_doc)
            self._n_days += 1
            self._n_trades += len(result.trades)
            return

        day_dir = self.days_dir / result.date
        day_dir.mkdir(parents=True, exist_ok=True)

        if trace is not None:
            with (day_dir / "status.log").open("w", encoding="utf-8") as fh:
                for st in trace:
                    fh.write(format_status_line(st) + "\n")

        with (day_dir / "trades.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["time", "side", "opt_type", "strike", "qty", "price", "nifty",
                        "cum_lots", "avg_entry", "leg_pnl", "day_pnl", "commission", "note"])
            for t in result.trades:
                w.writerow([
                    _hhmm(t.bar_time), t.side, t.opt_type, f"{t.strike:.0f}", t.qty,
                    f"{t.price:.2f}", f"{t.nifty:.2f}", t.cum_lots, f"{t.avg_entry:.2f}",
                    ("" if t.leg_pnl is None else f"{t.leg_pnl:.2f}"), f"{t.day_pnl:.2f}",
                    f"{t.commission_inr:.2f}", t.note,
                ])

        with (day_dir / "legs.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["opt_type", "strike", "entry", "exit", "lots", "avg_entry",
                        "exit_px", "leg_pnl", "reason"])
            for lr in result.leg_records:
                w.writerow([
                    lr.opt_type, f"{lr.strike:.0f}", _hhmm(lr.entry_ist), _hhmm(lr.exit_ist),
                    lr.lots, f"{lr.avg_entry:.2f}", f"{lr.exit_px:.2f}",
                    f"{lr.leg_pnl:.2f}", lr.reason,
                ])

        # trade_journal.csv: first open entry, last close, bias buckets matched, P&L
        open_trades = [t for t in result.trades if t.side == "SELL" and "open " in t.note]
        first_entry = _hhmm(min((t.bar_time for t in open_trades), default=None))
        last_exit = _hhmm(max((t.bar_time for t in result.trades), default=None)) if result.trades else ""
        conditions = list(dict.fromkeys(
            m.group(1)
            for t in open_trades
            for m in [_BUCKET_RE.search(t.note)]
            if m
        ))

        dd = self._peak - self._eq
        day_json: dict[str, Any] = {
            "date": result.date, "expiry": result.expiry,
            "nifty_open": result.nifty_open, "nifty_close": result.nifty_close,
            "nifty_chg": result.nifty_chg, "trades": len(result.trades),
            "legs_closed": len(result.leg_records), "gross_pnl": result.gross_pnl,
            "commission": result.commission, "net": result.realized,
            "cum_equity": self._eq, "drawdown": dd, "halted": result.done_reason or "",
            "timing_ms": {"build": round(build_ms, 1), "sim": round(sim_ms, 1)},
        }
        (day_dir / "day.json").write_text(json.dumps(day_json, indent=2), encoding="utf-8")

        self._summary.writerow([
            result.date, result.expiry, f"{result.nifty_open:.2f}", f"{result.nifty_close:.2f}",
            f"{result.nifty_chg:+.2f}", len(result.trades), f"{result.gross_pnl:.2f}",
            f"{result.commission:.2f}", f"{result.realized:.2f}", f"{self._eq:.2f}",
            f"{dd:.2f}", result.done_reason or "", f"{build_ms:.1f}", f"{sim_ms:.1f}",
        ])
        self._summary_fh.flush()
        self._equity.writerow([result.date, f"{result.realized:.2f}", f"{self._eq:.2f}",
                               f"{self._peak:.2f}", f"{dd:.2f}"])
        self._equity_fh.flush()
        self._journal.writerow([
            result.date, first_entry, last_exit, " | ".join(conditions),
            f"{result.gross_pnl:.2f}", f"{result.realized:.2f}", f"{self._eq:.2f}",
        ])
        self._journal_fh.flush()
        self._n_days += 1
        self._n_trades += len(result.trades)

    # -- finalize -------------------------------------------------------------- #
    def finalize(self, *, window: dict[str, Any], metrics: dict[str, Any],
                 extra: dict[str, Any] | None = None) -> Path | None:
        wall_s = time.perf_counter() - self._t0

        if not self.archive_local:
            from pdp.backtest.store import build_run_doc

            manifest = {
                "run_id": self.run_id,
                "generated": datetime.now(UTC).isoformat(timespec="seconds"),
                "config": self._safe_cfg(),
                "window": window,
                "metrics": metrics,
            }
            run_doc = build_run_doc(manifest, kind="single", equity_rets=self._equity_rets)
            if self._store is not None:
                self._store.upsert_run(run_doc)
                self._store.upsert_days(self._day_docs)
                self._store.upsert_trades(self._trade_docs)
                self._store.upsert_decisions(self._decision_docs)
            log.info(
                "backtest_run_persisted", run_id=self.run_id, days=self._n_days,
                trades=self._n_trades, decisions=len(self._decision_docs),
                wall_seconds=round(wall_s, 1), archive_local=False,
            )
            return None

        manifest = {
            "run_id": self.run_id,
            "generated": datetime.now().isoformat(timespec="seconds"),
            "config": self._safe_cfg(),
            "window": window,
            "metrics": metrics,
            "totals": {"days": self._n_days, "trades": self._n_trades,
                       "wall_seconds": round(wall_s, 1)},
            **(extra or {}),
        }
        (self.root / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str),
                                                 encoding="utf-8")
        self.log(f"done: {self._n_days} days, {self._n_trades} trades, {wall_s:.1f}s wall")
        self._summary_fh.close()
        self._equity_fh.close()
        self._journal_fh.close()
        self._log_fh.close()
        if self._store is not None:
            try:
                self._store.ingest_run_folder(self.root, kind="single")
                if self._decision_docs:
                    self._store.upsert_decisions(self._decision_docs)
            except Exception as exc:
                # Dual-sink failure must not abort the run
                structlog.get_logger().warning("backtest_mongo_sink_failed", error=str(exc))
        return self.root

    def _safe_cfg(self) -> dict[str, Any]:
        try:
            return self._cfg.to_dict()
        except Exception:
            return asdict(self._cfg)


def _hhmm(dt: datetime | None) -> str:
    return "" if dt is None else f"{dt:%H:%M}"
