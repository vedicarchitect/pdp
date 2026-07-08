"""Unit tests for trade_ledger.pair_trades.

Covers:
  (a) clean open→take_profit round-trip
  (b) open→stop_half→stop_all (partial + terminal row)
  (c) still-open leg (open with no close)
  (d) hedge leg open→close
  (e) per-index grouping
  (f) realized_pnl excludes open legs
  (g) read_day_events mtime/size caching
"""
from __future__ import annotations

import json
from datetime import date

from pdp.strategy.trade_ledger import (
    compute_totals,
    group_by_index,
    pair_trades,
    read_day_events,
)


def _open_evt(sid: str = "100", underlying: str = "NIFTY", **kw):
    return {
        "event_type": "leg_open",
        "sid": sid,
        "underlying": underlying,
        "opt_type": kw.get("opt_type", "PE"),
        "strike": kw.get("strike", 24300),
        "lots": kw.get("lots", 2),
        "entry_price": kw.get("entry_price", 100.0),
        "is_hedge": kw.get("is_hedge", False),
        "entry_time": "2026-07-07T10:15:00+05:30",
        "expiry": "2026-07-10",
        "symbol": f"NIFTY-Jul2026-{kw.get('strike', 24300)}-{kw.get('opt_type', 'PE')}",
        **{k: v for k, v in kw.items() if k not in ("opt_type", "strike", "lots", "entry_price", "is_hedge")},
    }


def _close_evt(
    etype: str, sid: str = "100", underlying: str = "NIFTY", **kw,
):
    return {
        "event_type": etype,
        "sid": sid,
        "underlying": underlying,
        "opt_type": kw.get("opt_type", "PE"),
        "strike": kw.get("strike", 24300),
        "lots": kw.get("lots", 2),
        "entry_price": kw.get("entry_price", 100.0),
        "exit_price": kw.get("exit_price", 50.0),
        "pnl": kw.get("pnl", 7500.0),
        "is_hedge": kw.get("is_hedge", False),
        "entry_time": "2026-07-07T10:15:00+05:30",
        "exit_time": "2026-07-07T11:30:00+05:30",
        "expiry": "2026-07-10",
        "symbol": f"NIFTY-Jul2026-{kw.get('strike', 24300)}-{kw.get('opt_type', 'PE')}",
        "reason": kw.get("reason", etype),
        **{k: v for k, v in kw.items() if k not in (
            "opt_type", "strike", "lots", "entry_price", "exit_price",
            "pnl", "is_hedge", "reason",
        )},
    }


class TestPairTradesCleanRoundTrip:
    """(a) A clean open → take_profit round-trip."""

    def test_single_round_trip(self):
        events = [
            _open_evt(sid="100", entry_price=100.0, lots=2),
            _close_evt("take_profit", sid="100", exit_price=50.0, pnl=7500.0, lots=2),
        ]
        rows = pair_trades(events)
        assert len(rows) == 1
        row = rows[0]
        assert row["open"] is False
        assert row["partial"] is False
        assert row["entry_price"] == 100.0
        assert row["exit_price"] == 50.0
        assert row["pnl"] == 7500.0
        assert row["lots"] == 2
        assert row["reason"] == "take_profit"


class TestPairTradesStopHalfThenAll:
    """(b) open → stop_half → stop_all yields partial + terminal rows."""

    def test_partial_then_terminal(self):
        events = [
            _open_evt(sid="200", lots=4, entry_price=100.0),
            _close_evt("stop_half", sid="200", lots=2, exit_price=130.0, pnl=-4500.0),
            _close_evt("stop_all", sid="200", lots=2, exit_price=140.0, pnl=-6000.0),
        ]
        rows = pair_trades(events)
        # Should get 2 rows: one partial, one terminal
        assert len(rows) == 2
        partial = [r for r in rows if r["partial"]]
        terminal = [r for r in rows if not r["partial"] and not r["open"]]
        assert len(partial) == 1
        assert len(terminal) == 1
        assert partial[0]["pnl"] == -4500.0
        assert terminal[0]["pnl"] == -6000.0

    def test_no_double_counting(self):
        events = [
            _open_evt(sid="200", lots=4, entry_price=100.0),
            _close_evt("stop_half", sid="200", lots=2, exit_price=130.0, pnl=-4500.0),
            _close_evt("stop_all", sid="200", lots=2, exit_price=140.0, pnl=-6000.0),
        ]
        rows = pair_trades(events)
        totals = compute_totals(rows)
        assert totals["realized_pnl"] == -4500.0 + -6000.0
        assert totals["n_open"] == 0


class TestPairTradesStillOpen:
    """(c) A still-open leg (open with no close)."""

    def test_open_leg_returned(self):
        events = [
            _open_evt(sid="300", lots=2, entry_price=80.0),
        ]
        rows = pair_trades(events)
        assert len(rows) == 1
        row = rows[0]
        assert row["open"] is True
        assert row["exit_price"] is None
        assert row["exit_time"] is None
        assert row["pnl"] is None

    def test_open_leg_excluded_from_realized(self):
        events = [
            _open_evt(sid="300", lots=2, entry_price=80.0),
        ]
        rows = pair_trades(events)
        totals = compute_totals(rows)
        assert totals["realized_pnl"] == 0.0
        assert totals["n_open"] == 1


class TestPairTradesHedge:
    """(d) Hedge leg open → close."""

    def test_hedge_round_trip(self):
        events = [
            _open_evt(sid="400", lots=2, entry_price=5.0, is_hedge=True),
            _close_evt("leg_close", sid="400", exit_price=2.0, pnl=-450.0, is_hedge=True, lots=2),
        ]
        rows = pair_trades(events)
        assert len(rows) == 1
        row = rows[0]
        assert row["is_hedge"] is True
        assert row["pnl"] == -450.0
        assert row["open"] is False


class TestGroupByIndex:
    """(e) Per-index grouping."""

    def test_multi_index_grouping(self):
        events = [
            _open_evt(sid="100", underlying="NIFTY"),
            _close_evt("take_profit", sid="100", underlying="NIFTY"),
            _open_evt(sid="500", underlying="BANKNIFTY"),
            _close_evt("leg_close", sid="500", underlying="BANKNIFTY"),
        ]
        rows = pair_trades(events)
        grouped = group_by_index(rows)
        assert "NIFTY" in grouped
        assert "BANKNIFTY" in grouped
        assert len(grouped["NIFTY"]) == 1
        assert len(grouped["BANKNIFTY"]) == 1


class TestComputeTotals:
    """(f) Realized P&L excludes open legs."""

    def test_mixed_open_and_closed(self):
        events = [
            _open_evt(sid="100", lots=2, entry_price=100.0),
            _close_evt("take_profit", sid="100", exit_price=50.0, pnl=7500.0, lots=2),
            _open_evt(sid="200", lots=2, entry_price=80.0),  # still open
        ]
        rows = pair_trades(events)
        totals = compute_totals(rows)
        assert totals["realized_pnl"] == 7500.0
        assert totals["n_round_trips"] == 1
        assert totals["n_open"] == 1


class TestReadDayEventsCaching:
    """(g) read_day_events caches by (mtime, size) — an unchanged file is not
    re-read/re-parsed, but an append is picked up on the next call."""

    def test_missing_file_returns_empty(self, tmp_path):
        events = read_day_events("no_such_strategy", date(2026, 7, 7), logs_dir=tmp_path)
        assert events == []

    def test_repeated_read_of_unchanged_file_returns_same_events(self, tmp_path):
        strategy_dir = tmp_path / "directional_strangle_nifty"
        strategy_dir.mkdir()
        log_path = strategy_dir / "2026-07-07.log"
        log_path.write_text(json.dumps({"event_type": "leg_open", "sid": "1"}) + "\n")

        first = read_day_events("directional_strangle_nifty", date(2026, 7, 7), logs_dir=tmp_path)
        second = read_day_events("directional_strangle_nifty", date(2026, 7, 7), logs_dir=tmp_path)
        assert first == second == [{"event_type": "leg_open", "sid": "1"}]

    def test_append_is_picked_up_on_next_read(self, tmp_path):
        strategy_dir = tmp_path / "directional_strangle_banknifty"
        strategy_dir.mkdir()
        log_path = strategy_dir / "2026-07-07.log"
        log_path.write_text(json.dumps({"event_type": "leg_open", "sid": "1"}) + "\n")

        first = read_day_events("directional_strangle_banknifty", date(2026, 7, 7), logs_dir=tmp_path)
        assert len(first) == 1

        with log_path.open("a") as f:
            f.write(json.dumps({"event_type": "leg_close", "sid": "1", "pnl": 100.0}) + "\n")

        second = read_day_events("directional_strangle_banknifty", date(2026, 7, 7), logs_dir=tmp_path)
        assert len(second) == 2, "Append must be visible on the next read, not served from a stale cache"
        assert second[1]["event_type"] == "leg_close"
