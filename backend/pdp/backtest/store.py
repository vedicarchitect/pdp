"""Backtest warehouse store — document builders + idempotent upsert for the four Mongo
collections: `backtest_runs`, `backtest_days`, `backtest_folds`, `backtest_trades`.

Both the ingest script (sync pymongo) and the RunWriter dual-sink use this module.
API routes query the Motor async collections directly (no wrapping needed here).
"""
from __future__ import annotations

import csv
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

_TRADING_DAYS_PER_YEAR = 252

# Verdict thresholds — single source of truth. `backtest/strangle_walkforward.py`
# imports these instead of re-declaring literals so the printed verdict, the stored
# verdict, and the promotion-evidence breakdown can never disagree.
WF_PASS_NET = 0
WF_PASS_PF = 1.2
WF_PASS_SHARPE = 0.5
WF_PASS_POS_FRAC = 0.6
# Back-compat aliases (module-private names used elsewhere in this file).
_WF_PASS_NET = WF_PASS_NET
_WF_PASS_PF = WF_PASS_PF
_WF_PASS_SHARPE = WF_PASS_SHARPE
_WF_PASS_POS_FRAC = WF_PASS_POS_FRAC


def verdict_breakdown(stitched_oos: dict[str, Any]) -> dict[str, Any]:
    """Per-threshold PASS/actual breakdown for a stitched-OOS summary (promotion evidence)."""
    net = _safe_float(stitched_oos.get("net")) or 0.0
    pf = _safe_float(stitched_oos.get("profit_factor")) or 0.0
    sharpe = _safe_float(stitched_oos.get("sharpe")) or 0.0
    folds = int(stitched_oos.get("folds") or 0)
    positive_folds = int(stitched_oos.get("positive_folds") or 0)
    pos_frac = (positive_folds / folds) if folds else 0.0
    checks = {
        "net": {"actual": net, "threshold": WF_PASS_NET, "pass": net > WF_PASS_NET},
        "profit_factor": {"actual": pf, "threshold": WF_PASS_PF, "pass": pf > WF_PASS_PF},
        "sharpe": {"actual": sharpe, "threshold": WF_PASS_SHARPE, "pass": sharpe > WF_PASS_SHARPE},
        "positive_fold_fraction": {
            "actual": pos_frac, "threshold": WF_PASS_POS_FRAC, "pass": pos_frac >= WF_PASS_POS_FRAC,
        },
    }
    return {
        "checks": checks,
        "all_pass": all(c["pass"] for c in checks.values()),
        "positive_folds": positive_folds,
        "folds": folds,
    }


def single_run_verdict(metrics: dict[str, Any], computed_sharpe: float | None = None) -> str:
    """Compute PASS/REVIEW for a single run using its headline metrics."""
    pseudo_oos = {
        "net": _safe_float(metrics.get("net")) or 0.0,
        "profit_factor": _safe_float(metrics.get("profit_factor")) or 0.0,
        "sharpe": computed_sharpe if computed_sharpe is not None else (_safe_float(metrics.get("sharpe")) or 0.0),
        "folds": 1,
        "positive_folds": 1,
    }
    return "PASS" if verdict_breakdown(pseudo_oos)["all_pass"] else "REVIEW"


def _sharpe_from_rets(rets: list[float]) -> float | None:
    n = len(rets)
    if n < 2:
        return None
    mean = sum(rets) / n
    var = sum((x - mean) ** 2 for x in rets) / (n - 1)
    std = math.sqrt(var) if var > 0 else 0.0
    return (mean / std * math.sqrt(_TRADING_DAYS_PER_YEAR)) if std > 0 else None


def _safe_float(v: Any) -> float | None:
    try:
        f = float(v)
        return None if math.isinf(f) or math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _ship_backtest(kind: str, doc: dict[str, Any]) -> None:
    """Dual-sink a backtest document to OpenSearch (no-op when indexer inactive — e.g. scripts)."""
    from pdp.observability.indexer import get_active_indexer

    indexer = get_active_indexer()
    if indexer is None:
        return
    from pdp.observability import sinks

    if kind == "run":
        d, did = sinks.backtest_run_doc(doc)
        indexer.enqueue(sinks.BACKTEST_RUNS, d, did)
    elif kind == "day":
        d, did = sinks.backtest_day_doc(doc)
        indexer.enqueue(sinks.BACKTEST_DAYS, d, did)
    elif kind == "trade":
        d, did = sinks.backtest_trade_doc(doc)
        indexer.enqueue(sinks.BACKTEST_TRADES, d, did)
    elif kind == "decision":
        d, did = sinks.backtest_decision_doc(doc)
        indexer.enqueue(sinks.BACKTEST_DECISIONS, d, did)
    elif kind == "promotion":
        d, did = sinks.backtest_promotion_doc(doc)
        indexer.enqueue(sinks.BACKTEST_PROMOTIONS, d, did)


# ── Document builders ─────────────────────────────────────────────────────────


def build_run_doc(
    manifest: dict[str, Any],
    *,
    kind: str = "single",
    equity_rets: list[float] | None = None,
    verdict: str | None = None,
    stitched_oos: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a `backtest_runs` document from a manifest dict."""
    raw_metrics = manifest.get("metrics", {})
    sharpe = _safe_float(raw_metrics.get("sharpe")) or (
        _sharpe_from_rets(equity_rets) if equity_rets else None
    )
    net = _safe_float(raw_metrics.get("net"))
    calmar: float | None = None
    max_dd = _safe_float(raw_metrics.get("max_dd")) or 0.0
    if net is not None and max_dd and max_dd > 0:
        calmar = net / max_dd

    run_id = manifest["run_id"]
    # Derive strategy_id from run_id prefix (e.g. "strangle" from "strangle_20260626-120127")
    strategy_id = re.split(r"_\d{8}", run_id)[0]
    config = manifest.get("config", {})

    from pdp.strategy.unified_registry import canonical_id
    canonical_strategy_id = canonical_id(strategy_id, config.get("underlying"))

    doc: dict[str, Any] = {
        "run_id": run_id,
        "kind": kind,
        "underlying": (config.get("underlying") or "").upper(),
        "strategy_id": strategy_id,
        "canonical_strategy_id": canonical_strategy_id,
        "config": config,
        "window": manifest.get("window", {}),
        "metrics": {
            "net": net,
            "profit_factor": _safe_float(raw_metrics.get("profit_factor")),
            "win_rate": _safe_float(raw_metrics.get("win_rate")),
            "max_dd": _safe_float(raw_metrics.get("max_dd")),
            "sharpe": sharpe,
            "calmar": calmar,
            "trades": int(raw_metrics.get("trades", 0)),
            "halted": int(raw_metrics.get("halted", 0)),
            "days": int(raw_metrics.get("days", 0)),
        },
        "git_sha": manifest.get("git_sha"),
        "status": "complete",
        "promotion_state": "none",
        "verdict": verdict if verdict is not None else single_run_verdict(raw_metrics, sharpe),
        "created_at": datetime.fromisoformat(manifest["generated"]).replace(tzinfo=UTC)
        if manifest.get("generated")
        else datetime.now(UTC),
    }
    if stitched_oos:
        doc["stitched_oos"] = stitched_oos
    return doc


def build_day_docs(
    run_id: str,
    summary_path: str | Path,
    equity_path: str | Path,
    days_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Build `backtest_days` documents by merging summary.csv and equity.csv.

    When *days_dir* is supplied, each document also carries a ``status_log``
    list of strings (one per bar) read from ``days/<date>/status.log``.
    """
    equity_by_date: dict[str, dict[str, Any]] = {}
    with open(equity_path, newline="") as fh:
        for row in csv.DictReader(fh):
            equity_by_date[row["date"]] = row

    docs: list[dict[str, Any]] = []
    with open(summary_path, newline="") as fh:
        for row in csv.DictReader(fh):
            d = row["date"]
            eq = equity_by_date.get(d, {})

            status_log: list[str] = []
            if days_dir is not None:
                status_path = Path(days_dir) / d / "status.log"
                if status_path.exists():
                    status_log = status_path.read_text(encoding="utf-8").splitlines()

            docs.append({
                "run_id": run_id,
                "date": d,
                "expiry": row.get("expiry", ""),
                "nifty_open": _safe_float(row.get("nifty_open")),
                "nifty_close": _safe_float(row.get("nifty_close")),
                "nifty_chg": _safe_float(row.get("nifty_chg")),
                "trades": int(row.get("trades") or 0),
                "gross_pnl": _safe_float(row.get("gross_pnl")),
                "commission": _safe_float(row.get("commission")),
                "net": _safe_float(row.get("net")),
                "cum_equity": _safe_float(eq.get("cum_equity") or row.get("cum_equity")),
                "peak": _safe_float(eq.get("peak")),
                "drawdown": _safe_float(row.get("drawdown")),
                "halted": row.get("halted", ""),
                "build_ms": _safe_float(row.get("build_ms")),
                "sim_ms": _safe_float(row.get("sim_ms")),
                "status_log": status_log,
            })
    return docs


def build_fold_docs(
    run_id: str,
    folds_csv_path: str | Path,
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    """Parse a walk-forward CSV into fold documents + stitched-OOS summary + verdict.

    Returns (fold_docs, stitched_oos_metrics, verdict).
    """
    rows: list[dict[str, Any]] = []
    with open(folds_csv_path, newline="") as fh:
        for r in csv.DictReader(fh):
            rows.append(r)

    fold_docs: list[dict[str, Any]] = []
    oos_nets: list[float] = []
    oos_trades: int = 0
    oos_days: int = 0
    oos_gp = oos_gl = 0.0
    oos_wins = 0
    oos_rets: list[float] = []

    for r in rows:
        fold_idx = int(r["fold"])
        is_pf_raw = r.get("is_pf", "0")
        oos_pf_raw = r.get("oos_pf", "0")
        is_pf = None if is_pf_raw in ("inf", "") else _safe_float(is_pf_raw)
        oos_pf = None if oos_pf_raw in ("inf", "") else _safe_float(oos_pf_raw)

        oos_net = _safe_float(r.get("oos_net")) or 0.0
        oos_nets.append(oos_net)
        oos_trades += int(r.get("oos_trades") or 0)
        oos_days += int(r.get("oos_days") or 0)

        fold_docs.append({
            "run_id": run_id,
            "fold_index": fold_idx,
            "is_window": {"start": r.get("is_start", ""), "end": r.get("oos_start", "")},
            "oos_window": {"start": r.get("oos_start", ""), "end": r.get("oos_end", "")},
            "pick_label": r.get("pick", ""),
            "is_metrics": {
                "net": _safe_float(r.get("is_net")),
                "profit_factor": is_pf,
                "sharpe": _safe_float(r.get("is_sharpe")),
            },
            "oos_metrics": {
                "net": oos_net,
                "profit_factor": oos_pf,
                "win_rate": _safe_float(r.get("oos_win")),
                "sharpe": _safe_float(r.get("oos_sharpe")),
                "max_dd": _safe_float(r.get("oos_maxdd")),
                "days": int(r.get("oos_days") or 0),
                "trades": int(r.get("oos_trades") or 0),
            },
        })

    # Stitched OOS summary — aggregate across folds
    total_net = sum(oos_nets)
    oos_sharpe = _sharpe_from_rets(oos_nets)

    # Simple PF from per-fold data
    gp = sum(x for x in oos_nets if x >= 0)
    gl = sum(x for x in oos_nets if x < 0)
    agg_pf = (gp / abs(gl)) if gl < 0 else None

    pos_folds = sum(1 for x in oos_nets if x > 0)
    n = len(rows)
    verdict = (
        "PASS"
        if total_net > _WF_PASS_NET
        and (agg_pf or 0) > _WF_PASS_PF
        and (oos_sharpe or 0) > _WF_PASS_SHARPE
        and n > 0
        and pos_folds >= _WF_PASS_POS_FRAC * n
        else "REVIEW"
    )

    stitched_oos = {
        "net": total_net,
        "profit_factor": agg_pf,
        "sharpe": oos_sharpe,
        "trades": oos_trades,
        "days": oos_days,
        "folds": n,
        "positive_folds": pos_folds,
    }
    return fold_docs, stitched_oos, verdict


def build_trade_docs(
    run_id: str,
    days_dir: str | Path,
) -> list[dict[str, Any]]:
    """Build `backtest_trades` documents (one per day) from per-day trades.csv files."""
    days_dir = Path(days_dir)
    docs: list[dict[str, Any]] = []
    for day_dir in sorted(days_dir.iterdir()):
        if not day_dir.is_dir():
            continue
        trades_path = day_dir / "trades.csv"
        if not trades_path.exists():
            continue
        fills: list[dict[str, Any]] = []
        with open(trades_path, newline="") as fh:
            for row in csv.DictReader(fh):
                fills.append({
                    "time": row.get("time", ""),
                    "side": row.get("side", ""),
                    "opt_type": row.get("opt_type", ""),
                    "strike": _safe_float(row.get("strike")),
                    "qty": int(row.get("qty") or 0),
                    "price": _safe_float(row.get("price")),
                    "nifty": _safe_float(row.get("nifty")),
                    "leg_pnl": _safe_float(row.get("leg_pnl")) if row.get("leg_pnl") else None,
                    "day_pnl": _safe_float(row.get("day_pnl")),
                    "commission": _safe_float(row.get("commission")),
                    "note": row.get("note", ""),
                })
        if fills:
            docs.append({"run_id": run_id, "date": day_dir.name, "fills": fills})
    return docs


def build_day_doc_from_result(
    run_id: str,
    result: Any,
    *,
    cum_equity: float,
    peak: float,
    build_ms: float,
    sim_ms: float,
) -> dict[str, Any]:
    """Build one `backtest_days` doc directly from a `DayResult` (DB-first path — no CSV round-trip)."""
    return {
        "run_id": run_id,
        "date": result.date,
        "expiry": result.expiry,
        "nifty_open": _safe_float(result.nifty_open),
        "nifty_close": _safe_float(result.nifty_close),
        "nifty_chg": _safe_float(result.nifty_chg),
        "trades": len(result.trades),
        "gross_pnl": _safe_float(result.gross_pnl),
        "commission": _safe_float(result.commission),
        "net": _safe_float(result.realized),
        "cum_equity": _safe_float(cum_equity),
        "peak": _safe_float(peak),
        "drawdown": _safe_float(peak - cum_equity),
        "halted": result.done_reason or "",
        "build_ms": _safe_float(build_ms),
        "sim_ms": _safe_float(sim_ms),
        "status_log": [],
    }


def build_trade_doc_from_result(run_id: str, result: Any) -> dict[str, Any] | None:
    """Build one `backtest_trades` doc (fills bucket) directly from a `DayResult`."""
    if not result.trades:
        return None
    fills = [{
        "time": t.bar_time.strftime("%H:%M") if hasattr(t.bar_time, "strftime") else str(t.bar_time),
        "side": t.side,
        "opt_type": t.opt_type,
        "strike": _safe_float(t.strike),
        "qty": t.qty,
        "price": _safe_float(t.price),
        "nifty": _safe_float(t.nifty),
        "leg_pnl": _safe_float(t.leg_pnl) if t.leg_pnl is not None else None,
        "day_pnl": _safe_float(t.day_pnl),
        "commission": _safe_float(t.commission_inr),
        "note": t.note,
    } for t in result.trades]
    return {"run_id": run_id, "date": result.date, "fills": fills}


# ── sweep leaderboard ──────────────────────────────────────────────────────────


def build_sweep_doc(
    sweep_id: str,
    *,
    kind: str,
    window: dict[str, Any],
    grid: dict[str, Any],
    objective: str,
    combos: list[dict[str, Any]],
    base_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a `backtest_sweeps` leaderboard document.

    *combos* is a list of ``{params, metrics}`` (unranked); this ranks by
    ``(-profit_factor, -net)`` (matching ``backtest/run.py:print_table``) and
    picks the top combo's ``params`` as ``best_param``.
    """
    def _rank_key(c: dict[str, Any]) -> tuple[float, float]:
        pf = c["metrics"].get("profit_factor")
        pf = pf if pf not in (None, float("inf")) else 1e9
        net = c["metrics"].get("net") or 0.0
        return (-pf, -net)

    ranked = sorted(combos, key=_rank_key)
    for i, c in enumerate(ranked, 1):
        c["rank"] = i

    return {
        "sweep_id": sweep_id,
        "kind": kind,
        "underlying": ((base_config or {}).get("underlying") or "").upper(),
        "window": window,
        "grid": grid,
        "objective": objective,
        "base_config": base_config or {},
        "combos": ranked,
        "best_param": ranked[0]["params"] if ranked else None,
        "verdict": single_run_verdict(ranked[0].get("metrics", {})) if ranked else None,
        "created_at": datetime.now(UTC),
    }


# ── promotion rationale ─────────────────────────────────────────────────────────


def build_promotion_doc(
    run: dict[str, Any],
    promote_result: dict[str, Any],
    *,
    note: str | None = None,
) -> dict[str, Any]:
    """Build a self-contained `backtest_promotions` evidence doc.

    Snapshots the justifying evidence at promote time so the audit doc never needs to
    join back to `backtest_runs`: stitched-OOS metrics, per-threshold PASS-vs-actual
    breakdown, positive-fold fraction, source-run link, plus an optional operator note.
    """
    stitched_oos = run.get("stitched_oos") or {}
    breakdown = verdict_breakdown(stitched_oos) if stitched_oos else None
    return {
        "run_id": run["run_id"],
        "source_run_id": run["run_id"],
        "strategy_id": promote_result["strategy_id"],
        "yaml_path": promote_result["yaml_path"],
        "verdict": run.get("verdict"),
        "config": run.get("config", {}),
        "stitched_oos": stitched_oos,
        "verdict_breakdown": breakdown,
        "note": note,
        "promoted_at": datetime.now(UTC),
    }


def ship_promotion_event(doc: dict[str, Any]) -> None:
    """Dual-sink a promotion doc to OpenSearch (no-op when indexer inactive)."""
    _ship_backtest("promotion", doc)


# ── decision trace (why entry / why exit) ──────────────────────────────────────

# Closed vocabulary of top-level reason codes. `sub_reason` and `snapshot` stay
# open maps so any strategy can emit the same shape.
DECISION_EVENTS = ("st_flip", "entry", "scale_in", "rollup", "exit", "reentry")


def build_decision_docs(
    run_id: str,
    strategy_id: str,
    raw_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Shape raw decision events (as emitted by the sim) into `backtest_decisions` docs.

    *raw_events* items: ``{ts_ist, date, event, sub_reason?, action, snapshot}``.
    """
    docs: list[dict[str, Any]] = []
    for e in raw_events:
        docs.append({
            "run_id": run_id,
            "strategy_id": strategy_id,
            "ts_ist": e["ts_ist"],
            "date": e["date"],
            "event": e["event"],
            "sub_reason": e.get("sub_reason"),
            "action": e.get("action", ""),
            "snapshot": e.get("snapshot", {}),
        })
    return docs


# ── BacktestStore ─────────────────────────────────────────────────────────────


class BacktestStore:
    """Thin wrapper around pymongo sync collections for idempotent upserts.

    Call with sync pymongo collections (scripts / ingest / RunWriter dual-sink).
    The API routes query Motor async collections directly.
    """

    def __init__(
        self,
        col_runs: Any,
        col_days: Any,
        col_folds: Any,
        col_trades: Any,
        col_sweeps: Any | None = None,
        col_decisions: Any | None = None,
    ) -> None:
        self._runs = col_runs
        self._days = col_days
        self._folds = col_folds
        self._trades = col_trades
        self._sweeps = col_sweeps
        self._decisions = col_decisions

    # -- upserts ---------------------------------------------------------------- #

    def upsert_run(self, doc: dict[str, Any]) -> None:
        self._runs.update_one(
            {"run_id": doc["run_id"]},
            {"$set": doc},
            upsert=True,
        )
        log.info("backtest_run_upserted", run_id=doc["run_id"], kind=doc.get("kind"))
        _ship_backtest("run", doc)

    def upsert_days(self, docs: list[dict[str, Any]]) -> int:
        if not docs:
            return 0
        for doc in docs:
            self._days.update_one(
                {"run_id": doc["run_id"], "date": doc["date"]},
                {"$set": doc},
                upsert=True,
            )
            _ship_backtest("day", doc)
        return len(docs)

    def upsert_folds(self, docs: list[dict[str, Any]]) -> int:
        if not docs:
            return 0
        for doc in docs:
            self._folds.update_one(
                {"run_id": doc["run_id"], "fold_index": doc["fold_index"]},
                {"$set": doc},
                upsert=True,
            )
        return len(docs)

    def upsert_trades(self, docs: list[dict[str, Any]]) -> int:
        if not docs:
            return 0
        for doc in docs:
            self._trades.update_one(
                {"run_id": doc["run_id"], "date": doc["date"]},
                {"$set": doc},
                upsert=True,
            )
            _ship_backtest("trade", doc)
        return len(docs)

    def upsert_sweep(self, doc: dict[str, Any]) -> None:
        if self._sweeps is None:
            raise RuntimeError("BacktestStore was constructed without a sweeps collection")
        self._sweeps.update_one(
            {"sweep_id": doc["sweep_id"]},
            {"$set": doc},
            upsert=True,
        )
        log.info("backtest_sweep_upserted", sweep_id=doc["sweep_id"], combos=len(doc.get("combos", [])))
        # Dual-sink each combo to OpenSearch's backtest-runs family, tagged with
        # sweep_id/param_grid — the leaderboard above (not a backtest_runs Mongo doc
        # per combo) stays the DB source of truth, but combos must still be queryable
        # and rankable alongside single/walk-forward runs in the observability layer.
        base_config = doc.get("base_config") or {}
        for combo in doc.get("combos", []):
            _ship_backtest("run", {
                "run_id": f"{doc['sweep_id']}#rank{combo.get('rank')}",
                "kind": "sweep_combo",
                "underlying": ((base_config or {}).get("underlying") or "").upper(),
                "strategy_id": "strangle",
                "config": {**base_config, **combo.get("params", {})},
                "window": doc.get("window", {}),
                "metrics": combo.get("metrics", {}),
                "verdict": single_run_verdict(combo.get("metrics", {})),
                "promotion_state": "none",
                "git_sha": None,
                "created_at": doc.get("created_at"),
                "sweep_id": doc["sweep_id"],
                "param_grid": doc.get("grid", {}),
            })

    def upsert_decisions(self, docs: list[dict[str, Any]]) -> int:
        if not docs:
            return 0
        if self._decisions is None:
            raise RuntimeError("BacktestStore was constructed without a decisions collection")
        for doc in docs:
            self._decisions.update_one(
                {"run_id": doc["run_id"], "ts_ist": doc["ts_ist"], "event": doc["event"]},
                {"$set": doc},
                upsert=True,
            )
            _ship_backtest("decision", doc)
        return len(docs)

    # -- high-level ingest ------------------------------------------------------ #

    def ingest_run_folder(
        self,
        run_dir: str | Path,
        *,
        kind: str = "single",
        folds_csv: str | Path | None = None,
    ) -> dict[str, Any]:
        """Read a `backtest/runs/<id>/` folder and upsert everything into Mongo.

        Optionally pass a ``folds_csv`` to also ingest walk-forward fold data.
        Returns a summary dict of inserted counts.
        """
        run_dir = Path(run_dir)
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"manifest.json not found in {run_dir}")

        manifest = json.loads(manifest_path.read_text())

        # Equity series for Sharpe computation
        equity_rets: list[float] = []
        equity_path = run_dir / "equity.csv"
        if equity_path.exists():
            with open(equity_path, newline="") as fh:
                equity_rets = [float(r["net"]) for r in csv.DictReader(fh)
                               if r.get("net") not in (None, "")]

        # Walk-forward folds (optional)
        fold_docs: list[dict[str, Any]] = []
        stitched_oos: dict[str, Any] | None = None
        verdict: str | None = None
        if folds_csv is not None and Path(folds_csv).exists():
            fold_docs, stitched_oos, verdict = build_fold_docs(manifest["run_id"], folds_csv)
            kind = "walkforward"

        run_doc = build_run_doc(
            manifest, kind=kind, equity_rets=equity_rets,
            verdict=verdict, stitched_oos=stitched_oos,
        )
        self.upsert_run(run_doc)

        # Per-day documents (include status_log when days/ exists)
        day_count = 0
        summary_path = run_dir / "summary.csv"
        if summary_path.exists() and equity_path.exists():
            day_docs = build_day_docs(
                manifest["run_id"], summary_path, equity_path,
                days_dir=run_dir / "days" if (run_dir / "days").exists() else None,
            )
            day_count = self.upsert_days(day_docs)

        # Fold documents
        fold_count = self.upsert_folds(fold_docs)

        # Trade documents (may be large; skip if days/ is absent)
        trade_count = 0
        days_dir = run_dir / "days"
        if days_dir.exists():
            trade_docs = build_trade_docs(manifest["run_id"], days_dir)
            trade_count = self.upsert_trades(trade_docs)

        summary = {
            "run_id": manifest["run_id"],
            "kind": kind,
            "days": day_count,
            "folds": fold_count,
            "trade_days": trade_count,
        }
        log.info("ingest_complete", **summary)
        return summary

    def ingest_wf_csv(
        self,
        folds_csv: str | Path,
        *,
        run_id: str,
        config: dict[str, Any] | None = None,
        window: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Ingest a stand-alone walk-forward CSV (no run folder) into Mongo.

        Use when the walk-forward was run without ``--out-dir``.
        """
        fold_docs, stitched_oos, verdict = build_fold_docs(run_id, folds_csv)
        if not fold_docs:
            return {"run_id": run_id, "folds": 0}

        # Derive window from fold dates if not supplied
        if window is None:
            all_starts = [f["is_window"]["start"] for f in fold_docs]
            all_ends = [f["oos_window"]["end"] for f in fold_docs]
            window = {
                "from": min(all_starts) if all_starts else "",
                "to": max(all_ends) if all_ends else "",
            }

        run_doc: dict[str, Any] = {
            "run_id": run_id,
            "kind": "walkforward",
            "underlying": ((config or {}).get("underlying") or "").upper(),
            "strategy_id": re.split(r"_\d{8}", run_id)[0] if re.search(r"_\d{8}", run_id) else run_id,
            "config": config or {},
            "window": window,
            "metrics": {
                "net": stitched_oos.get("net"),
                "profit_factor": stitched_oos.get("profit_factor"),
                "sharpe": stitched_oos.get("sharpe"),
                "max_dd": None,
                "win_rate": None,
                "calmar": None,
                "trades": stitched_oos.get("trades", 0),
                "halted": 0,
                "days": stitched_oos.get("days", 0),
            },
            "git_sha": None,
            "status": "complete",
            "promotion_state": "none",
            "verdict": verdict,
            "stitched_oos": stitched_oos,
            "created_at": datetime.now(UTC),
        }
        self.upsert_run(run_doc)
        fold_count = self.upsert_folds(fold_docs)
        return {"run_id": run_id, "kind": "walkforward", "folds": fold_count, "verdict": verdict}
