"""Unit tests for the pure grid-expansion / aggregation helpers in sweep_engine.py.

``run_strangle_sweep`` itself needs Mongo (the market window); these test only the
deterministic combinatorics and metrics math that back the leaderboard.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from pdp.backtest.sweep_engine import aggregate, expand_grid


def test_expand_grid_cartesian_product():
    grid = {"hedge_enabled": [True, False], "day_loss_limit": [10000, 15000]}
    combos = expand_grid(grid)
    assert len(combos) == 4
    assert {"hedge_enabled": True, "day_loss_limit": 10000} in combos
    assert {"hedge_enabled": False, "day_loss_limit": 15000} in combos


def test_expand_grid_single_field():
    combos = expand_grid({"scale_lots": [1, 2, 3]})
    assert combos == [{"scale_lots": 1}, {"scale_lots": 2}, {"scale_lots": 3}]


def test_expand_grid_empty_raises():
    with pytest.raises(ValueError):
        expand_grid({})


@dataclass
class _FakeDayResult:
    realized: float
    trades: list = field(default_factory=list)
    done_reason: str = ""


def test_aggregate_profit_factor_and_drawdown():
    results = [
        _FakeDayResult(realized=1000.0),
        _FakeDayResult(realized=-400.0),
        _FakeDayResult(realized=2000.0),
        _FakeDayResult(realized=-100.0),
    ]
    m = aggregate(results)
    assert m["days"] == 4
    assert m["net"] == pytest.approx(2500.0)
    assert m["gross_profit"] == pytest.approx(3000.0)
    assert m["gross_loss"] == pytest.approx(-500.0)
    assert m["profit_factor"] == pytest.approx(6.0)
    assert m["win_rate"] == pytest.approx(50.0)
    # Equity path: +1000 (peak 1000) -400 (peak 1000, dd 400) +2000 (peak 2600) -100 (dd 100)
    assert m["max_dd"] == pytest.approx(400.0)


def test_aggregate_no_losing_days_is_best_case():
    results = [_FakeDayResult(realized=500.0), _FakeDayResult(realized=300.0)]
    m = aggregate(results)
    assert m["profit_factor"] is None  # treated as "best" (inf), matches print_table


def test_aggregate_empty_results():
    m = aggregate([])
    assert m["days"] == 0
    assert m["net"] == 0.0
    assert m["profit_factor"] == 0.0  # no trading days at all — not ranked as best
    assert m["win_rate"] == pytest.approx(0.0)


def test_aggregate_halted_count():
    results = [
        _FakeDayResult(realized=100.0, done_reason="day_loss"),
        _FakeDayResult(realized=50.0, done_reason=""),
    ]
    m = aggregate(results)
    assert m["halted"] == 1


def test_aggregate_includes_sharpe():
    # A sweep combo's metrics must carry a real sharpe so single_run_verdict (which grades
    # combos via the walk-forward thresholds) doesn't silently default sharpe to 0.0 and
    # force every combo to REVIEW regardless of actual risk-adjusted return.
    results = [
        _FakeDayResult(realized=1000.0),
        _FakeDayResult(realized=-400.0),
        _FakeDayResult(realized=2000.0),
        _FakeDayResult(realized=-100.0),
    ]
    m = aggregate(results)
    assert m["sharpe"] is not None
    assert m["sharpe"] > 0  # positive-mean returns -> positive Sharpe


def test_aggregate_sharpe_none_for_single_day():
    m = aggregate([_FakeDayResult(realized=100.0)])
    assert m["sharpe"] is None  # needs >=2 return observations
