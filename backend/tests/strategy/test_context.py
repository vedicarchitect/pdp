"""Unit tests for StrategyOrderClient risk-cap enforcement."""
from __future__ import annotations

import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pdp.strategy.context import MarketControl, RiskCapBreached, StrategyOrderClient


def _make_client(max_open_orders: int = 2) -> StrategyOrderClient:
    mock_router = MagicMock()
    mock_session_maker = MagicMock()
    return StrategyOrderClient(
        strategy_id="test_strat",
        order_router=mock_router,
        session_maker=mock_session_maker,
        max_open_orders=max_open_orders,
        max_daily_loss_inr=5000.0,
    )


# ---------------------------------------------------------------------------
# 8.5 — RiskCapBreached
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_place_order_blocked_at_max_open_orders():
    """place_order raises RiskCapBreached when open order count reaches cap."""
    client = _make_client(max_open_orders=2)

    # Fake session context manager
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    client._session_maker.return_value = mock_session

    # Patch _count_open_orders to return cap value
    with patch.object(client, "_count_open_orders", new=AsyncMock(return_value=2)):
        with pytest.raises(RiskCapBreached, match="already has 2 open orders"):
            await client.place_order(
                security_id="1333",
                exchange_segment="NSE_FNO",
                side="BUY",
                qty=25,
            )


@pytest.mark.asyncio
async def test_place_order_proceeds_below_cap():
    """place_order calls OrderRouter when below cap."""
    client = _make_client(max_open_orders=3)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    client._session_maker.return_value = mock_session

    mock_order = MagicMock()
    client._router.place_order = AsyncMock(return_value=mock_order)

    with patch.object(client, "_count_open_orders", new=AsyncMock(return_value=1)):
        result = await client.place_order(
            security_id="1333",
            exchange_segment="NSE_FNO",
            side="BUY",
            qty=25,
        )

    assert result is mock_order
    client._router.place_order.assert_awaited_once()


# ---------------------------------------------------------------------------
# GAP 4 — MarketControl pre-registers the sid with the paper broker on subscribe
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subscribe_notifies_paper_broker_before_adapter():
    """MarketControl.subscribe() calls paper_broker.notify_subscribe so the paper
    run-loop watches tick.{sid} before the first order arrives (no missed first fill)."""
    notified: list[str] = []

    class _FakePaperBroker:
        def notify_subscribe(self, security_id: str) -> None:
            notified.append(security_id)

    mc = MarketControl(
        adapter=None, session_maker=None, redis=None, paper_broker=_FakePaperBroker()
    )
    result = await mc.subscribe("OPT_PE", "NSE_FNO")

    assert notified == ["OPT_PE"]
    assert result is False  # no adapter configured -> subscription is a no-op


@pytest.mark.asyncio
async def test_subscribe_without_paper_broker_is_safe():
    """No paper broker wired in: subscribe must not raise."""
    mc = MarketControl(adapter=None, session_maker=None, redis=None, paper_broker=None)
    assert await mc.subscribe("OPT_PE", "NSE_FNO") is False


# ---------------------------------------------------------------------------
# GAP 5 — MarketControl.ltp_with_age returns the LTP age from the ts key
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ltp_with_age_computes_age_from_ts():
    """ltp_with_age returns (price, age) using ltp_ts:{sid}; age reflects how old the tick is."""

    class _FakeRedis:
        def __init__(self, ltp: str, ts: str | None):
            self._vals = [ltp, ts]

        async def mget(self, *keys):
            return self._vals

    ten_secs_ago = str(time.time() - 10.0)
    mc = MarketControl(
        adapter=None, session_maker=None, redis=_FakeRedis("123.5", ten_secs_ago)
    )
    price, age = await mc.ltp_with_age("OPT_PE")
    assert price == Decimal("123.5")
    assert age is not None and 9.0 < age < 12.0


@pytest.mark.asyncio
async def test_ltp_with_age_age_none_when_ts_absent():
    """When the ltp_ts key is missing, the price is still returned but age is None."""

    class _FakeRedis:
        async def mget(self, *keys):
            return ["123.5", None]

    mc = MarketControl(adapter=None, session_maker=None, redis=_FakeRedis())
    price, age = await mc.ltp_with_age("OPT_PE")
    assert price == Decimal("123.5")
    assert age is None
