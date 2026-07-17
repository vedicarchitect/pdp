"""Tests for strangle-partial-entry-recovery.

A bucket-required side that fails to open (subscribe/tick race, cold LTP after a
feed reconnect, a single rejected order) must self-correct within the same bucket
episode via `_reconcile_bucket_composition`, reusing the normal `_open_short` path
(lock, cap, hedge). A side that was deliberately exited this episode (take-profit,
stop-gate) must never be resurrected, and recovery is bounded per side per episode.
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
from pdp.strategy.log import StrangleEventType

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


def _events(s: DirectionalStrangle, event_type: str) -> list[dict]:
    return [e for e in s._activity if e.get("event_type") == event_type]


class _FakeOrders:
    async def get_net_qty(self, security_id: str) -> int:
        return 0

    async def get_position(self, security_id: str) -> tuple[int, Decimal]:
        return 0, Decimal("0")

    async def get_realized_pnl(self, security_id: str) -> Decimal:
        return Decimal("0")

    async def cancel_open_entry_orders(self, security_id: str) -> list[int]:
        return []

    async def place_order(self, *, security_id, side, qty, **kw):
        return SimpleNamespace(status="OPEN", id=1)


async def _build_strategy(params: dict | None = None) -> DirectionalStrangle:
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
        orders=_FakeOrders(),
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
    "entry_recovery_max_attempts": 2,
}


@pytest.mark.asyncio
async def test_aborted_side_reopens_next_bar():
    """1.1 — CE opens, PE aborts cold; next bar PE resolves and recovers."""
    s = await _build_strategy(params=_DEFAULT_PARAMS)
    s._current_bucket = None
    neutral = _bias(BiasBucket.NEUTRAL)  # strategy default ratio: (3, 3)

    cold = {"PE": True, "CE": False}

    async def _fill(sid):
        return None if cold[sid.split("_")[0]] else Decimal("100")

    with (
        patch("pdp.strategies.directional_strangle.score_bias", return_value=neutral),
        patch("pdp.strategies.directional_strangle.resolve_otm_option", AsyncMock(side_effect=_resolve_side_effect)),
        patch.object(s, "_resolve_fill_price", AsyncMock(side_effect=_fill)),
    ):
        await s.on_bar(_make_bar("10:20"))
        assert s._current_bucket == "neutral", "bucket commits once CE opens"
        assert {leg.opt_type for leg in s._short_legs} == {"CE"}
        assert s._recovery_attempts.get("PE") == 1, "same-bar reconcile already attempted PE"

        cold["PE"] = False
        await s.on_bar(_make_bar("10:25"))
        assert {leg.opt_type for leg in s._short_legs} == {"PE", "CE"}


@pytest.mark.asyncio
async def test_both_sides_aborted_then_recover():
    """1.2 — both sides cold on the open bar; each recovers once its price resolves."""
    s = await _build_strategy(params=_DEFAULT_PARAMS)
    s._current_bucket = None
    neutral = _bias(BiasBucket.NEUTRAL)

    cold = {"PE": True, "CE": True}

    async def _fill(sid):
        return None if cold[sid.split("_")[0]] else Decimal("100")

    with (
        patch("pdp.strategies.directional_strangle.score_bias", return_value=neutral),
        patch("pdp.strategies.directional_strangle.resolve_otm_option", AsyncMock(side_effect=_resolve_side_effect)),
        patch.object(s, "_resolve_fill_price", AsyncMock(side_effect=_fill)),
    ):
        await s.on_bar(_make_bar("10:20"))
        assert len(s._short_legs) == 0
        assert s._current_bucket is None, "nothing opened -- must not latch"

        cold["CE"] = False
        await s.on_bar(_make_bar("10:25"))
        assert s._current_bucket == "neutral"
        assert {leg.opt_type for leg in s._short_legs} == {"CE"}

        cold["PE"] = False
        await s.on_bar(_make_bar("10:30"))
        assert {leg.opt_type for leg in s._short_legs} == {"PE", "CE"}


@pytest.mark.asyncio
async def test_take_profit_side_not_resurrected():
    """1.3 — a side realized then closed (take-profit) this episode is never retried."""
    s = await _build_strategy(params=_DEFAULT_PARAMS)
    s._current_bucket = None
    neutral = _bias(BiasBucket.NEUTRAL)

    with (
        patch("pdp.strategies.directional_strangle.score_bias", return_value=neutral),
        patch("pdp.strategies.directional_strangle.resolve_otm_option", AsyncMock(side_effect=_resolve_side_effect)),
        patch.object(s, "_resolve_fill_price", AsyncMock(return_value=Decimal("100"))),
    ):
        await s.on_bar(_make_bar("10:20"))
        assert {leg.opt_type for leg in s._short_legs} == {"PE", "CE"}
        assert s._bucket_realized == {"PE", "CE"}

        # Take-profit banks the PE side: the leg closes but the realized flag persists.
        pe_leg = next(leg for leg in s._short_legs if leg.opt_type == "PE")
        s._remove_leg(pe_leg.security_id)

        resolved_types: list[str] = []

        async def _resolve_tracked(*a, **k):
            resolved_types.append(k.get("option_type"))
            return _resolve_side_effect(*a, **k)

        with patch(
            "pdp.strategies.directional_strangle.resolve_otm_option",
            AsyncMock(side_effect=_resolve_tracked),
        ):
            await s.on_bar(_make_bar("10:25"))

    assert "PE" not in {leg.opt_type for leg in s._short_legs}
    assert "PE" not in resolved_types, "a realized-then-closed side must not be re-resolved"


@pytest.mark.asyncio
async def test_stop_gated_side_not_recovered():
    """1.4 — a side sitting in the stop-gate cooldown is skipped by recovery."""
    s = await _build_strategy(params=_DEFAULT_PARAMS)
    s._current_bucket = None
    neutral = _bias(BiasBucket.NEUTRAL)

    with (
        patch("pdp.strategies.directional_strangle.score_bias", return_value=neutral),
        patch("pdp.strategies.directional_strangle.resolve_otm_option", AsyncMock(side_effect=_resolve_side_effect)),
        patch.object(s, "_resolve_fill_price", AsyncMock(return_value=Decimal("100"))),
    ):
        await s.on_bar(_make_bar("10:20"))
        assert {leg.opt_type for leg in s._short_legs} == {"PE", "CE"}

        ce_leg = next(leg for leg in s._short_legs if leg.opt_type == "CE")
        s._remove_leg(ce_leg.security_id)
        s._stop_gate["CE"] = {"exit_px": 50.0, "sid": ce_leg.security_id, "n_below": 0}

        resolved_types: list[str] = []

        async def _resolve_tracked(*a, **k):
            resolved_types.append(k.get("option_type"))
            return _resolve_side_effect(*a, **k)

        with patch(
            "pdp.strategies.directional_strangle.resolve_otm_option",
            AsyncMock(side_effect=_resolve_tracked),
        ):
            await s.on_bar(_make_bar("10:25"))

    assert "CE" not in {leg.opt_type for leg in s._short_legs}
    assert "CE" not in resolved_types, "a stop-gated side must not be re-resolved"


@pytest.mark.asyncio
async def test_recovery_is_bounded_and_emits_unfilled():
    """1.5 — exactly `entry_recovery_max_attempts` attempts, then one terminal event."""
    params = {**_DEFAULT_PARAMS, "entry_recovery_max_attempts": 2}
    s = await _build_strategy(params=params)
    s._current_bucket = None
    neutral = _bias(BiasBucket.NEUTRAL)

    cold = {"PE": True, "CE": False}

    async def _fill(sid):
        return None if cold[sid.split("_")[0]] else Decimal("100")

    with (
        patch("pdp.strategies.directional_strangle.score_bias", return_value=neutral),
        patch("pdp.strategies.directional_strangle.resolve_otm_option", AsyncMock(side_effect=_resolve_side_effect)),
        patch.object(s, "_resolve_fill_price", AsyncMock(side_effect=_fill)),
    ):
        await s.on_bar(_make_bar("10:20"))  # commit bucket; same-bar reconcile: PE attempt #1
        await s.on_bar(_make_bar("10:25"))  # unchanged-bucket reconcile: PE attempt #2 (== max)
        await s.on_bar(_make_bar("10:30"))  # bound reached -> terminal ENTRY_SIDE_UNFILLED
        await s.on_bar(_make_bar("10:35"))  # no further attempts or terminal events

    assert len(_events(s, StrangleEventType.ENTRY_RECOVERY_ATTEMPT)) == 2
    assert len(_events(s, StrangleEventType.ENTRY_SIDE_UNFILLED)) == 1
    assert "PE" not in {leg.opt_type for leg in s._short_legs}


@pytest.mark.asyncio
async def test_bucket_change_resets_recovery():
    """1.6 — a confirmed bucket change resets attempt counters and opens the new bucket afresh."""
    params = {**_DEFAULT_PARAMS, "entry_recovery_max_attempts": 1}
    s = await _build_strategy(params=params)
    s._current_bucket = None

    state = {"bias": _bias(BiasBucket.NEUTRAL)}
    cold = {"PE": True, "CE": False}

    async def _fill(sid):
        return None if cold[sid.split("_")[0]] else Decimal("100")

    with (
        patch("pdp.strategies.directional_strangle.score_bias", side_effect=lambda *a, **k: state["bias"]),
        patch("pdp.strategies.directional_strangle.resolve_otm_option", AsyncMock(side_effect=_resolve_side_effect)),
        patch.object(s, "_resolve_fill_price", AsyncMock(side_effect=_fill)),
    ):
        await s.on_bar(_make_bar("10:20"))  # commit neutral; PE attempt #1 (== max)
        await s.on_bar(_make_bar("10:25"))  # bound reached -> terminal, no more attempts
        assert s._recovery_attempts.get("PE", 0) > 0
        assert _events(s, StrangleEventType.ENTRY_SIDE_UNFILLED)

        cold["PE"] = False
        state["bias"] = _bias(BiasBucket.MORE_BEAR)  # strategy default ratio: (2, 3)
        await s.on_bar(_make_bar("10:30"))

    assert s._current_bucket == "more_bear"
    assert s._recovery_attempts == {}, "new episode starts with a clean attempt counter"
    assert {leg.opt_type for leg in s._short_legs} == {"PE", "CE"}


@pytest.mark.asyncio
async def test_recovery_respects_entry_allowed_and_neutral_no_trade():
    """1.7 — no recovery when DTE-gated, when neutral_no_trade skips neutral, or when
    the lot size is degraded (even with a committed bucket and a missing side)."""
    neutral = _bias(BiasBucket.NEUTRAL)

    # (a) DTE gate closed: entry_allowed False -> nothing opens, no episode state.
    s_dte = await _build_strategy(params=_DEFAULT_PARAMS)
    s_dte._current_bucket = None
    s_dte._entry_within_dte = AsyncMock(return_value=False)
    with (
        patch("pdp.strategies.directional_strangle.score_bias", return_value=neutral),
        patch("pdp.strategies.directional_strangle.resolve_otm_option", AsyncMock(side_effect=_resolve_side_effect)),
        patch.object(s_dte, "_resolve_fill_price", AsyncMock(return_value=Decimal("100"))),
    ):
        await s_dte.on_bar(_make_bar("10:20"))
    assert s_dte._current_bucket is None
    assert len(s_dte._short_legs) == 0
    assert s_dte._recovery_attempts == {}

    # (b) neutral_no_trade skips the neutral bucket entirely before recovery ever runs.
    s_ntn = await _build_strategy(params={**_DEFAULT_PARAMS, "neutral_no_trade": True})
    with (
        patch("pdp.strategies.directional_strangle.score_bias", return_value=neutral),
        patch("pdp.strategies.directional_strangle.resolve_otm_option", AsyncMock(side_effect=_resolve_side_effect)),
        patch.object(s_ntn, "_resolve_fill_price", AsyncMock(return_value=Decimal("100"))),
    ):
        await s_ntn.on_bar(_make_bar("10:20"))
    assert s_ntn._current_bucket is None
    assert len(s_ntn._short_legs) == 0

    # (c) lot_size_degraded blocks the reconcile pass even with a genuinely-missing side.
    s_deg = await _build_strategy(params=_DEFAULT_PARAMS)
    s_deg._current_bucket = None
    cold = {"PE": True, "CE": False}

    async def _fill(sid):
        return None if cold[sid.split("_")[0]] else Decimal("100")

    with (
        patch("pdp.strategies.directional_strangle.score_bias", return_value=neutral),
        patch("pdp.strategies.directional_strangle.resolve_otm_option", AsyncMock(side_effect=_resolve_side_effect)),
        patch.object(s_deg, "_resolve_fill_price", AsyncMock(side_effect=_fill)),
    ):
        await s_deg.on_bar(_make_bar("10:20"))
        assert s_deg._recovery_attempts.get("PE") == 1

        s_deg._lot_size_degraded = True
        await s_deg.on_bar(_make_bar("10:25"))

    assert s_deg._recovery_attempts.get("PE") == 1, "no attempt while lot size is degraded"


@pytest.mark.asyncio
async def test_naked_hedge_averted_side_is_recovered():
    """Regression (2026-07-17 review) — a hedge-failure square-off (`naked_hedge_averted`)
    must not mark the side realized. `_bucket_realized` is only set once the short survives
    the hedge step, so a side squared by a failed hedge is retried by reconcile instead of
    being permanently stuck for the rest of the episode. hedge_enabled=True is the production
    default (all 3 canonical configs run hedged), so this path must be covered."""
    params = {**_DEFAULT_PARAMS, "hedge_enabled": True}
    s = await _build_strategy(params=params)
    s._current_bucket = None
    neutral = _bias(BiasBucket.NEUTRAL)

    hedge_fails = {"PE": True}

    async def _fake_open_hedge(opt_type, spot, lots, segment, short_leg=None):
        if hedge_fails.get(opt_type) and short_leg is not None:
            s._ltp_cache[short_leg.security_id] = 100.0
            await s._close_short_leg(
                short_leg, "naked_hedge_averted", event_type=StrangleEventType.LEG_CLOSE
            )

    with (
        patch("pdp.strategies.directional_strangle.score_bias", return_value=neutral),
        patch("pdp.strategies.directional_strangle.resolve_otm_option", AsyncMock(side_effect=_resolve_side_effect)),
        patch.object(s, "_resolve_fill_price", AsyncMock(return_value=Decimal("100"))),
        patch.object(s, "_open_hedge", AsyncMock(side_effect=_fake_open_hedge)),
    ):
        await s.on_bar(_make_bar("10:20"))
        # PE opened then squared by the failed hedge; CE opened and kept its (no-op) hedge.
        assert {leg.opt_type for leg in s._short_legs} == {"CE"}
        assert "PE" not in s._bucket_realized, "a hedge-failure square-off must not mark PE realized"
        assert s._recovery_attempts.get("PE") == 1, "same-bar reconcile already retried PE"

        # Next bar: hedge now succeeds for PE (feed recovered) -- reconcile must reopen it.
        hedge_fails["PE"] = False
        await s.on_bar(_make_bar("10:25"))

    assert {leg.opt_type for leg in s._short_legs} == {"PE", "CE"}


@pytest.mark.asyncio
async def test_recovery_attempts_reset_on_day_rollover():
    """Regression (2026-07-17 review) — an exhausted recovery counter must not stay
    permanently pinned once a new trading day starts, even though `_current_bucket`
    intentionally persists across days. `_bucket_realized` is NOT reset by the day
    rollover (a deliberately-closed side must still never be resurrected), only
    `_recovery_attempts` is."""
    params = {**_DEFAULT_PARAMS, "entry_recovery_max_attempts": 1}
    s = await _build_strategy(params=params)
    s._current_bucket = None
    neutral = _bias(BiasBucket.NEUTRAL)

    cold = {"PE": True, "CE": False}

    async def _fill(sid):
        return None if cold[sid.split("_")[0]] else Decimal("100")

    with (
        patch("pdp.strategies.directional_strangle.score_bias", return_value=neutral),
        patch("pdp.strategies.directional_strangle.resolve_otm_option", AsyncMock(side_effect=_resolve_side_effect)),
        patch.object(s, "_resolve_fill_price", AsyncMock(side_effect=_fill)),
    ):
        await s.on_bar(_make_bar("10:20", day=28))  # commit neutral; PE attempt #1 (== max)
        await s.on_bar(_make_bar("10:25", day=28))  # bound reached -> terminal ENTRY_SIDE_UNFILLED
        assert s._recovery_attempts.get("PE", 0) > params["entry_recovery_max_attempts"] - 1
        assert _events(s, StrangleEventType.ENTRY_SIDE_UNFILLED)

        # Feed recovers overnight; new trading day starts with the same bucket (no bucket
        # change, so the transition-reset path never fires) -- PE must still be retried.
        cold["PE"] = False
        await s.on_bar(_make_bar("10:20", day=29))

    assert s._current_bucket == "neutral", "bucket persists across the day boundary"
    assert {leg.opt_type for leg in s._short_legs} == {"PE", "CE"}
