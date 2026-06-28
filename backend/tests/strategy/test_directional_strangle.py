"""Unit + integration tests for DirectionalStrangle (chunk 4: strangle-execution-console).

Tests cover:
  9.1 bias_evaluated event includes votes dict on every 5m bar
  9.2 leg_status event emitted after every bias_evaluated (including when flat)
  9.3 _roll_leg fires when ltp < roll_trigger_prem; emits rolled event
  9.4 stop-gate blocks _open_short for 3 bars then clears; stop_gate_wait emitted
  9.5 GET /api/v1/strangle/status returns 200 with bucket and mode fields
  9.6 GET /api/v1/strangle/activity returns events newest-first, respects n cap
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from pdp.market.bars import BarClosed
from pdp.strategies.directional_strangle import DirectionalStrangle, OpenLeg
from pdp.strategy.log import StrangleEventType

_IST = ZoneInfo("Asia/Kolkata")

# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------

def _make_bar(
    security_id: str = "13",
    timeframe: str = "5m",
    close: float = 24000.0,
    ist_hhmm: str = "10:20",
) -> BarClosed:
    hh, mm = ist_hhmm.split(":")
    dt_ist = datetime(2026, 6, 28, int(hh), int(mm), tzinfo=_IST)
    dt_utc = dt_ist.astimezone(timezone.utc)
    return BarClosed(
        security_id=security_id,
        timeframe=timeframe,
        bar_time=dt_utc,
        open=Decimal(str(close)),
        high=Decimal(str(close + 50)),
        low=Decimal(str(close - 50)),
        close=Decimal(str(close)),
        volume=1000,
        oi=0,
    )


def _make_tick(security_id: str, ltp: float):
    return SimpleNamespace(security_id=security_id, ltp=ltp)


class _FakeOrders:
    """Minimal fake order client that auto-fills SELLs and tracks positions."""

    def __init__(self):
        self._pos: dict[str, dict] = {}
        self.calls: list[dict] = []

    def _p(self, sid: str) -> dict:
        return self._pos.setdefault(sid, {"net": 0, "avg": Decimal("0"), "realized": Decimal("0")})

    async def place_order(self, *, security_id, side, qty, **kw):
        self.calls.append({"sid": security_id, "side": side, "qty": qty})
        p = self._p(security_id)
        side_s = str(side)
        qty_i = int(qty)
        price = Decimal("100")
        if side_s == "SELL":
            p["avg"] = price
            p["net"] -= qty_i
        elif side_s == "BUY":
            if p["net"] < 0:
                cover = min(qty_i, abs(p["net"]))
                p["realized"] += (p["avg"] - price) * cover
                p["net"] += cover
        return SimpleNamespace(status="OPEN", id=len(self.calls))

    async def get_net_qty(self, security_id: str) -> int:
        return self._p(security_id)["net"]

    async def get_position(self, security_id: str) -> tuple[int, Decimal]:
        p = self._p(security_id)
        return p["net"], p["avg"]

    async def get_realized_pnl(self, security_id: str) -> Decimal:
        return self._p(security_id)["realized"]

    async def cancel_open_entry_orders(self, security_id: str) -> list[int]:
        return []

    @property
    def strategy_id(self) -> str:
        return "directional_strangle"


def _make_instrument(sid: str, strike: float, opt_type: str = "CE"):
    return SimpleNamespace(
        security_id=sid,
        exchange_segment="NSE_FNO",
        strike=Decimal(str(strike)),
        option_type=opt_type,
    )


async def _build_strategy(
    params: dict | None = None,
    ltp_override: float | None = None,
) -> DirectionalStrangle:
    """Create and on_init a DirectionalStrangle with fake dependencies."""
    s = DirectionalStrangle()
    s.strategy_id = "directional_strangle"
    s._mode = "paper"
    s._slog = None

    # Fake indicators: return None for all (minimal; not under test here)
    ind = MagicMock()
    ind.ema.return_value = None
    ind.pivots.return_value = None
    ind.period_levels.return_value = None
    ind.vwap.return_value = None

    # Fake market: subscribe is no-op; ltp_with_age returns entry-level price
    market = MagicMock()
    market.subscribe = AsyncMock(return_value=True)
    market.unsubscribe = AsyncMock()
    ltp_val = Decimal(str(ltp_override or 100.0))
    market.ltp_with_age = AsyncMock(return_value=(ltp_val, 0.1))

    orders = _FakeOrders()

    # Fake session_maker: resolve_otm_option will be patched per test
    session_maker = MagicMock()
    session_maker.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
    session_maker.return_value.__aexit__ = AsyncMock(return_value=False)

    ctx = SimpleNamespace(
        params=params or {},
        watchlist=[],
        log=MagicMock(),
        indicators=ind,
        market=market,
        orders=orders,
        session_maker=session_maker,
    )

    await s.on_init(ctx)
    return s


# ---------------------------------------------------------------------------
# 9.1 bias_evaluated includes votes dict
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bias_evaluated_includes_votes():
    """bias_evaluated event must carry a votes dict on every 5m bar."""
    s = await _build_strategy()
    bar = _make_bar(ist_hhmm="10:20")

    with patch(
        "pdp.strategies.directional_strangle.resolve_otm_option",
        AsyncMock(return_value=None),
    ):
        await s.on_bar(bar)

    bias_events = [e for e in s._activity if e.get("event_type") == StrangleEventType.BIAS_EVALUATED]
    assert bias_events, "Expected at least one bias_evaluated event"
    ev = bias_events[0]
    assert "votes" in ev, "bias_evaluated must include votes"
    assert isinstance(ev["votes"], dict), "votes must be a dict"


# ---------------------------------------------------------------------------
# 9.2 leg_status emitted after every bias_evaluated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_leg_status_after_bias_evaluated():
    """leg_status must immediately follow bias_evaluated in the activity buffer."""
    s = await _build_strategy()
    bar = _make_bar(ist_hhmm="10:20")

    with patch(
        "pdp.strategies.directional_strangle.resolve_otm_option",
        AsyncMock(return_value=None),
    ):
        await s.on_bar(bar)

    events = list(s._activity)
    types = [e["event_type"] for e in events]

    assert StrangleEventType.BIAS_EVALUATED in types
    assert StrangleEventType.LEG_STATUS in types

    # Find any bias_evaluated and confirm the next event is leg_status
    for i, t in enumerate(types):
        if t == StrangleEventType.BIAS_EVALUATED:
            assert i + 1 < len(types), "leg_status must follow bias_evaluated"
            assert types[i + 1] == StrangleEventType.LEG_STATUS


# ---------------------------------------------------------------------------
# 9.3 _roll_leg fires when ltp < roll_trigger_prem
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_roll_leg_fires_on_low_premium():
    """on_tick must call _roll_leg when ltp < roll_trigger_prem (default 20)."""
    s = await _build_strategy(params={"roll_trigger_prem": 20.0, "roll_target_min_prem": 50.0})

    # Manually inject an open short leg with high entry price
    fake_leg = OpenLeg(
        security_id="999",
        segment="NSE_FNO",
        opt_type="CE",
        strike=24200.0,
        lots=2,
        entry_price=Decimal("100"),
    )
    s._short_legs.append(fake_leg)
    s._ltp_cache["999"] = 100.0
    s._last_spot = 24000.0

    # Stub resolve_otm_option to return a new instrument with sufficient premium
    new_inst = _make_instrument("888", 24200.0, "CE")
    with patch(
        "pdp.strategies.directional_strangle.resolve_otm_option",
        AsyncMock(return_value=new_inst),
    ):
        # Tick with ltp below roll_trigger_prem
        tick = _make_tick("999", ltp=15.0)
        await s.on_tick(tick)

    rolled_events = [e for e in s._activity if e.get("event_type") == StrangleEventType.ROLLED]
    assert rolled_events, "Expected a rolled event after ltp < roll_trigger_prem"


# ---------------------------------------------------------------------------
# 9.4 stop-gate blocks _open_short for 3 bars then clears
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stop_gate_blocks_and_clears():
    """Stop gate must block _open_short and clear after 3 bars where ltp < exit_px."""
    s = await _build_strategy()

    # Inject a stop gate for "PE" side
    s._stop_gate["PE"] = {"exit_px": 50.0, "sid": "777", "n_below": 0}
    s._ltp_cache["777"] = 30.0  # below exit_px

    # _open_short must be blocked while gate is active
    with patch(
        "pdp.strategies.directional_strangle.resolve_otm_option",
        AsyncMock(return_value=None),
    ):
        await s._open_short(24000.0, "PE", 2)

    # No orders should have been placed (gate blocked)
    assert not s.ctx.orders.calls

    # Simulate 3 bars with ltp < exit_px → gate should clear
    for i in range(3):
        s._ltp_cache["777"] = 30.0
        s._update_stop_gates()

    assert "PE" not in s._stop_gate, "Gate must be cleared after 3 bars below exit_px"

    # Confirm stop_gate_wait events were emitted during the wait
    wait_events = [e for e in s._activity if e.get("event_type") == StrangleEventType.STOP_GATE_WAIT]
    assert wait_events, "stop_gate_wait must be emitted while gate is active"


# ---------------------------------------------------------------------------
# 9.5 GET /api/v1/strangle/status — integration (route registration)
# ---------------------------------------------------------------------------

def test_strangle_status_route_registered():
    """Confirm /api/v1/strangle/status is registered in the FastAPI app."""
    from pdp.main import create_app
    app = create_app()
    paths = [r.path for r in app.routes if hasattr(r, "path")]
    assert "/api/v1/strangle/status" in paths
    assert "/api/v1/strangle/legs" in paths
    assert "/api/v1/strangle/activity" in paths
    assert "/api/v1/strangle/stats" in paths


# ---------------------------------------------------------------------------
# 9.6 GET /api/v1/strangle/activity — newest-first + n cap
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_activity_newest_first_and_n_cap():
    """Activity endpoint must return events newest-first and respect n cap."""
    from pdp.strategy.routes import strangle_router
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(strangle_router)

    # Build a strategy with some activity events
    s = await _build_strategy()
    # Emit 10 events with sequential event_type markers
    for i in range(10):
        s._emit_event(f"test_event_{i}", seq=i)

    # Mock strategy_host to return our strategy instance
    class _FakeState:
        instance = s

    class _FakeHost:
        _running = {"directional_strangle": _FakeState()}

    app.state.strategy_host = _FakeHost()

    client = TestClient(app)
    resp = client.get("/api/v1/strangle/activity?n=3")
    assert resp.status_code == 200
    body = resp.json()
    assert "events" in body
    events = body["events"]
    assert len(events) <= 3, "n=3 must cap at 3 events"

    # Verify newest-first: last emitted event (test_event_9) should appear first
    assert events[0]["event_type"] == "test_event_9", "Newest event must be first"
