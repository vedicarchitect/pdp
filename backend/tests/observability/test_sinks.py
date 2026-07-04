"""Unit tests for the typed analytics doc mappers (pure functions)."""
from __future__ import annotations

from pdp.observability.sinks import (
    backtest_run_doc,
    fill_doc,
    journal_day_doc,
    strangle_event_doc,
)


def test_strangle_event_doc_id_and_timestamp():
    rec = {
        "event_type": "leg_open",
        "strategy_id": "directional_strangle",
        "account_id": "primary",
        "snapshot_date": "2026-06-28",
        "ist_time": "2026-06-28T10:00:00+05:30",
        "underlying": "NIFTY",
        "spot": 24000.0,
        "score": 1.2,
        "bucket": "BULL",
        "sid": "123",
        "opt_type": "CE",
        "strike": 24200.0,
        "lots": 2,
        "entry_price": 85.0,
    }
    doc, doc_id = strangle_event_doc(rec)
    assert doc_id == "directional_strangle:2026-06-28T10:00:00+05:30:leg_open:123"
    assert doc["@timestamp"] == "2026-06-28T10:00:00+05:30"
    assert doc["opt_type"] == "CE"
    assert doc["strike"] == 24200.0


def test_strangle_event_doc_id_stable_across_calls():
    rec = {"event_type": "stop_all", "strategy_id": "s", "ist_time": "t", "sid": "9"}
    assert strangle_event_doc(rec)[1] == strangle_event_doc(rec)[1]


def test_fill_doc_coerces_types():
    entry = {
        "ts": "2026-06-28T10:00:00Z",
        "security_id": "OPT_PE",
        "side": "SELL",
        "qty": "130",
        "fill_price": "100",
        "charges": "30",
        "strategy_id": "directional_strangle",
    }
    doc, doc_id = fill_doc(entry)
    assert doc_id is None
    assert doc["qty"] == 130
    assert doc["fill_price"] == 100.0
    assert doc["mode"] == "paper"


def test_journal_day_doc_id():
    stats = {"round_trips": 3, "wins": 2, "losses": 1, "realized_pnl": 4200.0,
             "gross_premium_sold": 18000.0, "gross_premium_bought": 13800.0}
    doc, doc_id = journal_day_doc("2026-06-28", stats)
    assert doc_id == "2026-06-28:paper"
    assert doc["realized_pnl"] == 4200.0
    assert doc["wins"] == 2


def test_backtest_run_doc_id_is_run_id():
    from datetime import UTC, datetime

    run = {
        "run_id": "strangle_20260628-120000",
        "kind": "single",
        "strategy_id": "strangle",
        "window": {"from": "2026-01-01", "to": "2026-06-01"},
        "metrics": {"net": 100.0},
        "verdict": "PASS",
        "promotion_state": "none",
        "git_sha": "abc",
        "created_at": datetime(2026, 6, 28, tzinfo=UTC),
        "config": {},
    }
    doc, doc_id = backtest_run_doc(run)
    assert doc_id == "strangle_20260628-120000"
    assert doc["@timestamp"].startswith("2026-06-28")
    assert doc["metrics"]["net"] == 100.0


def test_backtest_run_doc_forwards_sweep_fields():
    """Sweep combos are shipped as run docs — sweep_id/param_grid must pass through so
    they're queryable/rankable alongside single and walk-forward runs (task 2.4)."""
    from datetime import UTC, datetime

    run = {
        "run_id": "sweep_1#rank1",
        "kind": "sweep_combo",
        "strategy_id": "strangle",
        "window": {"from": "2026-01-01", "to": "2026-06-01"},
        "metrics": {"net": 100.0},
        "created_at": datetime(2026, 6, 28, tzinfo=UTC),
        "config": {"day_loss_limit": 10000},
        "sweep_id": "sweep_1",
        "param_grid": {"day_loss_limit": [10000, 15000]},
    }
    doc, doc_id = backtest_run_doc(run)
    assert doc_id == "sweep_1#rank1"
    assert doc["sweep_id"] == "sweep_1"
    assert doc["param_grid"] == {"day_loss_limit": [10000, 15000]}


def test_backtest_run_doc_sweep_fields_absent_for_plain_runs():
    """A single/walk-forward run (no sweep_id key at all) must not crash the mapper."""
    from datetime import UTC, datetime

    run = {
        "run_id": "strangle_20260628-120000", "kind": "single", "strategy_id": "strangle",
        "created_at": datetime(2026, 6, 28, tzinfo=UTC), "config": {},
    }
    doc, _ = backtest_run_doc(run)
    assert doc["sweep_id"] is None
    assert doc["param_grid"] is None
