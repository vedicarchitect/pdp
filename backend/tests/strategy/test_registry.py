"""Unit tests for registry.get_strategy."""
from __future__ import annotations

from pdp.strategy.abc import Strategy
from pdp.strategy.registry import get_strategy


def _write_yaml(path):
    (path / "foo.yaml").write_text(
        "id: foo\n"
        "class: pdp.strategies.supertrend_short.SuperTrendShort\n"
        "watchlist:\n"
        "  - security_id: '13'\n"
        "    exchange_segment: IDX_I\n"
        "    timeframes: [5m]\n"
        "params:\n"
        "  lot_size: 65\n"
        "  max_lots: 5\n"
    )


def test_get_strategy_returns_populated_instance(tmp_path):
    _write_yaml(tmp_path)
    inst = get_strategy("foo", tmp_path)
    assert isinstance(inst, Strategy)
    assert inst.strategy_id == "foo"
    assert inst.params["lot_size"] == 65
    assert inst.params["max_lots"] == 5
