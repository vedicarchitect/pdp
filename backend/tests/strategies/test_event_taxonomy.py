"""Invariant: a critical event type names exactly one condition.

`EventType.POSITION_SIZE_CAPPED` is emitted from five sites in `directional_strangle.py`
for two unrelated conditions: a genuine risk-limit (`_reserve_leg_lots` refusing or
clipping a fresh open at the per-sid lot cap) and a data-corruption alarm (a leg's broker
`net_qty` sign contradicts its assumed type on close — evidence the durable state itself
is wrong). A dashboard or alert rule counting `POSITION_SIZE_CAPPED` cannot distinguish
"the cap did its job" from "the position tracking is broken".

See `openspec/changes/strangle-observability-gaps/proposal.md`, which owns the fix (the
close-path sign contradiction becomes `LEG_TYPE_CONTRADICTED`). This test is expected to
start passing only once that change lands.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from pdp.strategies.directional_strangle import DirectionalStrangle, OpenLeg

pytestmark = pytest.mark.xfail(
    strict=True,
    reason="strangle-observability-gaps",
)


class _FakeOrders:
    def __init__(self, net_qty: int) -> None:
        self._net_qty = net_qty

    async def get_net_qty(self, security_id: str) -> int:
        return self._net_qty

    async def cancel_open_entry_orders(self, security_id: str) -> list[int]:
        return []

    async def get_realized_pnl(self, security_id: str) -> Decimal:
        return Decimal("0")

    async def place_order(self, *, security_id, side, qty, **kw):
        return SimpleNamespace(status="OPEN", id=1)


async def _build_strategy(net_qty: int) -> DirectionalStrangle:
    s = DirectionalStrangle()
    s.strategy_id = "directional_strangle"
    s._mode = "paper"
    s._slog = None

    market = MagicMock()
    market.subscribe = AsyncMock(return_value=True)
    market.unsubscribe = AsyncMock()

    ctx = SimpleNamespace(
        params={},
        watchlist=[],
        log=MagicMock(),
        indicators=MagicMock(),
        market=market,
        orders=_FakeOrders(net_qty),
        session_maker=None,
        chain_hub=None,
        _event_service=None,
    )
    ctx.emit_critical = MagicMock()

    await s.on_init(ctx)
    return s


@pytest.mark.asyncio
async def test_cap_refusal_and_close_direction_mismatch_emit_different_event_types() -> None:
    """A risk-limit cap-refusal and a close-path sign contradiction are different
    conditions and must not share one event type."""
    # -- Condition 1: risk-limit cap genuinely refuses a fresh open.
    s_cap = await _build_strategy(net_qty=0)
    s_cap._scale_lots = 1
    s_cap._ratio_table = {}
    # existing_lots (from get_net_qty) already >= max_lots(=1) forces the refusal branch.
    s_cap.ctx.orders = _FakeOrders(net_qty=-75)
    s_cap._lot_size = 75
    await s_cap._reserve_leg_lots("1001", "PE", 1, "short leg")
    assert s_cap.ctx.emit_critical.call_count == 1
    cap_event_type = s_cap.ctx.emit_critical.call_args[0][0]

    # -- Condition 2: a short leg's broker net_qty contradicts its tracked type on close.
    s_close = await _build_strategy(net_qty=75)  # positive net_qty ⇒ not actually short
    s_close._lot_size = 75
    leg = OpenLeg(
        security_id="1002",
        segment="NSE_FNO",
        opt_type="PE",
        strike=24000.0,
        lots=1,
        entry_price=Decimal("100"),
    )
    s_close._ltp_cache["1002"] = Decimal("50")
    await s_close._close_short_leg(leg, "manual_close")
    assert s_close.ctx.emit_critical.call_count == 1
    contradiction_event_type = s_close.ctx.emit_critical.call_args[0][0]

    assert cap_event_type != contradiction_event_type
