"""
Integration tests for the paper broker fill pipeline.

These tests do NOT require a running database — they exercise the pure logic
of PaperBroker._fill, position upsert, and charges by injecting mock sessions
and stubs.  DB integration tests (with a real Postgres) are deferred to CI.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from pdp.orders.models import (
    BrokerCost,
    Order,
    OrderStatus,
    OrderType,
    Position,
    PreflightResult,
    Product,
    Side,
    TradeMode,
)
from pdp.orders.paper import PaperBroker, _should_fill
from pdp.orders.router import OrderRouter
from pdp.risk.feed_halt import FeedStaleHalt


def _open_order(
    order_id: int = 1,
    security_id: str = "13",
    side: str = Side.BUY,
    qty: int = 50,
    order_type: str = OrderType.MARKET,
    price=None,
    trigger=None,
) -> Order:
    return Order(
        id=order_id,
        client_order_id=f"cid-{order_id}",
        broker="paper",
        mode="PAPER",
        security_id=security_id,
        exchange_segment="NSE_FNO",
        side=side,
        qty=qty,
        order_type=order_type,
        price=price,
        trigger_price=trigger,
        product=Product.NRML,
        status=OrderStatus.OPEN,
    )


def _cost_row() -> BrokerCost:
    return BrokerCost(
        broker="paper",
        instrument_type="FUTIDX",
        brokerage_bps=Decimal("0"),
        brokerage_flat=Decimal("20"),
        stt_bps=Decimal("1"),
        exchange_fee_bps=Decimal("0.05"),
        gst_pct=Decimal("18"),
        sebi_charges_bps=Decimal("0.0001"),
        stamp_duty_bps=Decimal("0.002"),
    )


# ------------------------------------------------------------------ #
# Fill logic tests (pure, no DB)                                      #
# ------------------------------------------------------------------ #

class TestFillLogic:
    def test_market_order_fills_on_any_tick(self) -> None:
        o = _open_order(order_type=OrderType.MARKET)
        assert _should_fill(o, Decimal("24500"))

    def test_limit_buy_does_not_fill_above_limit(self) -> None:
        o = _open_order(order_type=OrderType.LIMIT, price=Decimal("24400"))
        assert not _should_fill(o, Decimal("24500"))
        assert not _should_fill(o, Decimal("24450"))

    def test_limit_buy_fills_at_limit(self) -> None:
        o = _open_order(order_type=OrderType.LIMIT, price=Decimal("24400"))
        assert _should_fill(o, Decimal("24400"))
        assert _should_fill(o, Decimal("24380"))

    def test_limit_sell_does_not_fill_below_limit(self) -> None:
        o = _open_order(order_type=OrderType.LIMIT, side=Side.SELL, price=Decimal("24600"))
        assert not _should_fill(o, Decimal("24500"))

    def test_limit_sell_fills_at_or_above_limit(self) -> None:
        o = _open_order(order_type=OrderType.LIMIT, side=Side.SELL, price=Decimal("24600"))
        assert _should_fill(o, Decimal("24600"))
        assert _should_fill(o, Decimal("24700"))


# ------------------------------------------------------------------ #
# Position math tests                                                 #
# ------------------------------------------------------------------ #

class TestPositionMathDirect:
    """Test position upsert logic without DB by calling internals directly."""

    @pytest.mark.asyncio
    async def test_add_to_existing_long_position(self) -> None:
        """BUY 50 @ 100 then BUY 50 @ 110 → avg_price = 105."""
        broker = PaperBroker.__new__(PaperBroker)
        broker._slippage_bps = Decimal("0")
        broker._costs = {}
        broker._hub = None

        # Existing position
        pos = Position(
            id=1,
            security_id="13",
            exchange_segment="NSE_FNO",
            product=Product.NRML,
            net_qty=50,
            avg_price=Decimal("100"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
        )

        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: pos))
        session.flush = AsyncMock()

        order = _open_order(side=Side.BUY, qty=50)
        await broker._upsert_position(session, order, Decimal("110"), datetime.now(UTC))

        assert pos.net_qty == 100
        assert pos.avg_price == Decimal("105.0000")

    @pytest.mark.asyncio
    async def test_realize_on_reduce(self) -> None:
        """BUY 50 @ 105 avg, SELL 50 @ 120 → realized_pnl = 750, net = 0."""
        broker = PaperBroker.__new__(PaperBroker)
        broker._slippage_bps = Decimal("0")
        broker._costs = {}
        broker._hub = None

        pos = Position(
            id=1,
            security_id="13",
            exchange_segment="NSE_FNO",
            product=Product.NRML,
            net_qty=50,
            avg_price=Decimal("105"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
        )

        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: pos))
        session.flush = AsyncMock()

        order = _open_order(side=Side.SELL, qty=50)
        await broker._upsert_position(session, order, Decimal("120"), datetime.now(UTC))

        assert pos.net_qty == 0
        assert pos.realized_pnl == Decimal("750.0000")

    @pytest.mark.asyncio
    async def test_short_multileg_weighted_avg(self) -> None:
        """SELL 65 @ 83.63 added to existing short (-130 @ 86.13) → avg = 85.2967."""
        broker = PaperBroker.__new__(PaperBroker)
        broker._slippage_bps = Decimal("0")
        broker._costs = {}
        broker._hub = None

        pos = Position(
            id=1,
            security_id="13",
            exchange_segment="NSE_FNO",
            product=Product.NRML,
            net_qty=-130,
            avg_price=Decimal("86.13"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
        )

        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: pos))
        session.flush = AsyncMock()

        order = _open_order(side=Side.SELL, qty=65)
        await broker._upsert_position(session, order, Decimal("83.63"), datetime.now(UTC))

        assert pos.net_qty == -195
        assert pos.avg_price == Decimal("85.2967")

    @pytest.mark.asyncio
    async def test_short_close_realized_pnl(self) -> None:
        """BUY 195 @ 96.52 closes short (-195 @ 85.2967) → realized_pnl = -2188.5435."""
        broker = PaperBroker.__new__(PaperBroker)
        broker._slippage_bps = Decimal("0")
        broker._costs = {}
        broker._hub = None

        pos = Position(
            id=1,
            security_id="13",
            exchange_segment="NSE_FNO",
            product=Product.NRML,
            net_qty=-195,
            avg_price=Decimal("85.2967"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
        )

        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: pos))
        session.flush = AsyncMock()

        order = _open_order(side=Side.BUY, qty=195)
        await broker._upsert_position(session, order, Decimal("96.52"), datetime.now(UTC))

        assert pos.net_qty == 0
        assert pos.realized_pnl == Decimal("-2188.5435")


# ------------------------------------------------------------------ #
# Charges                                                             #
# ------------------------------------------------------------------ #

class TestChargesIntegration:
    def test_optidx_charges_positive(self) -> None:
        from pdp.orders.paper import ChargesCalculator

        cost = BrokerCost(
            broker="paper",
            instrument_type="OPTIDX",
            brokerage_bps=Decimal("0"),
            brokerage_flat=Decimal("20"),
            stt_bps=Decimal("0.05"),
            exchange_fee_bps=Decimal("0.53"),
            gst_pct=Decimal("18"),
            sebi_charges_bps=Decimal("0.0001"),
            stamp_duty_bps=Decimal("0.003"),
        )
        calc = ChargesCalculator(cost)
        charges = calc.compute(qty=50, fill_price=Decimal("200"), side=Side.SELL)
        assert charges > Decimal("0"), f"charges should be positive, got {charges}"


# ------------------------------------------------------------------ #
# cancel_open_entry_orders                                            #
# ------------------------------------------------------------------ #

def _make_settings(live: bool = False) -> MagicMock:
    s = MagicMock()
    s.LIVE = live
    s.BROKER = "paper"
    s.DHAN_CLIENT_ID = None
    return s


class TestCancelOpenEntryOrders:
    @pytest.mark.asyncio
    async def test_cancels_open_sell_and_removes_from_broker(self) -> None:
        """OPEN SELL in broker watch list → status CANCELLED + removed from _open_orders."""
        paper = PaperBroker.__new__(PaperBroker)
        paper._open_orders = {}

        order = _open_order(order_id=42, security_id="13", side=Side.SELL, qty=130)
        order.strategy_id = "st_01"
        paper._open_orders["13"] = [order]

        router = OrderRouter(settings=_make_settings(), paper=paper)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [order]
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)
        session.commit = AsyncMock()

        cancelled = await router.cancel_open_entry_orders(session, "13", "st_01")

        assert cancelled == [42]
        assert order.status == OrderStatus.CANCELLED
        assert order.cancelled_at is not None
        assert paper._open_orders.get("13", []) == []

    @pytest.mark.asyncio
    async def test_noop_when_no_open_sells(self) -> None:
        """No OPEN SELLs → returns empty list, no DB commit."""
        paper = PaperBroker.__new__(PaperBroker)
        paper._open_orders = {}

        router = OrderRouter(settings=_make_settings(), paper=paper)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)
        session.commit = AsyncMock()

        cancelled = await router.cancel_open_entry_orders(session, "13", "st_01")

        assert cancelled == []
        session.commit.assert_not_called()


# ------------------------------------------------------------------ #
# R2 — zero-avg guard + immediate-fill from Redis cache (hardening)   #
# ------------------------------------------------------------------ #

class TestZeroAvgGuard:
    """upsert_position must not compute realized P&L when old_avg == 0."""

    @pytest.mark.asyncio
    async def test_close_short_with_zero_avg_yields_zero_realized(self) -> None:
        """Closing a short position whose avg_price=0 must leave realized_pnl untouched."""
        broker = PaperBroker.__new__(PaperBroker)
        broker._slippage_bps = Decimal("0")
        broker._costs = {}
        broker._hub = None

        pos = Position(
            id=1,
            security_id="13",
            exchange_segment="NSE_FNO",
            product=Product.NRML,
            net_qty=-50,
            avg_price=Decimal("0"),   # race condition: fill recorded zero
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
        )
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: pos))
        session.flush = AsyncMock()

        order = _open_order(side=Side.BUY, qty=50)  # closing buy
        await broker._upsert_position(session, order, Decimal("100"), datetime.now(UTC))

        # P&L must be 0, not (0 - 100) * (-50) = +5000 or (100 - 0) * 50 = +5000
        assert pos.realized_pnl == Decimal("0"), (
            f"expected 0 realized P&L for zero-avg position, got {pos.realized_pnl}"
        )
        assert pos.net_qty == 0

    @pytest.mark.asyncio
    async def test_reduce_long_with_zero_avg_yields_zero_realized(self) -> None:
        """Partial close of a long position with avg=0 must not compute realized P&L."""
        broker = PaperBroker.__new__(PaperBroker)
        broker._slippage_bps = Decimal("0")
        broker._costs = {}
        broker._hub = None

        pos = Position(
            id=1,
            security_id="13",
            exchange_segment="NSE_FNO",
            product=Product.NRML,
            net_qty=100,
            avg_price=Decimal("0"),
            realized_pnl=Decimal("50"),   # pre-existing realized from earlier
            unrealized_pnl=Decimal("0"),
        )
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: pos))
        session.flush = AsyncMock()

        order = _open_order(side=Side.SELL, qty=50)
        await broker._upsert_position(session, order, Decimal("120"), datetime.now(UTC))

        # realized should remain at 50, not 50 + (120 - 0) * 50
        assert pos.realized_pnl == Decimal("50"), (
            f"expected realized_pnl unchanged at 50, got {pos.realized_pnl}"
        )
        assert pos.net_qty == 50

    @pytest.mark.asyncio
    async def test_normal_close_short_still_works(self) -> None:
        """Guard must not break the normal non-zero avg_price path."""
        broker = PaperBroker.__new__(PaperBroker)
        broker._slippage_bps = Decimal("0")
        broker._costs = {}
        broker._hub = None

        pos = Position(
            id=1,
            security_id="13",
            exchange_segment="NSE_FNO",
            product=Product.NRML,
            net_qty=-50,
            avg_price=Decimal("85.30"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
        )
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: pos))
        session.flush = AsyncMock()

        order = _open_order(side=Side.BUY, qty=50)
        await broker._upsert_position(session, order, Decimal("96.52"), datetime.now(UTC))

        # realized = (85.30 - 96.52) * 50 = -561.0
        assert pos.realized_pnl == Decimal("-561.0000")
        assert pos.net_qty == 0


class TestImmediateFillFromCache:
    """MARKET orders should fill immediately from Redis LTP cache when available."""

    @pytest.mark.asyncio
    async def test_market_order_fills_from_cached_ltp(self) -> None:
        """When Redis has a cached LTP for the SID, add_order() must fill immediately."""
        broker = PaperBroker.__new__(PaperBroker)
        broker._slippage_bps = Decimal("2")
        broker._costs = {}
        broker._hub = None
        broker._open_orders = {}

        # Mock Redis: returns a valid LTP (decode_responses=True means string, not bytes)
        redis = AsyncMock()
        redis.get = AsyncMock(return_value="150.50")
        broker._redis = redis

        # Mock _fill to capture calls
        broker._fill = AsyncMock()

        order = _open_order(order_id=5, security_id="OPT_1234", order_type=OrderType.MARKET)
        await broker.add_order(order)

        broker._fill.assert_called_once()
        call_args = broker._fill.call_args
        assert call_args[0][0] is order
        assert call_args[0][1] == Decimal("150.50")

    @pytest.mark.asyncio
    async def test_market_order_no_fill_when_no_cached_ltp(self) -> None:
        """When Redis has no cached LTP, add_order() leaves the order OPEN for pub/sub fill."""
        broker = PaperBroker.__new__(PaperBroker)
        broker._slippage_bps = Decimal("2")
        broker._costs = {}
        broker._hub = None
        broker._open_orders = {}

        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        broker._redis = redis
        broker._fill = AsyncMock()

        order = _open_order(order_id=6, security_id="OPT_5678", order_type=OrderType.MARKET)
        await broker.add_order(order)

        broker._fill.assert_not_called()
        # Order remains in the watch list for pub/sub fill
        assert order in broker._open_orders.get("OPT_5678", [])


# ------------------------------------------------------------------ #
# W3 — Paper advisory: preflight failure must not block paper orders  #
# ------------------------------------------------------------------ #

def _make_paper_broker() -> PaperBroker:
    broker = PaperBroker.__new__(PaperBroker)
    broker._open_orders = {}
    broker._costs = {}
    broker._redis = None
    broker._hub = None
    broker.add_order = AsyncMock()
    return broker


def _make_mock_session(existing_order=None) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing_order
    result.first.return_value = None  # no instrument row → _validate_lot_size skips
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()  # session.add is synchronous in SQLAlchemy
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


async def _place(router: OrderRouter, session: AsyncMock) -> Order:
    return await router.place_order(
        session,
        client_order_id=None,
        security_id="OPT_1234",
        exchange_segment="NSE_FNO",
        side="SELL",
        qty=100,
        order_type="MARKET",
        price=None,
        trigger_price=None,
        product="NRML",
        strategy_id="st_01",
    )


class TestPaperAdvisory:
    @pytest.mark.asyncio
    async def test_paper_advisory_does_not_block_order(self) -> None:
        """Preflight violations in paper mode are advisory: order must still be OPEN."""
        paper = _make_paper_broker()
        settings = _make_settings(live=False)
        settings.ORDER_PREFLIGHT_ENABLED = True

        router = OrderRouter(settings=settings, paper=paper)
        # Force _preflight to return a violation
        router._preflight = AsyncMock(
            return_value=PreflightResult(ok=False, violations=["lot_check_failed"])
        )

        order = await _place(router, _make_mock_session())

        assert order.status == OrderStatus.OPEN, (
            f"paper advisory must not block — expected OPEN, got {order.status}"
        )
        paper.add_order.assert_called_once_with(order)

    @pytest.mark.asyncio
    async def test_live_preflight_failure_blocks_order(self) -> None:
        """Preflight violations in live mode must REJECT the order."""
        paper = _make_paper_broker()
        settings = MagicMock()
        settings.LIVE = True
        settings.BROKER = "dhan"
        settings.DHAN_CLIENT_ID = "client123"
        settings.ORDER_PREFLIGHT_ENABLED = True

        router = OrderRouter(settings=settings, paper=paper)
        router._preflight = AsyncMock(
            return_value=PreflightResult(ok=False, violations=["insufficient_margin"])
        )

        order = await _place(router, _make_mock_session())

        assert order.status == OrderStatus.REJECTED
        assert "insufficient_margin" in (order.reject_reason or "")
        paper.add_order.assert_not_called()


# ------------------------------------------------------------------ #
# W4 — Feed-halt gate: live orders blocked when halt engaged          #
# ------------------------------------------------------------------ #

class TestFeedHaltGate:
    @pytest.mark.asyncio
    async def test_feed_stale_halt_blocks_live_order(self) -> None:
        """When FeedStaleHalt is engaged, live MARKET orders must be REJECTED immediately."""
        feed_halt = FeedStaleHalt(halt_after_seconds=0)
        feed_halt.on_feed_stale()
        feed_halt.on_feed_stale()
        assert feed_halt.live_blocked is True

        paper = _make_paper_broker()
        settings = MagicMock()
        settings.LIVE = True
        settings.BROKER = "dhan"
        settings.DHAN_CLIENT_ID = "client123"
        settings.ORDER_PREFLIGHT_ENABLED = False  # skip preflight

        router = OrderRouter(settings=settings, paper=paper, feed_halt=feed_halt)
        order = await _place(router, _make_mock_session())

        assert order.status == OrderStatus.REJECTED
        assert "feed_stale_halt" in (order.reject_reason or ""), (
            f"reject_reason should mention feed_stale_halt, got: {order.reject_reason!r}"
        )
        paper.add_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_paper_order_unaffected_by_feed_halt(self) -> None:
        """Feed-halt must NOT block paper orders (no real money at risk)."""
        feed_halt = FeedStaleHalt(halt_after_seconds=0)
        feed_halt.on_feed_stale()
        feed_halt.on_feed_stale()
        assert feed_halt.live_blocked is True

        paper = _make_paper_broker()
        settings = _make_settings(live=False)  # PAPER mode
        settings.ORDER_PREFLIGHT_ENABLED = False

        router = OrderRouter(settings=settings, paper=paper, feed_halt=feed_halt)
        order = await _place(router, _make_mock_session())

        assert order.status == OrderStatus.OPEN
        paper.add_order.assert_called_once_with(order)
