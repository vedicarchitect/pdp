from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from pdp.backtest.engine import BacktestEngine, SimulatedClock, get_sim_time
from pdp.backtest.indicators import IndicatorCache


def test_simulated_clock():
    """Test SimulatedClock context manager."""
    dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

    with SimulatedClock(dt):
        assert get_sim_time() == dt


def test_simulated_clock_outside_context():
    """Test that get_sim_time returns current time outside context."""
    sim_time = get_sim_time()
    assert isinstance(sim_time, datetime)


def test_indicator_cache_sma():
    """Test SMA indicator computation."""
    cache = IndicatorCache(None)

    prices = [Decimal(str(p)) for p in [100, 101, 102, 103, 104, 105]]
    sma = cache._sma(prices, 3)

    # First 2 values should be None
    assert sma[0] is None
    assert sma[1] is None

    # SMA of [100, 101, 102] = 101
    assert sma[2] == Decimal("101")

    # SMA of [101, 102, 103] = 102
    assert sma[3] == Decimal("102")


def test_indicator_cache_ema():
    """Test EMA indicator computation."""
    cache = IndicatorCache(None)

    prices = [Decimal(str(p)) for p in [100, 101, 102, 103, 104, 105]]
    ema = cache._ema(prices, 3)

    # First 2 values should be None
    assert ema[0] is None
    assert ema[1] is None

    # EMA starts with SMA at period
    assert ema[2] is not None


def test_indicator_cache_rsi():
    """Test RSI indicator computation."""
    cache = IndicatorCache(None)

    prices = [Decimal(str(p)) for p in [100, 102, 104, 103, 105, 107]]
    rsi = cache._rsi(prices, 3)

    # First period-1 values should be None
    assert rsi[0] is None
    assert rsi[1] is None

    # RSI should be between 0 and 100
    for val in rsi[3:]:
        if val is not None:
            assert 0 <= val <= 100


def test_backtest_engine_initialization():
    """Test BacktestEngine initialization."""
    from unittest.mock import MagicMock

    mock_strategy = MagicMock()
    mock_mongo = MagicMock()
    mock_session_maker = MagicMock()

    engine = BacktestEngine(
        strategy=mock_strategy,
        strategy_id="test_strategy",
        from_date=datetime(2024, 1, 1, tzinfo=UTC),
        to_date=datetime(2024, 12, 31, tzinfo=UTC),
        mongo_client=mock_mongo,
        session_maker=mock_session_maker,
        initial_equity=Decimal("100000"),
    )

    assert engine.strategy_id == "test_strategy"
    assert engine.initial_equity == Decimal("100000")
    assert engine.current_equity == Decimal("100000")
    assert len(engine.positions) == 0
    assert len(engine.trade_log) == 0


def test_backtest_position_creation():
    """Test creating a backtest position."""
    from pdp.backtest.engine import BacktestPosition

    position = BacktestPosition(
        symbol="NIFTY",
        quantity=100,
        entry_price=Decimal("20000"),
        entry_time=datetime.now(UTC),
        metadata={"order_id": "123"},
    )

    assert position.symbol == "NIFTY"
    assert position.quantity == 100
    assert position.entry_price == Decimal("20000")
    assert position.metadata["order_id"] == "123"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
