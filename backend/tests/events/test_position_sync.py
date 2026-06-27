"""PositionSync tests: Dhan mapping, diff → POSITION_CHANGE, graceful behaviour."""
from __future__ import annotations

import pytest

from pdp.events.models import EventType
from pdp.events.positions import PositionSync, _map_dhan_position, _resolve_underlying


def test_map_dhan_short_ce():
    mp = _map_dhan_position({
        "netQty": -75, "tradingSymbol": "NIFTY 26 JUN 24000 CALL",
        "exchangeSegment": "NSE_FNO", "sellAvg": 120.5, "drvOptionType": "CE",
        "drvStrikePrice": 24000, "securityId": "45678", "drvExpiryDate": "2026-06-26",
        "delta": 0.42,
    })
    assert mp is not None
    assert mp.underlying == "NIFTY" and mp.option_type == "CE"
    assert mp.strike == 24000.0 and mp.side == "SHORT" and mp.is_option

def test_map_zero_qty_skipped():
    assert _map_dhan_position({"netQty": 0}) is None

def test_resolve_underlying():
    assert _resolve_underlying("BANKNIFTY24500CE") == "BANKNIFTY"
    assert _resolve_underlying("UNKNOWNSYM") == "NIFTY"


@pytest.mark.asyncio
async def test_apply_emits_open_and_close():
    events = []
    sync = PositionSync(settings=None, session_maker=None, adapter=None,
                        emit=events.append, interval_seconds=30)
    p = _map_dhan_position({
        "netQty": -75, "tradingSymbol": "NIFTY24000CE", "exchangeSegment": "NSE_FNO",
        "sellAvg": 120, "drvOptionType": "CE", "drvStrikePrice": 24000, "securityId": "45678",
    })
    await sync._apply([p])
    assert any(e.event_type == EventType.POSITION_CHANGE and "opened" in e.title for e in events)
    events.clear()
    await sync._apply([])  # leg closed
    assert any(e.event_type == EventType.POSITION_CHANGE and "closed" in e.title for e in events)


@pytest.mark.asyncio
async def test_apply_carries_mtm_peak():
    sync = PositionSync(settings=None, session_maker=None, adapter=None,
                        emit=lambda e: None, interval_seconds=30)
    p1 = _map_dhan_position({"netQty": -75, "tradingSymbol": "X", "exchangeSegment": "NSE_FNO",
                             "sellAvg": 120, "securityId": "1"})
    await sync._apply([p1])
    sync.get_positions()[0].mtm_peak = 8000.0
    p2 = _map_dhan_position({"netQty": -75, "tradingSymbol": "X", "exchangeSegment": "NSE_FNO",
                             "sellAvg": 120, "securityId": "1"})
    await sync._apply([p2])
    assert sync.get_positions()[0].mtm_peak == 8000.0
