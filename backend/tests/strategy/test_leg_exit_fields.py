"""Unit tests for DirectionalStrangle._leg_exit_fields / _leg_pnl P&L sign convention.

Verifies that:
- Short legs produce positive P&L when price falls (entry > exit)
- Hedge/momentum (long) legs produce positive P&L when price rises (exit > entry)
- Partial close (stop_half) uses close_lots, not leg.lots

Exercises the real `_leg_pnl`/_leg_exit_fields` production code (not a reimplementation)
so a regression in the shared sign-convention helper fails this suite directly.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from pdp.strategies.directional_strangle import DirectionalStrangle, OpenLeg

from .test_directional_strangle import _build_strategy

_LOT_SIZE = 75


def _make_leg(**kw) -> OpenLeg:
    defaults = dict(
        security_id="12345", segment="NSE_FNO", opt_type="PE",
        strike=24300.0, lots=2, entry_price=Decimal("100"),
    )
    defaults.update(kw)
    return OpenLeg(**defaults)


@pytest.mark.asyncio
async def _strategy() -> DirectionalStrangle:
    return await _build_strategy()


class TestLegExitFieldsPnl:
    """P&L sign convention matches _compute_unrealized (same shared _leg_pnl helper)."""

    @pytest.mark.asyncio
    async def test_short_profitable_when_price_falls(self):
        s = await _strategy()
        s._lot_size = _LOT_SIZE
        leg = _make_leg(entry_price=Decimal("100"), lots=2, is_hedge=False)
        fields = s._leg_exit_fields(leg, exit_px=40.0, reason="take_profit")
        expected = round((100 - 40) * 2 * _LOT_SIZE, 2)
        assert fields["pnl"] == expected
        assert fields["pnl"] > 0, "Short leg should profit when exit < entry"

    @pytest.mark.asyncio
    async def test_short_loss_when_price_rises(self):
        s = await _strategy()
        s._lot_size = _LOT_SIZE
        leg = _make_leg(entry_price=Decimal("50"), lots=1, is_hedge=False)
        fields = s._leg_exit_fields(leg, exit_px=90.0, reason="stop_all")
        expected = round((50 - 90) * 1 * _LOT_SIZE, 2)
        assert fields["pnl"] == expected
        assert fields["pnl"] < 0, "Short leg should lose when exit > entry"

    @pytest.mark.asyncio
    async def test_hedge_profitable_when_price_rises(self):
        s = await _strategy()
        s._lot_size = _LOT_SIZE
        leg = _make_leg(entry_price=Decimal("5"), lots=2, is_hedge=True)
        fields = s._leg_exit_fields(leg, exit_px=25.0, reason="leg_close")
        expected = round((25 - 5) * 2 * _LOT_SIZE, 2)
        assert fields["pnl"] == expected
        assert fields["pnl"] > 0, "Hedge (long) leg should profit when exit > entry"

    @pytest.mark.asyncio
    async def test_momentum_long_profitable_when_price_rises(self):
        s = await _strategy()
        s._lot_size = _LOT_SIZE
        leg = _make_leg(entry_price=Decimal("200"), lots=1, is_momentum=True, is_hedge=False)
        fields = s._leg_exit_fields(leg, exit_px=300.0, reason="leg_close")
        expected = round((300 - 200) * 1 * _LOT_SIZE, 2)
        assert fields["pnl"] == expected
        assert fields["pnl"] > 0

    @pytest.mark.asyncio
    async def test_partial_close_uses_close_lots(self):
        """stop_half closes half the lots; pnl should use close_lots, not leg.lots."""
        s = await _strategy()
        s._lot_size = _LOT_SIZE
        leg = _make_leg(entry_price=Decimal("100"), lots=4, is_hedge=False)
        close_lots = leg.lots // 2  # 2
        fields = s._leg_exit_fields(leg, exit_px=130.0, reason="stop_half", close_lots=close_lots)
        expected = round((100 - 130) * close_lots * _LOT_SIZE, 2)
        assert fields["pnl"] == expected
        # Full lots would give a larger-magnitude loss; partial must be less in absolute terms
        full_fields = s._leg_exit_fields(leg, exit_px=130.0, reason="stop_half")
        assert abs(fields["pnl"]) < abs(full_fields["pnl"])

    @pytest.mark.asyncio
    async def test_zero_pnl_when_flat(self):
        s = await _strategy()
        s._lot_size = _LOT_SIZE
        leg = _make_leg(entry_price=Decimal("100"), lots=1, is_hedge=False)
        fields = s._leg_exit_fields(leg, exit_px=100.0, reason="leg_close")
        assert fields["pnl"] == 0.0
