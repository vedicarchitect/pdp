"""Tests for DirectionalStrangle._build_bias_inputs (bias-input-completeness).

Guards the three silently-dead inputs the proposal found: cam_daily read from the
5m pivot tracker instead of 1D, cam_weekly always None (1w never configured), and
PCR always None for underlyings without a chain poller.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from pdp.strategies.directional_strangle import DirectionalStrangle


async def _build_strategy(
    params: dict | None = None,
    ind: MagicMock | None = None,
    chain_hub: MagicMock | None = None,
) -> DirectionalStrangle:
    s = DirectionalStrangle()
    s.strategy_id = "directional_strangle"
    s._mode = "paper"
    s._slog = None

    if ind is None:
        ind = MagicMock()
        ind.ema.return_value = None
        ind.pivots.return_value = None
        ind.period_levels.return_value = None

    market = MagicMock()
    market.subscribe = AsyncMock(return_value=True)
    market.subscribe = AsyncMock(return_value=True)

    class _MockSession:
        async def __aenter__(self):
            m = MagicMock()
            m.commit = AsyncMock()
            m.execute = AsyncMock()
            m.add = MagicMock()
            empty_res = MagicMock()
            empty_res.all.return_value = []
            m.scalars = AsyncMock(return_value=empty_res)
            m.scalar = AsyncMock(return_value=None)
            m.begin = MagicMock()
            m.begin.return_value.__aenter__ = AsyncMock()
            m.begin.return_value.__aexit__ = AsyncMock()
            return m
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    session_maker = MagicMock(return_value=_MockSession())

    ctx = SimpleNamespace(
        params=params or {},
        watchlist=[],
        log=MagicMock(),
        indicators=ind,
        market=market,
        orders=MagicMock(),
        session_maker=session_maker,
        chain_hub=chain_hub,
        _event_service=None,
    )
    ctx.emit_critical = lambda *a, **kw: None

    await s.on_init(ctx)
    return s


@pytest.mark.asyncio
async def test_cam_daily_requests_1d_never_5m():
    """cam_daily must read the 1D pivot tracker; a 5m pivot describes the prior
    5-minute bar, not the prior trading day."""
    ind = MagicMock()
    ind.ema.return_value = None
    ind.pivots.return_value = None
    ind.period_levels.return_value = None
    s = await _build_strategy(ind=ind)

    s._build_bias_inputs(spot=100.0)

    pivot_calls = [c.args for c in ind.pivots.call_args_list]
    assert (s.sid, "1D") in pivot_calls
    assert (s.sid, "5m") not in pivot_calls


@pytest.mark.asyncio
async def test_cam_weekly_resolves_from_1w_pivot_tracker():
    """With a 1w pivot tracker configured (non-None), cam_weekly must be non-null."""
    ind = MagicMock()
    ind.ema.return_value = None
    ind.period_levels.return_value = None
    weekly_state = SimpleNamespace(cam_r3=110.0, cam_r4=115.0, cam_s3=90.0, cam_s4=85.0)

    def _pivots(sid, tf):
        return weekly_state if tf == "1w" else None

    ind.pivots.side_effect = _pivots
    s = await _build_strategy(ind=ind)

    inp = s._build_bias_inputs(spot=100.0)

    assert inp.cam_weekly is not None
    assert inp.cam_weekly.r3 == 110.0
    assert inp.cam_weekly.r4 == 115.0
    assert inp.cam_weekly.s3 == 90.0
    assert inp.cam_weekly.s4 == 85.0


@pytest.mark.asyncio
async def test_pcr_reads_stubbed_chain_hub_value():
    """With chain_hub.get_pcr(underlying) stubbed to a float, BiasInputs.pcr is that float."""
    ind = MagicMock()
    ind.ema.return_value = None
    ind.pivots.return_value = None
    ind.period_levels.return_value = None
    chain_hub = MagicMock()
    chain_hub.get_pcr.return_value = 1.23

    s = await _build_strategy(params={"underlying": "SENSEX"}, ind=ind, chain_hub=chain_hub)

    inp = s._build_bias_inputs(spot=100.0)

    chain_hub.get_pcr.assert_called_once_with("SENSEX")
    assert inp.pcr == 1.23


@pytest.mark.asyncio
async def test_pcr_none_when_no_chain_hub_wired():
    s = await _build_strategy(chain_hub=None)
    inp = s._build_bias_inputs(spot=100.0)
    assert inp.pcr is None
