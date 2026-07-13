"""Behavioural tests for session-start lot-size resolution (lot-size-live-reconciliation).

`self._lot_size` is seeded from YAML for the very first bar, then `_maybe_resolve_lot_size`
(called from `on_bar`) makes the instruments table authoritative — YAML becomes advisory-only,
compared just for a mismatch warning. An empty instruments table degrades new-entry trading
(never falls back to a guessed/hardcoded lot size) while existing legs keep pricing off the
last-known-good value.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from pdp.strategies.directional_strangle import DirectionalStrangle

_IST = ZoneInfo("Asia/Kolkata")


class _FakeOrders:
    async def get_realized_pnl(self, security_id: str) -> Decimal:
        return Decimal("0")

    async def get_net_qty(self, security_id: str) -> int:
        return 0


async def _build_strategy(lot_size_param: int | None = 65) -> DirectionalStrangle:
    s = DirectionalStrangle()
    s.strategy_id = "directional_strangle"
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
    _empty_scalars = MagicMock()
    _empty_scalars.all.return_value = []
    fake_session.scalars = AsyncMock(return_value=_empty_scalars)
    fake_session.scalar = AsyncMock(return_value=None)
    fake_session.execute = AsyncMock()
    fake_session.commit = AsyncMock()
    session_maker = MagicMock()
    session_maker.return_value.__aenter__ = AsyncMock(return_value=fake_session)
    session_maker.return_value.__aexit__ = AsyncMock(return_value=False)

    params: dict = {}
    if lot_size_param is not None:
        params["lot_size"] = lot_size_param

    ctx = SimpleNamespace(
        params=params,
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


def _bar_day(day: int = 28):
    return datetime(2026, 7, day, 10, 20, tzinfo=_IST).astimezone(UTC).date()


@pytest.mark.asyncio
async def test_session_start_resolution_overrides_yaml_value():
    """task 1.2: resolves from the instruments table at session start, not YAML."""
    s = await _build_strategy(lot_size_param=65)
    assert s._lot_size == 65  # YAML seed, before any bar

    with patch(
        "pdp.strategy.strikes.lot_size_for_underlying", AsyncMock(return_value=75)
    ):
        await s._maybe_resolve_lot_size(_bar_day())

    assert s._lot_size == 75
    assert s._lot_size_degraded is False


@pytest.mark.asyncio
async def test_yaml_mismatch_logs_warning_and_uses_resolved_value():
    """task 1.3: YAML present + mismatched vs resolved -> warning, resolved value wins."""
    s = await _build_strategy(lot_size_param=65)

    with patch(
        "pdp.strategy.strikes.lot_size_for_underlying", AsyncMock(return_value=75)
    ):
        await s._maybe_resolve_lot_size(_bar_day())

    assert s._lot_size == 75
    warning_names = [c.args[0] for c in s.ctx.log.warning.call_args_list]
    assert warning_names.count("lot_size_yaml_mismatch") == 1


@pytest.mark.asyncio
async def test_no_yaml_value_resolves_silently():
    """task 1.4: YAML lot_size absent -> resolves and uses scrip-master value, no warning."""
    s = await _build_strategy(lot_size_param=None)
    assert s._lot_size == 65  # class default, no YAML override

    with patch(
        "pdp.strategy.strikes.lot_size_for_underlying", AsyncMock(return_value=30)
    ):
        await s._maybe_resolve_lot_size(_bar_day())

    assert s._lot_size == 30
    warning_names = [c.args[0] for c in s.ctx.log.warning.call_args_list]
    assert "lot_size_yaml_mismatch" not in warning_names


@pytest.mark.asyncio
async def test_empty_instruments_table_degrades_without_hardcoded_fallback():
    """task 1.5: no matching rows -> new entries blocked, degraded surfaced, no fallback guess."""
    s = await _build_strategy(lot_size_param=65)

    with patch(
        "pdp.strategy.strikes.lot_size_for_underlying", AsyncMock(return_value=None)
    ):
        await s._maybe_resolve_lot_size(_bar_day())

    assert s._lot_size_degraded is True
    assert s._lot_size == 65  # unchanged -- last-known-good, not a guessed fallback
    s.ctx.emit_critical.assert_called_once()

    # New-entry paths refuse outright while degraded.
    with patch(
        "pdp.strategies.directional_strangle.resolve_otm_option", AsyncMock()
    ) as resolve_mock:
        await s._open_short(24000.0, "PE", 2)
    resolve_mock.assert_not_called()


@pytest.mark.asyncio
async def test_existing_legs_still_price_with_last_known_good_lot_size_while_degraded():
    """task 1.6: existing open legs still price/close correctly on the last-known-good
    lot size while new-entry trading is degraded."""
    from pdp.strategies.directional_strangle import OpenLeg, _leg_pnl

    s = await _build_strategy(lot_size_param=65)
    leg = OpenLeg(
        security_id="OPT1", segment="NSE_FNO", opt_type="PE", strike=24000.0,
        lots=2, entry_price=Decimal("100"),
    )
    s._add_leg(leg)

    with patch(
        "pdp.strategy.strikes.lot_size_for_underlying", AsyncMock(return_value=None)
    ):
        await s._maybe_resolve_lot_size(_bar_day())
    assert s._lot_size_degraded is True

    # MTM math still uses the pre-degradation lot size (65), not 0 or a guess.
    mtm = _leg_pnl(leg, 80.0, leg.lots, s._lot_size)
    assert mtm == (100.0 - 80.0) * 2 * 65


@pytest.mark.asyncio
async def test_resolved_once_per_day_no_repeated_query_within_same_day():
    """task 1.7: no repeated DB query across bars within the same trading day."""
    s = await _build_strategy(lot_size_param=65)

    with patch(
        "pdp.strategy.strikes.lot_size_for_underlying", AsyncMock(return_value=75)
    ) as lookup:
        await s._maybe_resolve_lot_size(_bar_day())
        await s._maybe_resolve_lot_size(_bar_day())
        await s._maybe_resolve_lot_size(_bar_day())

    assert lookup.call_count == 1


@pytest.mark.asyncio
async def test_lot_size_change_picked_up_on_the_next_trading_day():
    """task 1.8: a lot size revision between two simulated trading days (same process,
    no restart) is picked up on the second day."""
    s = await _build_strategy(lot_size_param=65)

    with patch(
        "pdp.strategy.strikes.lot_size_for_underlying", AsyncMock(return_value=65)
    ):
        await s._maybe_resolve_lot_size(_bar_day(28))
    assert s._lot_size == 65

    with patch(
        "pdp.strategy.strikes.lot_size_for_underlying", AsyncMock(return_value=70)
    ):
        await s._maybe_resolve_lot_size(_bar_day(29))
    assert s._lot_size == 70
