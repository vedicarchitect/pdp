"""Unit tests for BacktestStore: document builders, idempotent upsert, ingest round-trip."""
from __future__ import annotations

import csv
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pdp.backtest.store import (
    WF_PASS_NET,
    WF_PASS_PF,
    WF_PASS_POS_FRAC,
    WF_PASS_SHARPE,
    BacktestStore,
    _sharpe_from_rets,
    _safe_float,
    build_day_docs,
    build_decision_docs,
    build_fold_docs,
    build_promotion_doc,
    build_run_doc,
    build_sweep_doc,
    build_trade_docs,
    verdict_breakdown,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_manifest(tmp_path: Path, run_id: str = "strangle_20260101-120000") -> dict:
    m = {
        "run_id": run_id,
        "generated": "2026-01-01T12:00:00",
        "config": {"timeframe_min": 5, "lot_size": 65, "underlying": "NIFTY"},
        "window": {"from": "2026-01-02", "to": "2026-01-10", "biz_days": 6, "traded_days": 5},
        "metrics": {"days": 5, "net": 10000.0, "gross_profit": 15000.0,
                    "gross_loss": -5000.0, "profit_factor": 3.0,
                    "win_rate": 80.0, "max_dd": 2000.0, "trades": 30, "halted": 0},
        "totals": {"days": 5, "trades": 30, "wall_seconds": 1.2},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(m))
    return m


def _make_equity_csv(tmp_path: Path) -> None:
    with open(tmp_path / "equity.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "net", "cum_equity", "peak", "drawdown"])
        w.writerow(["2026-01-02", "2000.0", "2000.0", "2000.0", "0.0"])
        w.writerow(["2026-01-03", "3000.0", "5000.0", "5000.0", "0.0"])
        w.writerow(["2026-01-06", "-1000.0", "4000.0", "5000.0", "1000.0"])
        w.writerow(["2026-01-07", "4000.0", "8000.0", "8000.0", "0.0"])
        w.writerow(["2026-01-08", "2000.0", "10000.0", "10000.0", "0.0"])


def _make_summary_csv(tmp_path: Path) -> None:
    with open(tmp_path / "summary.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "expiry", "nifty_open", "nifty_close", "nifty_chg",
                    "trades", "gross_pnl", "commission", "net",
                    "cum_equity", "drawdown", "halted", "build_ms", "sim_ms"])
        rows = [
            ("2026-01-02", "2026-01-09", "23000", "23100", "+100", "6", "2200", "200", "2000",
             "2000", "0", "", "30", "5"),
            ("2026-01-03", "2026-01-09", "23100", "23200", "+100", "8", "3300", "300", "3000",
             "5000", "0", "", "28", "6"),
            ("2026-01-06", "2026-01-09", "23200", "23050", "-150", "4", "-900", "100", "-1000",
             "4000", "1000", "day_loss", "25", "4"),
            ("2026-01-07", "2026-01-09", "23050", "23250", "+200", "10", "4400", "400", "4000",
             "8000", "0", "", "32", "7"),
            ("2026-01-08", "2026-01-09", "23250", "23350", "+100", "8", "2200", "200", "2000",
             "10000", "0", "", "29", "6"),
        ]
        for r in rows:
            w.writerow(r)


def _make_trades_csv(day_dir: Path) -> None:
    with open(day_dir / "trades.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["time", "side", "opt_type", "strike", "qty", "price", "nifty",
                    "cum_lots", "avg_entry", "leg_pnl", "day_pnl", "commission", "note"])
        w.writerow(["10:15", "SELL", "PE", "23000", "1", "80.0", "23100",
                    "1", "80.0", "", "0.0", "20.0", "open [more_bull]"])
        w.writerow(["15:10", "BUY", "PE", "23000", "1", "40.0", "23200",
                    "0", "80.0", "2600.0", "2000.0", "20.0", "squareoff"])


def _make_wf_csv(tmp_path: Path) -> Path:
    p = tmp_path / "wf.csv"
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["fold", "is_start", "oos_start", "oos_end", "pick",
                    "is_net", "is_pf", "is_sharpe", "oos_net", "oos_pf",
                    "oos_win", "oos_sharpe", "oos_maxdd", "oos_days", "oos_trades"])
        w.writerow(["0", "2021-01-01", "2022-01-01", "2022-04-01",
                    "tren/cons/tp0.5/H", "500000", "5.0", "8.0",
                    "200000", "3.5", "80", "6.0", "20000", "60", "800"])
        w.writerow(["1", "2021-04-01", "2022-04-01", "2022-07-01",
                    "tren/cons/tp0.5/H", "480000", "4.5", "7.5",
                    "180000", "2.8", "75", "5.5", "25000", "62", "820"])
    return p


# ── unit tests ────────────────────────────────────────────────────────────────


def test_sharpe_from_rets_empty():
    assert _sharpe_from_rets([]) is None
    assert _sharpe_from_rets([100.0]) is None


def test_sharpe_from_rets_positive():
    rets = [100.0] * 100
    # All same returns → std == 0 → None
    assert _sharpe_from_rets(rets) is None


def test_sharpe_from_rets_mixed():
    rets = [100.0, -50.0, 200.0, -30.0, 80.0]
    s = _sharpe_from_rets(rets)
    assert s is not None
    assert s > 0  # positive mean → positive Sharpe


def test_safe_float_handles_inf():
    assert _safe_float(float("inf")) is None
    assert _safe_float(float("nan")) is None
    assert _safe_float("inf") is None
    assert _safe_float(3.14) == pytest.approx(3.14)
    assert _safe_float(None) is None


def test_build_run_doc_fields(tmp_path):
    manifest = _make_manifest(tmp_path)
    doc = build_run_doc(manifest, kind="single", equity_rets=[2000, 3000, -1000, 4000, 2000])
    assert doc["run_id"] == "strangle_20260101-120000"
    assert doc["kind"] == "single"
    assert doc["underlying"] == "NIFTY"
    assert doc["strategy_id"] == "strangle"
    assert doc["status"] == "complete"
    assert doc["promotion_state"] == "none"
    assert doc["verdict"] == "PASS"
    assert doc["metrics"]["net"] == pytest.approx(10000.0)
    assert doc["metrics"]["profit_factor"] == pytest.approx(3.0)
    assert doc["metrics"]["max_dd"] == pytest.approx(2000.0)
    assert doc["metrics"]["sharpe"] is not None  # computed from equity_rets
    assert isinstance(doc["created_at"], datetime)
    assert doc["created_at"].tzinfo is not None  # timezone-aware


def test_build_run_doc_review_verdict(tmp_path):
    manifest = _make_manifest(tmp_path)
    # PF < 1.2 causes REVIEW
    manifest["metrics"]["profit_factor"] = 1.1
    doc = build_run_doc(manifest, kind="single", equity_rets=[2000, 3000, -1000, 4000, 2000])
    assert doc["verdict"] == "REVIEW"
    assert doc["promotion_state"] == "none"


def test_build_run_doc_inf_pf(tmp_path):
    manifest = _make_manifest(tmp_path)
    manifest["metrics"]["profit_factor"] = float("inf")
    doc = build_run_doc(manifest)
    assert doc["metrics"]["profit_factor"] is None  # inf → None


def test_build_day_docs(tmp_path):
    _make_equity_csv(tmp_path)
    _make_summary_csv(tmp_path)
    docs = build_day_docs("run1", tmp_path / "summary.csv", tmp_path / "equity.csv")
    assert len(docs) == 5
    d0 = docs[0]
    assert d0["run_id"] == "run1"
    assert d0["date"] == "2026-01-02"
    assert d0["net"] == pytest.approx(2000.0)
    assert d0["cum_equity"] == pytest.approx(2000.0)
    assert d0["peak"] == pytest.approx(2000.0)
    assert d0["drawdown"] == pytest.approx(0.0)
    assert d0["status_log"] == []  # no days_dir supplied

    d2 = docs[2]
    assert d2["date"] == "2026-01-06"
    assert d2["net"] == pytest.approx(-1000.0)
    assert d2["halted"] == "day_loss"


def test_build_day_docs_with_status_log(tmp_path):
    _make_equity_csv(tmp_path)
    _make_summary_csv(tmp_path)
    days_dir = tmp_path / "days"
    day_dir = days_dir / "2026-01-02"
    day_dir.mkdir(parents=True)
    (day_dir / "status.log").write_text(
        "09:15 spot=23000 score=+0.5 most_bull | flat | day=0 | hold\n"
        "09:20 spot=23100 score=+0.5 most_bull | flat | day=0 | open 2PE\n",
        encoding="utf-8",
    )
    docs = build_day_docs("run1", tmp_path / "summary.csv", tmp_path / "equity.csv",
                          days_dir=days_dir)
    d0 = docs[0]
    assert d0["date"] == "2026-01-02"
    assert len(d0["status_log"]) == 2
    assert "09:15" in d0["status_log"][0]
    # Days without a status.log get empty list
    assert docs[1]["status_log"] == []


def test_build_fold_docs(tmp_path):
    wf = _make_wf_csv(tmp_path)
    fold_docs, stitched, verdict = build_fold_docs("wf_run1", wf)
    assert len(fold_docs) == 2
    f0 = fold_docs[0]
    assert f0["run_id"] == "wf_run1"
    assert f0["fold_index"] == 0
    assert f0["pick_label"] == "tren/cons/tp0.5/H"
    assert f0["is_window"]["start"] == "2021-01-01"
    assert f0["oos_window"]["end"] == "2022-04-01"
    assert f0["oos_metrics"]["net"] == pytest.approx(200000.0)
    assert f0["is_metrics"]["profit_factor"] == pytest.approx(5.0)

    assert stitched["net"] == pytest.approx(380000.0)
    assert stitched["folds"] == 2
    assert stitched["positive_folds"] == 2
    assert verdict in ("PASS", "REVIEW")


def test_build_trade_docs(tmp_path):
    days_dir = tmp_path / "days"
    day1 = days_dir / "2026-01-02"
    day1.mkdir(parents=True)
    _make_trades_csv(day1)
    docs = build_trade_docs("run1", days_dir)
    assert len(docs) == 1
    assert docs[0]["date"] == "2026-01-02"
    assert len(docs[0]["fills"]) == 2
    fill = docs[0]["fills"][0]
    assert fill["side"] == "SELL"
    assert fill["opt_type"] == "PE"
    assert fill["price"] == pytest.approx(80.0)


# ── BacktestStore / upsert ────────────────────────────────────────────────────


class _FakeCol:
    """In-memory stub for pymongo Collection."""

    def __init__(self):
        self._docs: dict = {}

    def update_one(self, filt, update, *, upsert=False):
        key = str(sorted(filt.items()))
        self._docs[key] = {**self._docs.get(key, {}), **update.get("$set", {})}

    def find_one(self, filt):
        key = str(sorted(filt.items()))
        return self._docs.get(key)


def _make_store(*, with_sweeps=False, with_decisions=False):
    return BacktestStore(
        col_runs=_FakeCol(),
        col_days=_FakeCol(),
        col_folds=_FakeCol(),
        col_trades=_FakeCol(),
        col_sweeps=_FakeCol() if with_sweeps else None,
        col_decisions=_FakeCol() if with_decisions else None,
    )


def test_store_upsert_run_idempotent():
    store = _make_store()
    doc = {"run_id": "r1", "kind": "single", "metrics": {"net": 1000.0},
           "created_at": datetime.now(UTC)}
    store.upsert_run(doc)
    store.upsert_run({**doc, "metrics": {"net": 2000.0}})  # second upsert updates
    # Both calls succeed without error; the store's fake col reflects last write
    key = str(sorted({"run_id": "r1"}.items()))
    stored = store._runs._docs[key]
    assert stored["metrics"]["net"] == pytest.approx(2000.0)


def test_store_upsert_days_returns_count():
    store = _make_store()
    docs = [
        {"run_id": "r1", "date": "2026-01-02", "net": 1000.0},
        {"run_id": "r1", "date": "2026-01-03", "net": 2000.0},
    ]
    n = store.upsert_days(docs)
    assert n == 2


def test_store_upsert_folds_returns_count():
    store = _make_store()
    docs = [{"run_id": "r1", "fold_index": 0, "oos_metrics": {"net": 100}},
            {"run_id": "r1", "fold_index": 1, "oos_metrics": {"net": 200}}]
    assert store.upsert_folds(docs) == 2


def test_store_ingest_run_folder(tmp_path):
    _make_manifest(tmp_path, run_id="strangle_20260101-120000")
    _make_equity_csv(tmp_path)
    _make_summary_csv(tmp_path)
    days_dir = tmp_path / "days" / "2026-01-02"
    days_dir.mkdir(parents=True)
    _make_trades_csv(days_dir)

    store = _make_store()
    summary = store.ingest_run_folder(tmp_path, kind="single")
    assert summary["run_id"] == "strangle_20260101-120000"
    assert summary["days"] == 5
    assert summary["trade_days"] == 1
    assert summary["folds"] == 0


def test_store_ingest_wf_csv(tmp_path):
    wf = _make_wf_csv(tmp_path)
    store = _make_store()
    result = store.ingest_wf_csv(wf, run_id="wf_test", config={"underlying": "SENSEX"})
    assert result["run_id"] == "wf_test"
    assert result["folds"] == 2
    assert result["verdict"] in ("PASS", "REVIEW")
    
    key = str(sorted({"run_id": "wf_test"}.items()))
    stored = store._runs._docs[key]
    assert stored["underlying"] == "SENSEX"


# ── verdict thresholds / breakdown ───────────────────────────────────────────


def test_verdict_breakdown_all_pass():
    stitched = {"net": 100000.0, "profit_factor": 2.0, "sharpe": 1.5,
                "folds": 10, "positive_folds": 7}
    b = verdict_breakdown(stitched)
    assert b["all_pass"] is True
    assert b["checks"]["net"]["pass"] is True
    assert b["checks"]["profit_factor"]["threshold"] == WF_PASS_PF
    assert b["checks"]["sharpe"]["threshold"] == WF_PASS_SHARPE
    assert b["checks"]["positive_fold_fraction"]["actual"] == pytest.approx(0.7)
    assert b["positive_folds"] == 7
    assert b["folds"] == 10


def test_verdict_breakdown_fails_on_low_pf():
    stitched = {"net": 100000.0, "profit_factor": 0.9, "sharpe": 1.5,
                "folds": 10, "positive_folds": 7}
    b = verdict_breakdown(stitched)
    assert b["all_pass"] is False
    assert b["checks"]["profit_factor"]["pass"] is False
    assert b["checks"]["net"]["pass"] is True  # other checks still reported independently


def test_verdict_breakdown_fails_on_low_positive_fold_fraction():
    stitched = {"net": 100000.0, "profit_factor": 2.0, "sharpe": 1.5,
                "folds": 10, "positive_folds": 5}  # 50% < WF_PASS_POS_FRAC (60%)
    b = verdict_breakdown(stitched)
    assert b["all_pass"] is False
    assert b["checks"]["positive_fold_fraction"]["pass"] is False


def test_verdict_breakdown_empty_stitched_all_fail():
    b = verdict_breakdown({})
    assert b["all_pass"] is False
    assert b["folds"] == 0
    assert b["checks"]["net"]["actual"] == 0.0


def test_wf_pass_thresholds_are_the_single_source():
    # Guards against re-introducing duplicated literals elsewhere.
    assert WF_PASS_NET == 0
    assert WF_PASS_PF == 1.2
    assert WF_PASS_SHARPE == 0.5
    assert WF_PASS_POS_FRAC == 0.6


# ── sweep leaderboard ─────────────────────────────────────────────────────────


def test_build_sweep_doc_ranks_by_pf_then_net():
    combos = [
        {"params": {"day_loss_limit": 10000}, "metrics": {"profit_factor": 2.0, "net": 5000.0}},
        {"params": {"day_loss_limit": 15000}, "metrics": {"profit_factor": 3.0, "net": 1000.0}},
        {"params": {"day_loss_limit": 20000}, "metrics": {"profit_factor": 3.0, "net": 9000.0}},
    ]
    doc = build_sweep_doc(
        "sweep_1", kind="sweep", window={"from": "2026-01-01", "to": "2026-06-01"},
        grid={"day_loss_limit": [10000, 15000, 20000]}, objective="pf", combos=combos,
        base_config={"underlying": "BANKNIFTY"}
    )
    assert doc["sweep_id"] == "sweep_1"
    assert doc["underlying"] == "BANKNIFTY"
    ranked = doc["combos"]
    # Highest PF wins; ties broken by higher net -> 20000 (pf=3, net=9000) is rank 1.
    assert ranked[0]["params"] == {"day_loss_limit": 20000}
    assert ranked[0]["rank"] == 1
    assert ranked[1]["params"] == {"day_loss_limit": 15000}
    assert ranked[2]["params"] == {"day_loss_limit": 10000}
    assert doc["best_param"] == {"day_loss_limit": 20000}


def test_build_sweep_doc_treats_inf_pf_as_best():
    combos = [
        {"params": {"a": 1}, "metrics": {"profit_factor": float("inf"), "net": 100.0}},
        {"params": {"a": 2}, "metrics": {"profit_factor": 3.0, "net": 999999.0}},
    ]
    doc = build_sweep_doc("sweep_2", kind="sweep", window={}, grid={"a": [1, 2]},
                          objective="pf", combos=combos)
    assert doc["best_param"] == {"a": 1}  # inf PF ranks above any finite PF


def test_build_sweep_doc_empty_combos():
    doc = build_sweep_doc("sweep_3", kind="sweep", window={}, grid={"a": [1]},
                          objective="pf", combos=[])
    assert doc["best_param"] is None
    assert doc["combos"] == []


def test_store_upsert_sweep_requires_collection():
    store = _make_store()  # no col_sweeps
    with pytest.raises(RuntimeError):
        store.upsert_sweep({"sweep_id": "x", "combos": []})


def test_store_upsert_sweep():
    store = _make_store(with_sweeps=True)
    doc = {"sweep_id": "sweep_1", "combos": [{"rank": 1, "params": {}}]}
    store.upsert_sweep(doc)
    key = str(sorted({"sweep_id": "sweep_1"}.items()))
    assert store._sweeps._docs[key]["sweep_id"] == "sweep_1"


def test_store_upsert_sweep_ships_each_combo_to_opensearch_with_sweep_id(monkeypatch):
    """Combos must be individually dual-sunk to backtest-runs, tagged sweep_id/param_grid —
    otherwise they're invisible to the observability layer even though the leaderboard
    persists fine in Mongo (task 2.4 / the "Sweep runs indexed to OpenSearch" requirement)."""
    shipped: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "pdp.backtest.store._ship_backtest",
        lambda kind, doc: shipped.append((kind, doc)),
    )
    store = _make_store(with_sweeps=True)
    doc = build_sweep_doc(
        "sweep_2", kind="sweep", window={"from": "2026-01-01", "to": "2026-02-01"},
        grid={"day_loss_limit": [10000, 15000]}, objective="pf",
        combos=[
            {"params": {"day_loss_limit": 10000}, "metrics": {"net": 5000.0, "profit_factor": 2.0}},
            {"params": {"day_loss_limit": 15000}, "metrics": {"net": 9000.0, "profit_factor": 3.0}},
        ],
        base_config={"underlying": "NIFTY"},
    )
    store.upsert_sweep(doc)

    run_ships = [d for kind, d in shipped if kind == "run"]
    assert len(run_ships) == 2
    for d in run_ships:
        assert d["sweep_id"] == "sweep_2"
        assert d["param_grid"] == {"day_loss_limit": [10000, 15000]}
        assert d["kind"] == "sweep_combo"
    # Each combo's resolved config merges base_config + its own param override.
    configs = {d["run_id"]: d["config"] for d in run_ships}
    assert configs["sweep_2#rank1"] == {"underlying": "NIFTY", "day_loss_limit": 15000}
    assert configs["sweep_2#rank2"] == {"underlying": "NIFTY", "day_loss_limit": 10000}


# ── decision trace ────────────────────────────────────────────────────────────


def test_build_decision_docs_shapes_raw_events():
    raw = [
        {"ts_ist": "2026-06-02T10:15:00", "date": "2026-06-02", "event": "entry",
         "action": "open 5PE", "snapshot": {"score": 0.9}},
        {"ts_ist": "2026-06-02T11:00:00", "date": "2026-06-02", "event": "rollup",
         "sub_reason": "premium_decay", "action": "roll 5L", "snapshot": {"from_strike": 20000}},
    ]
    docs = build_decision_docs("run1", "strangle", raw)
    assert len(docs) == 2
    assert docs[0]["run_id"] == "run1"
    assert docs[0]["strategy_id"] == "strangle"
    assert docs[0]["event"] == "entry"
    assert docs[0]["sub_reason"] is None
    assert docs[1]["sub_reason"] == "premium_decay"
    assert docs[1]["snapshot"]["from_strike"] == 20000


def test_store_upsert_decisions_requires_collection():
    store = _make_store()  # no col_decisions
    with pytest.raises(RuntimeError):
        store.upsert_decisions([{"run_id": "r1", "ts_ist": "t", "event": "entry"}])


def test_store_upsert_decisions_returns_count():
    store = _make_store(with_decisions=True)
    docs = [
        {"run_id": "r1", "ts_ist": "2026-06-02T10:15:00", "event": "entry"},
        {"run_id": "r1", "ts_ist": "2026-06-02T11:00:00", "event": "exit"},
    ]
    assert store.upsert_decisions(docs) == 2
    assert store.upsert_decisions([]) == 0  # empty list is a no-op, not an error


# ── promotion rationale ──────────────────────────────────────────────────────


def test_build_promotion_doc_snapshots_evidence():
    run = {
        "run_id": "wf_run1",
        "verdict": "PASS",
        "config": {"timeframe_min": 5},
        "stitched_oos": {"net": 100000.0, "profit_factor": 2.0, "sharpe": 1.5,
                         "folds": 10, "positive_folds": 7},
    }
    promote_result = {"strategy_id": "promoted_wf_run1", "yaml_path": "strategies/promoted_wf_run1.yaml"}
    doc = build_promotion_doc(run, promote_result, note="looks good, ship it")
    assert doc["run_id"] == "wf_run1"
    assert doc["source_run_id"] == "wf_run1"
    assert doc["strategy_id"] == "promoted_wf_run1"
    assert doc["verdict"] == "PASS"
    assert doc["note"] == "looks good, ship it"
    assert doc["verdict_breakdown"]["all_pass"] is True
    assert doc["stitched_oos"]["net"] == pytest.approx(100000.0)
    assert isinstance(doc["promoted_at"], datetime)


def test_build_promotion_doc_no_stitched_oos():
    """A single-run (non-walk-forward) promotion has no stitched_oos — must not crash."""
    run = {"run_id": "r1", "verdict": "PASS", "config": {}}
    promote_result = {"strategy_id": "promoted_r1", "yaml_path": "strategies/promoted_r1.yaml"}
    doc = build_promotion_doc(run, promote_result)
    assert doc["stitched_oos"] == {}
    assert doc["verdict_breakdown"] is None
    assert doc["note"] is None
