"""Unit tests for pdp.backtest.paper_compare — pure grouping/alignment/diff logic plus a
thin DB-query test with a mocked AsyncSession (matches the repo's DB-test convention)."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from pdp.backtest.paper_compare import (
    align_days,
    annotate_day_divergence,
    annotate_minute_divergence,
    fetch_paper_trades,
    group_paper_pnl,
    minute_diff,
    normalize_backtest_event,
    normalize_live_event,
    paper_pnl_by_strategy,
    resolve_live_strategy_id,
)

# ── group_paper_pnl / fetch_paper_trades ────────────────────────────────────────


def _trade(strategy_id: str, side: str, qty: int, price: str, charges: str, ts: datetime) -> dict:
    return {
        "strategy_id": strategy_id,
        "security_id": "1001",
        "side": side,
        "qty": qty,
        "fill_price": Decimal(price),
        "charges": Decimal(charges),
        "filled_at": ts,
    }


def test_group_paper_pnl_computes_gross_and_net():
    trades = [
        _trade("directional_strangle_nifty", "SELL", 50, "100", "5", datetime(2026, 1, 2, 5, 0, tzinfo=UTC)),
        _trade("directional_strangle_nifty", "BUY", 50, "60", "5", datetime(2026, 1, 2, 6, 0, tzinfo=UTC)),
    ]
    out = group_paper_pnl(trades)
    days = out["directional_strangle_nifty"]
    assert len(days) == 1
    day = days[0]
    assert day["date"] == "2026-01-02"
    assert day["gross_pnl"] == pytest.approx((100 - 60) * 50)
    assert day["net_pnl"] == pytest.approx((100 - 60) * 50 - 10)
    assert day["round_trips"] == 1
    assert day["wins"] == 1


def test_group_paper_pnl_groups_by_strategy_and_date():
    trades = [
        _trade("directional_strangle_nifty", "SELL", 50, "100", "5", datetime(2026, 1, 2, 5, 0, tzinfo=UTC)),
        _trade("directional_strangle_banknifty", "SELL", 25, "200", "5", datetime(2026, 1, 3, 5, 0, tzinfo=UTC)),
    ]
    out = group_paper_pnl(trades)
    assert set(out) == {"directional_strangle_nifty", "directional_strangle_banknifty"}
    assert out["directional_strangle_nifty"][0]["date"] == "2026-01-02"
    assert out["directional_strangle_banknifty"][0]["date"] == "2026-01-03"


def test_group_paper_pnl_ist_date_boundary():
    """18:30 UTC on Jan 1 is 00:00 IST on Jan 2 — must land on the Jan-2 bucket."""
    trades = [_trade("s1", "SELL", 1, "10", "0", datetime(2026, 1, 1, 18, 30, tzinfo=UTC))]
    out = group_paper_pnl(trades)
    assert out["s1"][0]["date"] == "2026-01-02"


@pytest.mark.asyncio
async def test_fetch_paper_trades_maps_rows():
    rows = [
        ("directional_strangle_nifty", "1001", "SELL", 50, Decimal("100"), Decimal("5"),
         datetime(2026, 1, 2, 5, 0, tzinfo=UTC)),
    ]
    result = MagicMock()
    result.all = MagicMock(return_value=rows)
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)

    out = await fetch_paper_trades(session, datetime(2026, 1, 1).date(), datetime(2026, 1, 10).date())
    assert len(out) == 1
    assert out[0]["strategy_id"] == "directional_strangle_nifty"
    assert out[0]["fill_price"] == Decimal("100")


@pytest.mark.asyncio
async def test_paper_pnl_by_strategy_end_to_end_with_mocked_session():
    rows = [
        ("directional_strangle_nifty", "1001", "SELL", 50, Decimal("100"), Decimal("5"),
         datetime(2026, 1, 2, 5, 0, tzinfo=UTC)),
        ("directional_strangle_nifty", "1001", "BUY", 50, Decimal("60"), Decimal("5"),
         datetime(2026, 1, 2, 6, 0, tzinfo=UTC)),
    ]
    result = MagicMock()
    result.all = MagicMock(return_value=rows)
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)

    out = await paper_pnl_by_strategy(
        session, datetime(2026, 1, 1).date(), datetime(2026, 1, 10).date(), "directional_strangle_nifty"
    )
    assert out["directional_strangle_nifty"][0]["net_pnl"] == pytest.approx(1990.0)


def test_resolve_live_strategy_id():
    assert resolve_live_strategy_id({"config": {"underlying": "NIFTY"}}) == "directional_strangle_nifty"
    assert resolve_live_strategy_id({"config": {"underlying": "BANKNIFTY"}}) == "directional_strangle_banknifty"
    assert resolve_live_strategy_id({"config": {}}) is None
    assert resolve_live_strategy_id({}) is None


def test_resolve_live_strategy_id_defaults_pre_multi_index_runs_to_nifty():
    """Runs ingested before backtest-multi-index-strangle never set config.underlying."""
    run = {"strategy_id": "strangle", "config": {"timeframe_min": 5}}
    assert resolve_live_strategy_id(run) == "directional_strangle_nifty"


# ── align_days ───────────────────────────────────────────────────────────────────


def test_align_days_flags_divergence_when_both_sides_present():
    backtest_days = [{"date": "2026-01-02", "net": 1000.0}]
    paper_days = [{"date": "2026-01-02", "net_pnl": 800.0}]
    rows = align_days(backtest_days, paper_days)
    assert rows == [{
        "date": "2026-01-02", "backtest_net": 1000.0, "paper_net": 800.0,
        "divergence": 200.0, "diverges": True,
    }]


def test_align_days_no_divergence_when_one_side_missing():
    backtest_days = [{"date": "2026-01-02", "net": 1000.0}]
    rows = align_days(backtest_days, [])
    assert rows[0]["paper_net"] is None
    assert rows[0]["divergence"] is None
    assert rows[0]["diverges"] is False


def test_align_days_respects_tolerance():
    backtest_days = [{"date": "2026-01-02", "net": 1000.0}]
    paper_days = [{"date": "2026-01-02", "net_pnl": 995.0}]
    rows = align_days(backtest_days, paper_days, tolerance=10.0)
    assert rows[0]["diverges"] is False


# ── shared vocabulary adapter ────────────────────────────────────────────────────


def test_normalize_backtest_event_maps_known_events():
    doc = {"event": "st_flip", "ts_ist": datetime(2026, 1, 2, 9, 35), "sub_reason": None, "snapshot": {"bucket": "complete_bear"}}
    norm = normalize_backtest_event(doc)
    assert norm["action"] == "bias"
    assert norm["minute"] == "2026-01-02T09:35"
    assert norm["side"] == "backtest"


def test_normalize_backtest_event_unmapped_returns_none():
    assert normalize_backtest_event({"event": "unknown_thing"}) is None


def test_normalize_live_event_maps_known_events():
    doc = {"event_type": "leg_open", "ist_time": "2026-01-02T09:35:12.345+05:30", "reason": None,
           "spot": 23000.0, "score": 0.5, "bucket": "complete_bear", "bias_votes": {"5m": 1}}
    norm = normalize_live_event(doc)
    assert norm["action"] == "entry"
    assert norm["minute"] == "2026-01-02T09:35"
    assert norm["side"] == "live"


def test_normalize_live_event_leg_status_is_excluded():
    assert normalize_live_event({"event_type": "leg_status"}) is None


# ── minute_diff ──────────────────────────────────────────────────────────────────


def test_minute_diff_flags_mismatch_when_actions_differ():
    backtest_docs = [{"event": "entry", "ts_ist": datetime(2026, 1, 2, 9, 35), "snapshot": {}}]
    live_docs = [{"event_type": "bias_evaluated", "ist_time": "2026-01-02T09:35:00+05:30"}]
    rows = minute_diff(backtest_docs, live_docs)
    assert len(rows) == 1
    assert rows[0]["mismatch"] is True


def test_minute_diff_no_mismatch_when_actions_match():
    backtest_docs = [{"event": "entry", "ts_ist": datetime(2026, 1, 2, 9, 35), "snapshot": {}}]
    live_docs = [{"event_type": "leg_open", "ist_time": "2026-01-02T09:35:00+05:30"}]
    rows = minute_diff(backtest_docs, live_docs)
    assert rows[0]["mismatch"] is False


# ── divergence root-causing ──────────────────────────────────────────────────────


def test_annotate_day_divergence_attributes_gap_radar_cause():
    days = [{"date": "2026-01-02", "diverges": True}]
    radar = {"2026-01-02": {"spot": "ready", "levels_weekly": "weekly Camarilla missing"}}
    out = annotate_day_divergence(days, radar)
    assert out[0]["cause"] == "weekly Camarilla missing"


def test_annotate_day_divergence_no_cause_when_radar_all_ready():
    days = [{"date": "2026-01-02", "diverges": True}]
    radar = {"2026-01-02": {"spot": "ready"}}
    out = annotate_day_divergence(days, radar)
    assert out[0]["cause"] is None


def test_annotate_day_divergence_skips_non_diverging_days():
    days = [{"date": "2026-01-02", "diverges": False}]
    out = annotate_day_divergence(days, {"2026-01-02": {"spot": "spot/VWAP missing"}})
    assert out[0]["cause"] is None


def test_annotate_minute_divergence_falls_back_to_missing_vote():
    rows = [{
        "minute": "2026-01-02T09:35", "mismatch": True,
        "backtest": [{"snapshot": {"votes": {"5m": 1, "15m": None}}}],
        "live": [],
    }]
    out = annotate_minute_divergence(rows, {"2026-01-02": {"spot": "ready"}})
    assert out[0]["cause"] == "vote missing: 15m"
