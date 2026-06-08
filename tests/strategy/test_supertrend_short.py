"""Behavioural tests for the SuperTrend short strategy.

The strategy is driven with a stubbed indicator, order client, market control, and a
monkeypatched strike resolver, plus a controllable IST clock.
"""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

import pdp.strategies.supertrend_short as mod
from pdp.indicators.supertrend import DOWN, UP, SuperTrendState
from pdp.market.bars import BarClosed
from pdp.strategies.supertrend_short import SuperTrendShort


class _Orders:
    def __init__(self):
        self.calls: list[dict] = []

    async def place_order(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(id=len(self.calls), status="OPEN")


class _Indicators:
    def __init__(self):
        self.state: SuperTrendState | None = None

    def supertrend(self, security_id, timeframe):
        return self.state


class _Market:
    def __init__(self):
        self.subs: list[tuple[str, str]] = []
        self.unsubs: list[tuple[str, str]] = []

    async def subscribe(self, security_id, segment):
        self.subs.append((security_id, segment))
        return True

    async def unsubscribe(self, security_id, segment):
        self.unsubs.append((security_id, segment))


class _SessionMaker:
    def __call__(self):
        return self

    async def __aenter__(self):
        return SimpleNamespace()

    async def __aexit__(self, *exc):
        return False


def _ctx(orders, indicators, market):
    import structlog

    return SimpleNamespace(
        orders=orders,
        indicators=indicators,
        market=market,
        session_maker=_SessionMaker(),
        log=structlog.get_logger(),
        params={
            "underlying": "NIFTY",
            "underlying_security_id": "13",
            "timeframe": "5m",
            "lot_size": 65,
            "start_lots": 2,
            "add_lots": 1,
            "max_lots": 5,
            "start_ist": "09:30",
            "square_off_ist": "15:10",
        },
    )


def _bar(i: int, close: float = 22500.0) -> BarClosed:
    base = datetime(2026, 6, 8, 4, 0, tzinfo=UTC)
    return BarClosed(
        security_id="13",
        timeframe="5m",
        bar_time=base + timedelta(minutes=5 * i),
        open=Decimal(str(close)),
        high=Decimal(str(close + 5)),
        low=Decimal(str(close - 5)),
        close=Decimal(str(close)),
        volume=0,
        oi=0,
    )


@pytest.fixture
def patched_resolver(monkeypatch):
    async def fake_resolve(session, *, underlying, spot, option_type, otm_steps=1, strike_step=None, expiry=None):
        strike = 22450 if option_type == "PE" else 22550
        return SimpleNamespace(
            security_id=f"OPT_{option_type}",
            exchange_segment="NSE_FNO",
            strike=Decimal(str(strike)),
        )

    monkeypatch.setattr(mod, "resolve_otm_option", fake_resolve)


def _set_clock(monkeypatch, hh, mm):
    monkeypatch.setattr(mod, "_now_ist", lambda: time(hh, mm))


@pytest.mark.asyncio
async def test_no_entry_before_start(patched_resolver, monkeypatch):
    orders, ind, market = _Orders(), _Indicators(), _Market()
    ind.state = SuperTrendState(direction=UP, value=Decimal("0"), flipped=False)
    strat = SuperTrendShort()
    await strat.on_init(_ctx(orders, ind, market))

    _set_clock(monkeypatch, 9, 0)  # before 09:30
    await strat.on_bar(_bar(1))

    assert orders.calls == []  # no trades before the window


@pytest.mark.asyncio
async def test_opens_short_pe_on_uptrend(patched_resolver, monkeypatch):
    orders, ind, market = _Orders(), _Indicators(), _Market()
    ind.state = SuperTrendState(direction=UP, value=Decimal("0"), flipped=False)
    strat = SuperTrendShort()
    await strat.on_init(_ctx(orders, ind, market))

    _set_clock(monkeypatch, 9, 35)
    await strat.on_bar(_bar(1))

    assert len(orders.calls) == 1
    call = orders.calls[0]
    assert call["side"] == "SELL"
    assert call["security_id"] == "OPT_PE"
    assert call["qty"] == 2 * 65  # start_lots * lot_size
    assert ("OPT_PE", "NSE_FNO") in market.subs


@pytest.mark.asyncio
async def test_scale_in_up_to_cap(patched_resolver, monkeypatch):
    orders, ind, market = _Orders(), _Indicators(), _Market()
    ind.state = SuperTrendState(direction=UP, value=Decimal("0"), flipped=False)
    strat = SuperTrendShort()
    await strat.on_init(_ctx(orders, ind, market))
    _set_clock(monkeypatch, 9, 35)

    for i in range(1, 8):  # 1 open (2 lots) + adds; cap at 5 lots
        await strat.on_bar(_bar(i))

    sells = [c for c in orders.calls if c["side"] == "SELL"]
    # 2 lots open, then +1 each bar to reach 5 -> 1 open + 3 adds = 4 SELL orders.
    assert len(sells) == 4
    assert strat._current["lots"] == 5


@pytest.mark.asyncio
async def test_flip_closes_and_reverses(patched_resolver, monkeypatch):
    orders, ind, market = _Orders(), _Indicators(), _Market()
    ind.state = SuperTrendState(direction=UP, value=Decimal("0"), flipped=False)
    strat = SuperTrendShort()
    await strat.on_init(_ctx(orders, ind, market))
    _set_clock(monkeypatch, 9, 35)

    await strat.on_bar(_bar(1))  # open PE
    ind.state = SuperTrendState(direction=DOWN, value=Decimal("0"), flipped=True)
    await strat.on_bar(_bar(2))  # flip -> close PE, open CE

    buys = [c for c in orders.calls if c["side"] == "BUY"]
    assert len(buys) == 1
    assert buys[0]["security_id"] == "OPT_PE"  # bought back the PE
    assert strat._current["option_type"] == "CE"
    assert any(c["security_id"] == "OPT_CE" and c["side"] == "SELL" for c in orders.calls)


@pytest.mark.asyncio
async def test_square_off_flattens_and_stops(patched_resolver, monkeypatch):
    orders, ind, market = _Orders(), _Indicators(), _Market()
    ind.state = SuperTrendState(direction=UP, value=Decimal("0"), flipped=False)
    strat = SuperTrendShort()
    await strat.on_init(_ctx(orders, ind, market))

    _set_clock(monkeypatch, 9, 35)
    await strat.on_bar(_bar(1))  # open PE
    assert strat._current is not None

    _set_clock(monkeypatch, 15, 12)  # past square-off
    await strat.on_bar(_bar(2))  # close all, done for day
    assert strat._current is None
    assert strat._done_for_day is True

    n_before = len(orders.calls)
    await strat.on_bar(_bar(3))  # no more trading
    assert len(orders.calls) == n_before
