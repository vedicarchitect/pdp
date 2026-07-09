"""Unit tests for recover_strategy_state() in src/pdp/strategy/recovery.py."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from pdp.instruments.models import Instrument
from pdp.orders.models import Position, Product
from pdp.strategy.recovery import recover_strategy_state

_IST = ZoneInfo("Asia/Kolkata")
_TODAY = date(2026, 6, 12)
_TODAY_DT = datetime(2026, 6, 12, 9, 30, 0, tzinfo=_IST)
_YESTERDAY_DT = datetime(2026, 6, 11, 14, 0, 0, tzinfo=_IST)


def _mock_session_maker(*execute_returns: MagicMock) -> MagicMock:
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=list(execute_returns))
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=None)
    return MagicMock(return_value=cm)


def _short_pos(
    security_id: str = "CE123",
    net_qty: int = -325,
    pos_id: int = 1,
) -> Position:
    return Position(
        id=pos_id,
        security_id=security_id,
        exchange_segment="NSE_FNO",
        product=Product.NRML,
        net_qty=net_qty,
        avg_price=Decimal("86.13"),
        realized_pnl=Decimal("-500"),
        unrealized_pnl=Decimal("0"),
    )


def _instrument(security_id: str = "CE123", option_type: str = "CE") -> Instrument:
    return Instrument(
        id=10,
        security_id=security_id,
        exchange_segment="NSE_FNO",
        trading_symbol="NIFTY24JUN24800CE",
        instrument_type="OPTIDX",
        option_type=option_type,
        strike=Decimal("24800"),
        lot_size=65,
        tick_size=Decimal("0.05"),
    )


def _make_ctx(
    positions: list,
    realized: dict,
    fill_dt: datetime | None = _TODAY_DT,
    inst: Instrument | None = None,
) -> MagicMock:
    ctx = MagicMock()
    ctx.orders.get_positions = AsyncMock(return_value=positions)
    ctx.orders.get_realized_pnl_per_security = AsyncMock(return_value=realized)
    ctx.orders.strategy_id = "st_01"

    if positions and any(p.net_qty < 0 for p in positions):
        cross_day_res = MagicMock()
        cross_day_res.first.return_value = (fill_dt,) if fill_dt is not None else None
        inst_res = MagicMock()
        inst_res.scalar_one_or_none.return_value = inst
        execute_returns: list = [cross_day_res]
        if fill_dt is not None:

            fill_date = fill_dt.astimezone(_IST).date()
            if fill_date == _TODAY:
                execute_returns.append(inst_res)
        ctx.session_maker = _mock_session_maker(*execute_returns)
    else:
        ctx.session_maker = MagicMock()

    return ctx


class TestRecoverStrategyState:
    @pytest.mark.asyncio
    async def test_open_short_ce_recovered(self) -> None:
        """Short CE position from today → _current populated, baseline captured."""
        pos = _short_pos(net_qty=-325)  # 325 // 65 = 5 lots
        inst = _instrument(option_type="CE")
        ctx = _make_ctx(
            positions=[pos],
            realized={"CE123": Decimal("-500")},
            fill_dt=_TODAY_DT,
            inst=inst,
        )

        recovered, baseline = await recover_strategy_state(ctx, "st_01", 65, _TODAY)

        assert recovered == {
            "security_id": "CE123",
            "segment": "NSE_FNO",
            "option_type": "CE",
            "strike": Decimal("24800"),
            "lots": 5,
        }
        assert baseline == {"CE123": Decimal("-500")}

    @pytest.mark.asyncio
    async def test_flat_restart_current_remains_none(self) -> None:
        """No open positions on restart → recovered is None, baseline is empty."""
        ctx = _make_ctx(positions=[], realized={})

        recovered, baseline = await recover_strategy_state(ctx, "st_01", 65, _TODAY)

        assert recovered is None
        assert baseline == {}

    @pytest.mark.asyncio
    async def test_yesterday_position_returns_flat_with_warning(self) -> None:
        """Position with last fill date yesterday → recovered is None, warning emitted."""
        pos = _short_pos(net_qty=-65)
        ctx = _make_ctx(
            positions=[pos],
            realized={"CE123": Decimal("0")},
            fill_dt=_YESTERDAY_DT,
            inst=None,
        )

        recovered, baseline = await recover_strategy_state(ctx, "st_01", 65, _TODAY)

        assert recovered is None

    @pytest.mark.asyncio
    async def test_qty_not_divisible_lots_floored_with_warning(self) -> None:
        """net_qty not divisible by lot_size → lots floored, warning logged, recovery succeeds."""
        pos = _short_pos(net_qty=-330)  # 330 // 65 = 5, remainder 5
        inst = _instrument(option_type="CE")
        ctx = _make_ctx(
            positions=[pos],
            realized={"CE123": Decimal("0")},
            fill_dt=_TODAY_DT,
            inst=inst,
        )

        recovered, _ = await recover_strategy_state(ctx, "st_01", 65, _TODAY)

        assert recovered is not None
        assert recovered["lots"] == 5
