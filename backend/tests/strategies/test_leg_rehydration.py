"""Invariant: a leg's type (short / hedge / momentum) survives a process restart.

`_rehydrate_legs` (`pdp/strategies/directional_strangle.py:1772`) is supposed to rebuild
the open-leg lists from PostgreSQL `Position` rows on startup, classifying each restored
leg via a Mongo `leg_open` event lookup. But nothing in this codebase ever *writes* a
`leg_open` event to Mongo — `get_events_collection` has exactly two callers and both are
reads. So the lookup always comes back empty and every rehydrated leg is silently
classified as a short, regardless of its real type.

On 2026-07-09 this restored a genuinely long SENSEX hedge as a short; the resulting BUY
"close" grew the position 4 -> 8 -> 16 lots across three uncommanded restarts. See
`memory/leg_rehydration_misclassification_bug.md` and
`openspec/changes/strangle-leg-state-durability/proposal.md`, which owns the real fix
(a durable `leg_kind` column). This test proves the round trip and is expected to start
passing only once that change lands.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from pdp.instruments.models import Instrument
from pdp.orders.models import Position
from pdp.strategies.directional_strangle import DirectionalStrangle

pytestmark = pytest.mark.xfail(
    strict=True,
    reason="strangle-leg-state-durability",
)


class _FakeOrders:
    async def get_realized_pnl(self, security_id: str) -> Decimal:
        return Decimal("0")


async def _build_strategy_with_open_positions(positions: list, instruments: list) -> DirectionalStrangle:
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
    market.ltp_with_age = AsyncMock(return_value=(Decimal("100"), 0.1))
    market.cache_get = AsyncMock(return_value=None)
    market.cache_set = AsyncMock()

    positions_result = MagicMock()
    positions_result.all.return_value = positions
    instruments_result = MagicMock()
    instruments_result.all.return_value = instruments

    mock_session = MagicMock()
    mock_session.scalars = AsyncMock(side_effect=[positions_result, instruments_result])

    session_maker = MagicMock()
    session_maker.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    session_maker.return_value.__aexit__ = AsyncMock(return_value=False)

    ctx = SimpleNamespace(
        params={},
        watchlist=[],
        log=MagicMock(),
        indicators=ind,
        market=market,
        orders=_FakeOrders(),
        session_maker=session_maker,
        chain_hub=None,
        _event_service=None,
    )
    ctx.emit_critical = MagicMock()

    await s.on_init(ctx)
    return s


@pytest.mark.asyncio
async def test_leg_survives_restart_with_correct_type() -> None:
    """Open one leg of each type, simulate a restart, assert all three come back
    classified correctly (not silently collapsed into `_short_legs`)."""
    short_pos = Position(
        strategy_id="directional_strangle",
        security_id="1001",
        exchange_segment="NSE_FNO",
        product="NRML",
        net_qty=-75,
        avg_price=Decimal("120.50"),
    )
    hedge_pos = Position(
        strategy_id="directional_strangle",
        security_id="1002",
        exchange_segment="NSE_FNO",
        product="NRML",
        net_qty=75,
        avg_price=Decimal("3.25"),
    )
    momentum_pos = Position(
        strategy_id="directional_strangle",
        security_id="1003",
        exchange_segment="NSE_FNO",
        product="NRML",
        net_qty=75,
        avg_price=Decimal("45.00"),
    )

    instruments = [
        Instrument(
            security_id="1001", exchange_segment="NSE_FNO", trading_symbol="NIFTY-1001",
            instrument_type="OPTIDX", strike=Decimal("24000"), option_type="CE",
        ),
        Instrument(
            security_id="1002", exchange_segment="NSE_FNO", trading_symbol="NIFTY-1002",
            instrument_type="OPTIDX", strike=Decimal("24500"), option_type="CE",
        ),
        Instrument(
            security_id="1003", exchange_segment="NSE_FNO", trading_symbol="NIFTY-1003",
            instrument_type="OPTIDX", strike=Decimal("23800"), option_type="PE",
        ),
    ]

    s = await _build_strategy_with_open_positions(
        [short_pos, hedge_pos, momentum_pos], instruments
    )

    await s._rehydrate_legs()

    short_sids = {leg.security_id for leg in s._short_legs}
    hedge_sids = {leg.security_id for leg in s._hedge_legs}
    momentum_sids = {leg.security_id for leg in s._momentum_legs}

    assert short_sids == {"1001"}
    assert hedge_sids == {"1002"}
    assert momentum_sids == {"1003"}
