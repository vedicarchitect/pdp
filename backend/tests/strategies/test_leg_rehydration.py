"""Invariant: a leg's type (short / hedge / momentum) survives a process restart.

`_rehydrate_legs` (`pdp/strategies/directional_strangle.py`) rebuilds the open-leg book
from PostgreSQL on startup. A broker `net_qty` sign alone cannot distinguish a long hedge
leg from a long momentum leg — both are positive. On 2026-07-09 the old sign-only path
restored a genuinely long SENSEX hedge as a short; the resulting BUY "close" grew the
position 4 -> 8 -> 16 lots across three uncommanded restarts. See
`memory/leg_rehydration_misclassification_bug.md`.

The fix (`strangle-leg-state-durability`) writes a durable `strategy_legs.leg_kind` row on
every open and reads it back on rehydrate instead of inferring from sign. This test proves
the round trip for all three leg kinds, plus the orphan fallback (a broker position with no
durable row is classified by sign and flagged `LEG_TYPE_UNKNOWN`).
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from pdp.instruments.models import Instrument
from pdp.orders.models import Position, StrategyLeg
from pdp.strategies.directional_strangle import DirectionalStrangle


class _FakeOrders:
    async def get_realized_pnl(self, security_id: str) -> Decimal:
        return Decimal("0")


async def _build_strategy() -> DirectionalStrangle:
    """A strategy with an idle (no-op) session_maker — on_init's own rehydrate call
    sees zero open positions and leaves the leg book empty, so tests can drive
    `_rehydrate_legs()` explicitly with their own scripted session."""
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

    empty_result = MagicMock()
    empty_result.all.return_value = []
    mock_session = MagicMock()
    mock_session.scalars = AsyncMock(return_value=empty_result)

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


def _script_rehydrate(s: DirectionalStrangle, *scalars_results: object) -> None:
    session = s.ctx.session_maker.return_value.__aenter__.return_value
    session.scalars = AsyncMock(side_effect=list(scalars_results))


@pytest.mark.asyncio
async def test_leg_survives_restart_with_correct_type() -> None:
    """Open one leg of each type with a durable `strategy_legs` row, simulate a
    restart, assert all three come back classified by the durable row — not
    collapsed by sign inference (hedge and momentum are both long)."""
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

    legs = [
        StrategyLeg(
            strategy_id="directional_strangle", security_id="1001", leg_kind="short",
            opt_type="CE", strike=Decimal("24000"), expiry=None,
        ),
        StrategyLeg(
            strategy_id="directional_strangle", security_id="1002", leg_kind="hedge",
            opt_type="CE", strike=Decimal("24500"), expiry=None,
        ),
        StrategyLeg(
            strategy_id="directional_strangle", security_id="1003", leg_kind="momentum",
            opt_type="PE", strike=Decimal("23800"), expiry=None,
        ),
    ]

    s = await _build_strategy()

    pos_result = SimpleNamespace(all=lambda: [short_pos, hedge_pos, momentum_pos])
    leg_result = SimpleNamespace(all=lambda: legs)
    _script_rehydrate(s, pos_result, leg_result)

    await s._rehydrate_legs()

    short_sids = {leg.security_id for leg in s._short_legs}
    hedge_sids = {leg.security_id for leg in s._hedge_legs}
    momentum_sids = {leg.security_id for leg in s._momentum_legs}

    assert short_sids == {"1001"}
    assert hedge_sids == {"1002"}
    assert momentum_sids == {"1003"}
    assert s.ctx.emit_critical.call_count == 0


@pytest.mark.asyncio
async def test_orphan_position_without_durable_row_falls_back_to_sign_and_flags_unknown() -> None:
    """A broker position with no matching `strategy_legs` row (e.g. pre-migration
    data, or a manual fill) is classified by sign as a best effort and raises
    exactly one `LEG_TYPE_UNKNOWN` so the gap is visible rather than silent."""
    orphan_pos = Position(
        strategy_id="directional_strangle",
        security_id="2001",
        exchange_segment="NSE_FNO",
        product="NRML",
        net_qty=75,
        avg_price=Decimal("3.25"),
    )
    instrument = Instrument(
        security_id="2001", exchange_segment="NSE_FNO", trading_symbol="NIFTY-2001",
        instrument_type="OPTIDX", strike=Decimal("24500"), option_type="CE",
    )

    s = await _build_strategy()

    pos_result = SimpleNamespace(all=lambda: [orphan_pos])
    empty_leg_result = SimpleNamespace(all=lambda: [])
    inst_result = SimpleNamespace(all=lambda: [instrument])
    _script_rehydrate(s, pos_result, empty_leg_result, inst_result)

    await s._rehydrate_legs()

    assert {leg.security_id for leg in s._hedge_legs} == {"2001"}
    assert s.ctx.emit_critical.call_count == 1
    from pdp.events.models import EventType

    assert s.ctx.emit_critical.call_args[0][0] == EventType.LEG_TYPE_UNKNOWN
