"""Unit tests for daily loss calculation and hard-cap trigger in PortfolioService."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from pdp.portfolio.hub import PortfolioHub
from pdp.portfolio.models import PositionState
from pdp.portfolio.service import PortfolioService


def _make_settings(**overrides):
    s = MagicMock()
    s.PORTFOLIO_MTM_INTERVAL_SECONDS = 5
    s.PORTFOLIO_EOD_SNAPSHOT = False
    s.LIVE = False
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _make_service(hub=None) -> PortfolioService:
    if hub is None:
        hub = PortfolioHub()
    svc = PortfolioService(
        redis=MagicMock(),
        engine=MagicMock(),
        hub=hub,
        settings=_make_settings(),
    )
    return svc


def _pos(
    security_id: str = "13",
    net_qty: int = 1,
    avg_price: str = "0",
    realized_pnl: str = "0",
    unrealized_pnl: str = "0",
    strategy_id: str = "test-strategy",
) -> PositionState:
    return PositionState(
        strategy_id=strategy_id,
        security_id=security_id,
        exchange_segment="NSE_FNO",
        product="MIS",
        net_qty=net_qty,
        avg_price=Decimal(avg_price),
        realized_pnl=Decimal(realized_pnl),
        unrealized_pnl=Decimal(unrealized_pnl),
        updated_at=datetime.now(UTC),
    )


# ------------------------------------------------------------------ #
# get_daily_loss                                                       #
# ------------------------------------------------------------------ #


def test_get_daily_loss_zero_when_no_pnl():
    svc = _make_service()
    svc._cache[("13", "NSE_FNO", "MIS")] = _pos()
    assert svc.get_daily_loss() == Decimal("0")


def test_get_daily_loss_reflects_unrealized_loss():
    svc = _make_service()
    svc._day_start_pnl = Decimal("0")
    svc._cache[("13", "NSE_FNO", "MIS")] = _pos(unrealized_pnl="-5000")
    assert svc.get_daily_loss() == Decimal("5000")


def test_get_daily_loss_zero_when_in_profit():
    svc = _make_service()
    svc._day_start_pnl = Decimal("0")
    svc._cache[("13", "NSE_FNO", "MIS")] = _pos(unrealized_pnl="3000")
    assert svc.get_daily_loss() == Decimal("0")


def test_get_daily_loss_accounts_for_day_start_reference():
    svc = _make_service()
    svc._day_start_pnl = Decimal("10000")  # started day with 10k profit
    svc._cache[("13", "NSE_FNO", "MIS")] = _pos(realized_pnl="7000", unrealized_pnl="0")
    # Day started at 10k, now at 7k → loss = 3k
    assert svc.get_daily_loss() == Decimal("3000")


# ------------------------------------------------------------------ #
# Hard cap enforcement                                                 #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_hard_cap_triggers_callback_when_breached():
    svc = _make_service()
    callback = AsyncMock()
    svc.set_hard_cap_callback(callback, daily_loss_cap_inr=1000.0)

    svc._day_start_pnl = Decimal("0")
    svc._cache[("13", "NSE_FNO", "MIS")] = _pos(unrealized_pnl="-1500")

    await svc._check_hard_cap()

    callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_hard_cap_does_not_trigger_below_cap():
    svc = _make_service()
    callback = AsyncMock()
    svc.set_hard_cap_callback(callback, daily_loss_cap_inr=1000.0)

    svc._day_start_pnl = Decimal("0")
    svc._cache[("13", "NSE_FNO", "MIS")] = _pos(unrealized_pnl="-500")

    await svc._check_hard_cap()

    callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_hard_cap_triggers_only_once():
    svc = _make_service()
    callback = AsyncMock()
    svc.set_hard_cap_callback(callback, daily_loss_cap_inr=1000.0)

    svc._day_start_pnl = Decimal("0")
    svc._cache[("13", "NSE_FNO", "MIS")] = _pos(unrealized_pnl="-2000")

    await svc._check_hard_cap()
    await svc._check_hard_cap()  # second call should be a no-op

    callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_hard_cap_no_callback_when_none():
    svc = _make_service()
    svc._day_start_pnl = Decimal("0")
    svc._cache[("13", "NSE_FNO", "MIS")] = _pos(unrealized_pnl="-99999")
    # No callback set — must not raise
    await svc._check_hard_cap()


@pytest.mark.asyncio
async def test_hard_cap_resets_after_day_reset():
    svc = _make_service()
    callback = AsyncMock()
    svc.set_hard_cap_callback(callback, daily_loss_cap_inr=1000.0)

    svc._day_start_pnl = Decimal("0")
    svc._cache[("13", "NSE_FNO", "MIS")] = _pos(unrealized_pnl="-2000")

    await svc._check_hard_cap()
    assert svc._hard_cap_triggered is True

    # Simulate market-open reset: day_start_pnl anchors at current P&L (-2000)
    svc._reset_day_start_pnl()
    assert svc._hard_cap_triggered is False

    callback.reset_mock()
    # Daily loss is now 0 relative to new reference — cap should NOT trigger
    await svc._check_hard_cap()
    callback.assert_not_awaited()

    # Now add new losses on top of the reset reference
    svc._cache[("13", "NSE_FNO", "MIS")] = _pos(unrealized_pnl="-3500")
    await svc._check_hard_cap()
    # loss = 3500 - 2000 = 1500 > 1000 cap → should trigger
    callback.assert_awaited_once()


# ------------------------------------------------------------------ #
# _build_summary                                                       #
# ------------------------------------------------------------------ #


def test_build_summary_includes_realized_loss_today():
    svc = _make_service()
    svc._day_start_pnl = Decimal("0")
    svc._cache[("13", "NSE_FNO", "MIS")] = _pos(realized_pnl="-2000", unrealized_pnl="-500")

    summary = svc._build_summary()
    assert summary["realized_loss_today"] == 2500.0
    assert summary["day_pnl"] == -2500.0
    assert summary["open_positions"] == 1


def test_build_summary_positive_pnl_has_zero_loss():
    svc = _make_service()
    svc._day_start_pnl = Decimal("0")
    svc._cache[("13", "NSE_FNO", "MIS")] = _pos(unrealized_pnl="3000")

    summary = svc._build_summary()
    assert summary["realized_loss_today"] == 0.0
    assert summary["day_pnl"] == 3000.0
