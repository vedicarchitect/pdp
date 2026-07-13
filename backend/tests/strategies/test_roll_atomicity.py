"""Tests for atomicity of the roll path in directional strangle.

These tests reproduce missing atomic guarantees on HEAD before the
strangle-close-path-atomicity fix.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pdp.strategies.directional_strangle import DirectionalStrangle, OpenLeg
from pdp.strategy.log import StrangleEventType


class _FakeOrders:
    def __init__(self):
        self._pos: dict[str, dict] = {}
        self.calls: list[dict] = []
        self.cancel_calls: list[str] = []

    def _p(self, sid: str) -> dict:
        return self._pos.setdefault(sid, {"net": 0, "avg": Decimal("0"), "realized": Decimal("0")})

    def set_net_qty(self, security_id: str, qty: int):
        self._p(security_id)["net"] = qty

    async def place_order(self, *, security_id, side, qty, **kw):
        self.calls.append({"sid": security_id, "side": side, "qty": qty})
        p = self._p(security_id)
        side_s = str(side)
        qty_i = int(qty)
        price = Decimal("100")
        if side_s == "SELL":
            p["avg"] = price
            p["net"] -= qty_i
        elif side_s == "BUY":
            if p["net"] < 0:
                cover = min(qty_i, abs(p["net"]))
                p["realized"] += (p["avg"] - price) * cover
                p["net"] += cover
            else:
                p["net"] += qty_i
        return SimpleNamespace(status="OPEN", id=len(self.calls))

    async def get_net_qty(self, security_id: str) -> int:
        return self._p(security_id)["net"]

    async def get_position(self, security_id: str) -> tuple[int, Decimal]:
        p = self._p(security_id)
        return p["net"], p["avg"]

    async def get_realized_pnl(self, security_id: str) -> Decimal:
        return self._p(security_id)["realized"]

    async def cancel_open_entry_orders(self, security_id: str) -> list[int]:
        self.cancel_calls.append(security_id)
        return []

    async def get_positions(self) -> list:
        return [
            SimpleNamespace(security_id=sid, net_qty=p["net"], exchange_segment="NSE_FNO")
            for sid, p in self._pos.items()
            if p["net"] != 0
        ]

    @property
    def strategy_id(self) -> str:
        return "directional_strangle"


def _make_instrument(sid: str, strike: float, opt_type: str = "CE"):
    return SimpleNamespace(
        security_id=sid,
        exchange_segment="NSE_FNO",
        strike=Decimal(str(strike)),
        option_type=opt_type,
        expiry=date(2026, 7, 9),
    )


async def _build_strategy(
    params: dict | None = None,
    ltp_override: float | None = None,
) -> DirectionalStrangle:
    s = DirectionalStrangle()
    s.strategy_id = "directional_strangle"
    s._mode = "paper"
    s._slog = None

    ind = MagicMock()
    ind.ema.return_value = None
    ind.pivots.return_value = None
    ind.period_levels.return_value = None
    ind.vwap.return_value = None

    market = MagicMock()
    market.subscribe = AsyncMock(return_value=True)
    market.unsubscribe = AsyncMock()
    ltp_val = Decimal(str(ltp_override or 100.0))
    market.ltp_with_age = AsyncMock(return_value=(ltp_val, 0.1))
    market.cache_get = AsyncMock(return_value=None)
    market.cache_set = AsyncMock()

    orders = _FakeOrders()

    class _MockSession:
        async def __aenter__(self):
            m = MagicMock()
            m.commit = AsyncMock()
            m.execute = AsyncMock()
            m.add = MagicMock()
            empty_res = MagicMock()
            empty_res.all.return_value = []
            m.scalars = AsyncMock(return_value=empty_res)
            m.scalar = AsyncMock(return_value=None)
            m.begin = MagicMock()
            m.begin.return_value.__aenter__ = AsyncMock()
            m.begin.return_value.__aexit__ = AsyncMock()
            return m
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    session_maker = MagicMock(return_value=_MockSession())

    ctx = SimpleNamespace(
        params=params or {},
        watchlist=[],
        log=MagicMock(),
        indicators=ind,
        market=market,
        orders=orders,
        session_maker=session_maker,
        chain_hub=None,
        _event_service=None,
    )

    def _emit_critical(event_type, security_id, title, message, payload=None):
        if ctx._event_service is not None:
            ctx._event_service.emit_critical(event_type, security_id, title, message, payload)
        # Store in activity for assertions
        s._activity.append({
            "event_type": str(event_type),
            "sid": security_id,
            "title": title,
            "message": message,
        })

    ctx.emit_critical = _emit_critical

    await s.on_init(ctx)
    return s


def _make_tick(security_id: str, ltp: float):
    return SimpleNamespace(security_id=security_id, ltp=ltp)


@pytest.mark.asyncio
async def test_skipped_no_spot_leaves_position_open():
    """1.1 _last_spot = None, trigger a roll -> assert leg is still in _short_legs and zero orders placed."""
    s = await _build_strategy(params={"roll_trigger_prem": 20.0, "roll_target_min_prem": 50.0})
    fake_leg = OpenLeg(security_id="999", segment="NSE_FNO", opt_type="CE", strike=24200.0, lots=2, entry_price=Decimal("100"))
    fake_hedge = OpenLeg(security_id="999_h", segment="NSE_FNO", opt_type="CE", strike=24500.0, lots=2, entry_price=Decimal("10"))
    
    s._legs[fake_leg.security_id] = fake_leg
    fake_hedge.kind = "hedge"
    s._legs[fake_hedge.security_id] = fake_hedge
    s._ltp_cache["999"] = 10.0  # triggers roll
    s._ltp_cache["999_h"] = 1.0
    s.ctx.orders.set_net_qty("999", -2 * s._lot_size)
    s.ctx.orders.set_net_qty("999_h", 2 * s._lot_size)
    s._last_spot = None

    await s.on_tick(_make_tick("999", 10.0))

    # Expecting failure on HEAD because it places close orders before checking spot
    assert len(s.ctx.orders.calls) == 0, f"Expected 0 orders placed, got {len(s.ctx.orders.calls)}"
    assert fake_leg in s._short_legs
    assert fake_hedge in s._hedge_legs


@pytest.mark.asyncio
async def test_no_instrument_leaves_position_open():
    """1.2 resolve_otm_option returns None -> same assertions."""
    s = await _build_strategy(params={"roll_trigger_prem": 20.0, "roll_target_min_prem": 50.0})
    fake_leg = OpenLeg(security_id="999", segment="NSE_FNO", opt_type="CE", strike=24200.0, lots=2, entry_price=Decimal("100"))
    fake_hedge = OpenLeg(security_id="999_h", segment="NSE_FNO", opt_type="CE", strike=24500.0, lots=2, entry_price=Decimal("10"))
    
    s._legs[fake_leg.security_id] = fake_leg
    fake_hedge.kind = "hedge"
    s._legs[fake_hedge.security_id] = fake_hedge
    s._ltp_cache["999"] = 10.0
    s._ltp_cache["999_h"] = 1.0
    s.ctx.orders.set_net_qty("999", -2 * s._lot_size)
    s.ctx.orders.set_net_qty("999_h", 2 * s._lot_size)
    s._last_spot = 24000.0

    async def dummy_res_none(*args, **kwargs): return None
    with patch("pdp.strategies.directional_strangle.resolve_otm_option", new_callable=lambda: dummy_res_none):
        await s.on_tick(_make_tick("999", 10.0))

    assert len(s.ctx.orders.calls) == 0
    assert fake_leg in s._short_legs
    assert fake_hedge in s._hedge_legs


@pytest.mark.asyncio
async def test_low_premium_leaves_position_open():
    """1.3 new premium < roll_target_min_prem -> same assertions."""
    s = await _build_strategy(params={"roll_trigger_prem": 20.0, "roll_target_min_prem": 50.0})
    fake_leg = OpenLeg(security_id="999", segment="NSE_FNO", opt_type="CE", strike=24200.0, lots=2, entry_price=Decimal("100"))
    fake_hedge = OpenLeg(security_id="999_h", segment="NSE_FNO", opt_type="CE", strike=24500.0, lots=2, entry_price=Decimal("10"))
    
    s._legs[fake_leg.security_id] = fake_leg
    fake_hedge.kind = "hedge"
    s._legs[fake_hedge.security_id] = fake_hedge
    s._ltp_cache["999"] = 10.0
    s._ltp_cache["999_h"] = 1.0
    s.ctx.orders.set_net_qty("999", -2 * s._lot_size)
    s.ctx.orders.set_net_qty("999_h", 2 * s._lot_size)
    s._last_spot = 24000.0

    new_inst = _make_instrument("888", 24200.0, "CE")
    s.ctx.market.ltp_with_age = AsyncMock(return_value=(Decimal("40.0"), 0.1)) # < 50.0

    async def dummy_res(*args, **kwargs): return new_inst
    with patch("pdp.strategies.directional_strangle.resolve_otm_option", new_callable=lambda: dummy_res):
        await s.on_tick(_make_tick("999", 10.0))

    assert len(s.ctx.orders.calls) == 0
    assert fake_leg in s._short_legs
    assert fake_hedge in s._hedge_legs


@pytest.mark.asyncio
async def test_concurrent_roll_runs_once():
    """1.4 gather two on_tick calls for one sid -> exactly one roll, one close, one open."""
    s = await _build_strategy(params={"roll_trigger_prem": 20.0, "roll_target_min_prem": 50.0})
    fake_leg = OpenLeg(security_id="999", segment="NSE_FNO", opt_type="CE", strike=24200.0, lots=2, entry_price=Decimal("100"))
    s._legs[fake_leg.security_id] = fake_leg
    s._ltp_cache["999"] = 10.0
    s.ctx.orders.set_net_qty("999", -2 * s._lot_size)
    s._last_spot = 24000.0

    new_inst = _make_instrument("888", 24200.0, "CE")
    s.ctx.market.ltp_with_age = AsyncMock(return_value=(Decimal("60.0"), 0.1))

    async def dummy_res(*args, **kwargs):
        if kwargs.get("otm_steps", 0) > 2:
            return _make_instrument("888_h", 24500.0, "CE")
        return new_inst
    with patch("pdp.strategies.directional_strangle.resolve_otm_option", new_callable=lambda: dummy_res):
        await asyncio.gather(
            s.on_tick(_make_tick("999", 10.0)),
            s.on_tick(_make_tick("999", 10.0))
        )

    assert len(s.ctx.orders.calls) == 3, "Expected exactly one close and one open (with hedge) = 3 orders"


@pytest.mark.asyncio
async def test_close_and_open_do_not_interleave():
    """1.5 gather a close and an open on one sid; assert get_net_qty is not read between the other's read and place."""
    s = await _build_strategy(params={"roll_trigger_prem": 20.0, "roll_target_min_prem": 50.0})
    
    trace = []
    
    orig_get_net = s.ctx.orders.get_net_qty
    orig_place = s.ctx.orders.place_order

    async def _mock_get_net(sid):
        await asyncio.sleep(0.01)
        trace.append(("get_net", sid))
        return await orig_get_net(sid)
        
    async def _mock_place(**kw):
        await asyncio.sleep(0.01)
        trace.append(("place", kw["security_id"]))
        return await orig_place(**kw)

    s.ctx.orders.get_net_qty = _mock_get_net
    s.ctx.orders.place_order = _mock_place

    fake_leg = OpenLeg(security_id="999", segment="NSE_FNO", opt_type="CE", strike=24200.0, lots=2, entry_price=Decimal("100"))
    s._legs[fake_leg.security_id] = fake_leg
    s._ltp_cache["999"] = 100.0
    s.ctx.orders.set_net_qty("999", -2 * s._lot_size)

    new_inst = _make_instrument("888", 24200.0, "CE")
    async def dummy_res(*args, **kwargs):
        if kwargs.get("otm_steps", 0) > 2:
            return _make_instrument("888_h", 24500.0, "CE")
        return new_inst
    with patch("pdp.strategies.directional_strangle.resolve_otm_option", new_callable=lambda: dummy_res):
        await asyncio.gather(
            s._close_leg(fake_leg, "tp"),
            s._open_short(spot=24200.0, opt_type="CE", lots=1)
        )

    pattern = [t[0] for t in trace if t[1] == "999"]
    if len(pattern) >= 2:
        for i in range(len(pattern) - 1):
            if pattern[i] == "get_net" and pattern[i+1] == "get_net":
                pytest.fail("Interleaving detected: get_net -> get_net without a place in between")


@pytest.mark.asyncio
async def test_close_reduces_only_this_legs_lots():
    """1.6 broker net_qty = 8 lots, leg holds 4 -> closing order is 4 lots, not 8."""
    s = await _build_strategy()
    s.ctx.orders.set_net_qty("999", -8 * s._lot_size)
    fake_leg = OpenLeg(security_id="999", segment="NSE_FNO", opt_type="CE", strike=24200.0, lots=4, entry_price=Decimal("100"), kind="short")
    s._legs[fake_leg.security_id] = fake_leg
    s._ltp_cache["999"] = 100.0

    await s._close_leg(fake_leg, "tp")

    assert len(s.ctx.orders.calls) == 1
    assert s.ctx.orders.calls[0]["qty"] == 4 * s._lot_size, f"Order placed for {s.ctx.orders.calls[0]['qty']} lots, expected 4"


@pytest.mark.asyncio
async def test_duplicate_leg_for_security_is_rejected():
    """1.7 _add_leg rejects a second OpenLeg for a sid already tracked, raises
    ValueError, and emits a LEG_STATE_DIVERGED critical event — the exact
    4->8->16 leg-growth mechanism this guard exists to catch."""
    s = await _build_strategy()
    leg1 = OpenLeg(security_id="999", segment="NSE_FNO", opt_type="CE", strike=24200.0, lots=2, entry_price=Decimal("100"))
    leg2 = OpenLeg(security_id="999", segment="NSE_FNO", opt_type="CE", strike=24200.0, lots=2, entry_price=Decimal("100"))

    s._add_leg(leg1)
    assert s._legs["999"] is leg1

    with pytest.raises(ValueError, match="duplicate leg for security_id 999"):
        s._add_leg(leg2)

    # The original leg is untouched — the rejected duplicate never overwrote it.
    assert s._legs["999"] is leg1

    assert any(
        a["event_type"] == "LEG_STATE_DIVERGED" and a["sid"] == "999"
        for a in s._activity
    )


@pytest.mark.asyncio
async def test_legs_never_vanish_under_concurrent_roll():
    """1.8 drive two concurrent rolls on one sid... after each step assert sum(lots) == broker net_qty."""
    s = await _build_strategy(params={"roll_trigger_prem": 20.0, "roll_target_min_prem": 50.0})
    fake_leg = OpenLeg(security_id="999", segment="NSE_FNO", opt_type="CE", strike=24200.0, lots=2, entry_price=Decimal("100"))
    s._legs[fake_leg.security_id] = fake_leg
    s._ltp_cache["999"] = 10.0
    s.ctx.orders.set_net_qty("999", -2 * s._lot_size)
    s._last_spot = 24000.0

    new_inst = _make_instrument("888", 24200.0, "CE")
    s.ctx.market.ltp_with_age = AsyncMock(return_value=(Decimal("60.0"), 0.1))

    async def dummy_res(*args, **kwargs):
        if kwargs.get("otm_steps", 0) > 2:
            return _make_instrument("888_h", 24500.0, "CE")
        return new_inst
    with patch("pdp.strategies.directional_strangle.resolve_otm_option", new_callable=lambda: dummy_res):
        await asyncio.gather(
            s.on_tick(_make_tick("999", 10.0)),
            s.on_tick(_make_tick("999", 10.0))
        )
    
    mem_lots = sum(l.lots for l in s._short_legs + s._hedge_legs + s._momentum_legs)
    broker_lots = sum(abs(p["net"]) for p in s.ctx.orders._pos.values()) // s._lot_size
    assert mem_lots == broker_lots, f"Memory vanished: mem {mem_lots}, broker {broker_lots}"


@pytest.mark.asyncio
async def test_close_all_closes_orphan_position():
    """1.9 broker holds a position no leg list references -> square-off closes it and emits a critical event."""
    s = await _build_strategy()
    s.ctx.orders.set_net_qty("orphan_999", -2 * s._lot_size)
    
    await s._close_all("square_off")

    assert len(s.ctx.orders.calls) == 1, "Should have placed 1 order to close orphan"
    net = await s.ctx.orders.get_net_qty("orphan_999")
    assert net == 0, "Orphan position was not closed"


@pytest.mark.asyncio
async def test_stop_half_uses_the_close_path():
    """1.10 stop_half partial close on positive net_qty places SELL, holds lock, leaves lots consistent."""
    s = await _build_strategy()
    fake_leg = OpenLeg(security_id="999", segment="NSE_FNO", opt_type="CE", strike=24200.0, lots=2, entry_price=Decimal("100"))
    s._legs[fake_leg.security_id] = fake_leg
    
    # Fake being in a session and reaching stop
    s._last_spot = 24000.0
    s._ltp_cache["999"] = 160.0
    s.ctx.orders.set_net_qty("999", 2 * s._lot_size) # Misclassified long
    s._max_sl_percent = 50.0 # 100 * 1.5 = 150 < 160 -> stop hit
    
    await s.on_tick(_make_tick("999", 160.0))

    placed_orders = [c for c in s.ctx.orders.calls if c["sid"] == "999"]
    assert len(placed_orders) > 0, "No orders placed for stop_half"
    assert placed_orders[-1]["side"] == "SELL", "Misclassified long leg must be closed with SELL"

