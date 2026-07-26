"""Tests for strangle-orphan-fill-reconciliation.

2026-07-24 live incident: a NIFTY reopen order's fill-price poll timed out (tick
backpressure from a restart), `_open_short` called `cancel_open_entry_orders` and
gave up — but the order filled for real moments later, landing as a broker position
with no matching in-memory leg (one orphaned with `strategy_id: None`, one silently
untracked). `_open_short` must confirm the cancel actually took effect before
discarding a leg, and `_reconcile_divergences` must run on its own schedule so an
orphan is caught even with nobody polling the console.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from pdp.market.bars import BarClosed
from pdp.signals.bias import BiasBucket, BiasResult
from pdp.strategies.directional_strangle import DirectionalStrangle

_IST = ZoneInfo("Asia/Kolkata")


def _make_bar(ist_hhmm: str, day: int = 28) -> BarClosed:
    hh, mm = ist_hhmm.split(":")
    dt_ist = datetime(2026, 7, day, int(hh), int(mm), tzinfo=_IST)
    dt_utc = dt_ist.astimezone(UTC)
    return BarClosed(
        security_id="13",
        timeframe="5m",
        bar_time=dt_utc,
        open=Decimal("24000"),
        high=Decimal("24050"),
        low=Decimal("23950"),
        close=Decimal("24000"),
        volume=1000,
        oi=0,
    )


def _make_instrument(sid: str, strike: float = 24000.0):
    return SimpleNamespace(
        security_id=sid,
        exchange_segment="NSE_FNO",
        strike=Decimal(str(strike)),
        expiry=date(2026, 7, 29),
    )


def _resolve_side_effect(*_a, **k):
    ot = k.get("option_type", "CE")
    return _make_instrument(f"{ot}_opt")


def _bias(bucket: BiasBucket) -> BiasResult:
    return BiasResult(score=0.0, bucket=bucket, pe_lots=0, ce_lots=0, gated=False, reason="test", votes={})


class _FakeOrders:
    """Order client whose `cancel_open_entry_orders` is controllable per test —
    an empty return means "the order was not found OPEN" (already filled)."""

    def __init__(
        self,
        cancelled_ids: list[int] | None = None,
        position: tuple[int, Decimal] = (0, Decimal("0")),
    ) -> None:
        self.cancelled_ids = cancelled_ids if cancelled_ids is not None else []
        self.cancel_calls = 0
        self.position = position

    async def get_net_qty(self, security_id: str) -> int:
        return 0

    async def get_position(self, security_id: str) -> tuple[int, Decimal]:
        return self.position

    async def get_realized_pnl(self, security_id: str) -> Decimal:
        return Decimal("0")

    async def cancel_open_entry_orders(self, security_id: str) -> list[int]:
        self.cancel_calls += 1
        return self.cancelled_ids

    async def place_order(self, *, security_id, side, qty, **kw):
        return SimpleNamespace(status="OPEN", id=999)


async def _build_strategy(params: dict | None = None, orders: _FakeOrders | None = None) -> DirectionalStrangle:
    s = DirectionalStrangle()
    s.strategy_id = "directional_strangle_nifty"
    s._mode = "paper"
    s._slog = None

    ind = MagicMock()
    ind.ema.return_value = None
    ind.pivots.return_value = None
    ind.period_levels.return_value = None
    ind.vwap.return_value = None
    ind.seeding_summary.return_value = {}

    market = MagicMock()
    market.subscribe = AsyncMock(return_value=True)
    market.unsubscribe = AsyncMock()
    market.ltp_with_age = AsyncMock(return_value=(Decimal("100"), 0.1))
    market.cache_get = AsyncMock(return_value=None)
    market.cache_set = AsyncMock()

    fake_session = MagicMock()
    fake_session.add = MagicMock()
    fake_session.commit = AsyncMock()
    _execute_result = MagicMock()
    _execute_result.scalar_one_or_none.return_value = (params or {}).get("lot_size", 65)
    fake_session.execute = AsyncMock(return_value=_execute_result)
    _empty_scalars = MagicMock()
    _empty_scalars.all.return_value = []
    fake_session.scalars = AsyncMock(return_value=_empty_scalars)
    fake_session.scalar = AsyncMock(return_value=None)
    session_maker = MagicMock()
    session_maker.return_value.__aenter__ = AsyncMock(return_value=fake_session)
    session_maker.return_value.__aexit__ = AsyncMock(return_value=False)

    fake_chain_hub = MagicMock()
    fake_chain_hub.get_pcr.return_value = 1.0

    ctx = SimpleNamespace(
        params=params or {},
        watchlist=[],
        log=MagicMock(),
        indicators=ind,
        market=market,
        orders=orders or _FakeOrders(),
        session_maker=session_maker,
        chain_hub=fake_chain_hub,
        _event_service=None,
    )
    ctx.emit_critical = MagicMock()

    await s.on_init(ctx)
    return s


_DEFAULT_PARAMS = {
    "bucket_confirm_bars": 1,
    "hedge_enabled": False,
    "dte_max": None,
    "entry_ltp_wait_s": 0.01,
}


@pytest.mark.asyncio
async def test_leg_registered_when_cancel_races_a_real_fill():
    """The order was NOT among those cancel_open_entry_orders reports cancelled
    (it had already filled) — the strategy must register the leg from the real
    fill instead of discarding it. The recovery check reads the broker's own
    position avg (proof of a real fill), not another LTP-fallback guess."""
    orders = _FakeOrders(cancelled_ids=[], position=(650, Decimal("135.35")))
    s = await _build_strategy(params=_DEFAULT_PARAMS, orders=orders)

    with (
        patch("pdp.strategies.directional_strangle.resolve_otm_option", AsyncMock(side_effect=_resolve_side_effect)),
        patch.object(s, "_resolve_fill_price", AsyncMock(return_value=None)),
    ):
        opened = await s._open_short(spot=24000.0, opt_type="CE", lots=1)

    assert opened is True, "a real fill discovered post-cancel must not be discarded"
    assert len(s._short_legs) == 1
    leg = s._short_legs[0]
    assert leg.entry_price == Decimal("135.35")
    assert orders.cancel_calls == 1


@pytest.mark.asyncio
async def test_leg_not_registered_when_cancel_races_a_rejection_not_a_fill():
    """The order was NOT among those cancel_open_entry_orders reports cancelled, but it
    was REJECTED (not filled) — the broker position stays flat, so the recovery check
    must not fabricate a leg from an LTP estimate. Regression for the gap where trusting
    `_resolve_fill_price`'s LTP fallback layers as proof-of-fill could register a
    phantom leg for an order that never actually filled."""
    orders = _FakeOrders(cancelled_ids=[])  # order not cancelled AND never filled (rejected)
    s = await _build_strategy(params=_DEFAULT_PARAMS, orders=orders)

    with (
        patch("pdp.strategies.directional_strangle.resolve_otm_option", AsyncMock(side_effect=_resolve_side_effect)),
        patch.object(s, "_resolve_fill_price", AsyncMock(return_value=None)),
    ):
        opened = await s._open_short(spot=24000.0, opt_type="CE", lots=1)

    assert opened is False, "no confirmed broker fill must never register a phantom leg"
    assert len(s._short_legs) == 0


@pytest.mark.asyncio
async def test_leg_not_registered_when_cancel_succeeds_cleanly():
    """Sanity check: when the order genuinely was cancelled before filling
    (order.id IS in the cancelled list), behavior is unchanged — no leg, no
    orphan, clean abort."""
    orders = _FakeOrders(cancelled_ids=[999])  # order 999 WAS cancelled
    s = await _build_strategy(params=_DEFAULT_PARAMS, orders=orders)

    with (
        patch("pdp.strategies.directional_strangle.resolve_otm_option", AsyncMock(side_effect=_resolve_side_effect)),
        patch.object(s, "_resolve_fill_price", AsyncMock(return_value=None)),
    ):
        opened = await s._open_short(spot=24000.0, opt_type="CE", lots=1)

    assert opened is False
    assert len(s._short_legs) == 0
    assert orders.cancel_calls == 1


@pytest.mark.asyncio
async def test_reconcile_loop_runs_independent_of_state_calls():
    """The periodic reconciliation task must call _reconcile_divergences on its
    own schedule, without state() ever being invoked."""
    s = await _build_strategy(params={**_DEFAULT_PARAMS, "reconcile_interval_s": 0.01})
    try:
        s._reconcile_divergences = AsyncMock(wraps=s._reconcile_divergences)
        # Give the background task a few intervals to fire.
        import asyncio

        for _ in range(20):
            await asyncio.sleep(0.01)
            if s._reconcile_divergences.await_count >= 1:
                break
        assert s._reconcile_divergences.await_count >= 1, (
            "reconciliation must fire on its own timer, not only via state()"
        )
    finally:
        await s.on_shutdown()


@pytest.mark.asyncio
async def test_reconcile_task_cancelled_cleanly_on_shutdown():
    """on_shutdown must cancel the periodic reconcile task rather than leaking it."""
    s = await _build_strategy(params={**_DEFAULT_PARAMS, "reconcile_interval_s": 5.0})
    task = s._reconcile_task
    assert task is not None
    assert not task.done()

    await s.on_shutdown()

    assert task.cancelled() or task.done()
    assert s._reconcile_task is None
