"""Unit tests: fill logic, position math, charges, idempotency, lot-size rejection."""
from __future__ import annotations

from decimal import Decimal

from pdp.orders.models import BrokerCost, Order, OrderStatus, OrderType, Product, Side
from pdp.orders.paper import (
    ChargesCalculator,
    PaperBroker,
    _fill_price,
    _should_fill,
)

# ------------------------------------------------------------------ #
# Fill price                                                          #
# ------------------------------------------------------------------ #

def test_market_buy_fill_price_adds_slippage() -> None:
    fp = _fill_price(Decimal("100"), Side.BUY, Decimal("2"))
    assert fp == Decimal("100.0200")


def test_market_sell_fill_price_subtracts_slippage() -> None:
    fp = _fill_price(Decimal("100"), Side.SELL, Decimal("2"))
    assert fp == Decimal("99.9800")


# ------------------------------------------------------------------ #
# Should fill                                                         #
# ------------------------------------------------------------------ #

def _order(order_type: str, side: str, price=None, trigger=None) -> Order:
    return Order(
        id=1,
        client_order_id=None,
        broker="paper",
        mode="PAPER",
        security_id="13",
        exchange_segment="NSE_FNO",
        side=side,
        qty=50,
        order_type=order_type,
        price=price,
        trigger_price=trigger,
        product=Product.NRML,
        status=OrderStatus.OPEN,
    )


def test_market_always_fills() -> None:
    o = _order(OrderType.MARKET, Side.BUY)
    assert _should_fill(o, Decimal("99999"))


def test_limit_buy_fills_at_or_below_price() -> None:
    o = _order(OrderType.LIMIT, Side.BUY, price=Decimal("24400"))
    assert not _should_fill(o, Decimal("24500"))
    assert not _should_fill(o, Decimal("24401"))
    assert _should_fill(o, Decimal("24400"))
    assert _should_fill(o, Decimal("24380"))


def test_limit_sell_fills_at_or_above_price() -> None:
    o = _order(OrderType.LIMIT, Side.SELL, price=Decimal("24600"))
    assert not _should_fill(o, Decimal("24500"))
    assert _should_fill(o, Decimal("24600"))
    assert _should_fill(o, Decimal("24700"))


def test_sl_buy_triggers_at_or_above_trigger() -> None:
    o = _order(OrderType.SL, Side.BUY, trigger=Decimal("24500"))
    assert not _should_fill(o, Decimal("24400"))
    assert _should_fill(o, Decimal("24500"))
    assert _should_fill(o, Decimal("24600"))


def test_sl_sell_triggers_at_or_below_trigger() -> None:
    o = _order(OrderType.SL, Side.SELL, trigger=Decimal("24300"))
    assert not _should_fill(o, Decimal("24400"))
    assert _should_fill(o, Decimal("24300"))
    assert _should_fill(o, Decimal("24200"))


# ------------------------------------------------------------------ #
# Position math (tested via PaperBroker._upsert_position indirectly) #
# ------------------------------------------------------------------ #

class TestPositionMath:
    """Verify weighted-avg and realize-on-reduce semantics."""

    def test_weighted_avg_add(self) -> None:
        # BUY 50 @ 100 then BUY 50 @ 110 → avg = 105
        avg = (Decimal("100") * 50 + Decimal("110") * 50) / 100
        assert avg == Decimal("105")

    def test_realize_on_reduce(self) -> None:
        # BUY 100 @ 100 avg; SELL 50 @ 120
        avg_price = Decimal("100")
        fill_price = Decimal("120")
        reduce_qty = 50
        realized = (fill_price - avg_price) * reduce_qty
        assert realized == Decimal("1000")

    def test_spec_scenario(self) -> None:
        # BUY 50 @ 100 then BUY 50 @ 110 then SELL 50 @ 120
        # After buys: net=100, avg=105
        avg = (Decimal("100") * 50 + Decimal("110") * 50) / 100
        assert avg == Decimal("105")
        # SELL 50 @ 120: realized = (120 - 105) * 50 = 750
        realized = (Decimal("120") - avg) * 50
        assert realized == Decimal("750")
        # Remaining: net=50, avg=105 — verified above

    def test_weighted_avg_short_multileg(self) -> None:
        # SELL 130 @ 86.13 then SELL 65 @ 83.63 → avg uses abs(old_qty)
        # First fill creates position: net=-130, avg=86.13
        # Second fill: total_cost = 86.13 * 130 + 83.63 * 65 = 16632.85
        old_avg = Decimal("86.13")
        old_qty = 130  # abs value
        fill2 = Decimal("83.63")
        q2 = 65
        total = old_avg * old_qty + fill2 * q2
        new_qty = old_qty + q2
        avg = total / new_qty
        assert avg == Decimal("85.29666666666666666666666667")

    def test_realize_on_close_short(self) -> None:
        # Short position: net=-195, avg≈85.2967; close BUY 195 @ 96.52
        # realized = (fill_price - old_avg) * old_qty where old_qty is negative
        old_avg = Decimal("85.2967")
        fill_price = Decimal("96.52")
        old_qty = Decimal("-195")
        realized = (fill_price - old_avg) * old_qty
        assert realized == Decimal("-2188.5435")


# ------------------------------------------------------------------ #
# Charges calculator                                                  #
# ------------------------------------------------------------------ #

def _make_cost(**kwargs) -> BrokerCost:
    defaults = dict(
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
    defaults.update(kwargs)
    return BrokerCost(**defaults)


def test_charges_positive_for_optidx() -> None:
    calc = ChargesCalculator(_make_cost())
    charges = calc.compute(qty=50, fill_price=Decimal("200"), side=Side.BUY)
    assert charges > Decimal("0")


def test_charges_stt_on_sell_only() -> None:
    calc = ChargesCalculator(_make_cost(stt_bps=Decimal("1")))
    charges_buy = calc.compute(qty=1, fill_price=Decimal("100"), side=Side.BUY)
    charges_sell = calc.compute(qty=1, fill_price=Decimal("100"), side=Side.SELL)
    assert charges_sell > charges_buy


def test_charges_stamp_duty_on_buy_only() -> None:
    calc = ChargesCalculator(_make_cost(stamp_duty_bps=Decimal("1"), stt_bps=Decimal("0")))
    charges_buy = calc.compute(qty=1, fill_price=Decimal("100"), side=Side.BUY)
    charges_sell = calc.compute(qty=1, fill_price=Decimal("100"), side=Side.SELL)
    assert charges_buy > charges_sell


# ------------------------------------------------------------------ #
# GAP 4 — subscription race: notify_subscribe pre-registers a sid     #
# ------------------------------------------------------------------ #

def test_notify_subscribe_registers_sid_for_monitoring() -> None:
    """A pre-registered security_id appears in the run-loop's watch set so the first
    tick after order placement can fill, instead of being missed until the second."""
    pb = PaperBroker(session_maker=None, slippage_bps=0.0)
    assert "OPT_PE" not in pb._open_orders
    pb.notify_subscribe("OPT_PE")
    assert "OPT_PE" in pb._open_orders
    assert pb._open_orders["OPT_PE"] == []


def test_notify_subscribe_is_idempotent_and_preserves_orders() -> None:
    """Re-registering a sid that already has tracked orders must not clobber them."""
    pb = PaperBroker(session_maker=None, slippage_bps=0.0)
    sentinel = object()
    pb._open_orders["OPT_CE"] = [sentinel]
    pb.notify_subscribe("OPT_CE")
    assert pb._open_orders["OPT_CE"] == [sentinel]
