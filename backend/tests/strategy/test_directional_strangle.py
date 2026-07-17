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

from datetime import UTC, date, datetime, timedelta
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
    dt_utc = dt_ist.astimezone(UTC)
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

    async def get_positions(self) -> list:
        return [
            SimpleNamespace(security_id=sid, net_qty=p["net"], exchange_segment="NSE_FNO")
            for sid, p in self._pos.items()
            if p["net"] != 0
        ]

    @property
    def strategy_id(self) -> str:
        return "directional_strangle"


def _make_instrument(sid: str, strike: float, opt_type: str = "CE"):
    return SimpleNamespace(
        security_id=sid,
        exchange_segment="NSE_FNO",
        strike=Decimal(str(strike)),
        option_type=opt_type,
        expiry=date(2026, 7, 9),
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
    # Add seeding summary mock to always return True for tests
    ind.seeding_summary.return_value = {("ema", "5m"): True, ("pivots", "1w"): True}


    # Fake market: subscribe is no-op; ltp_with_age returns entry-level price
    market = MagicMock()
    market.subscribe = AsyncMock(return_value=True)
    market.unsubscribe = AsyncMock()
    ltp_val = Decimal(str(ltp_override or 100.0))
    market.ltp_with_age = AsyncMock(return_value=(ltp_val, 0.1))
    market.cache_get = AsyncMock(return_value=None)  # no halt marker by default
    market.cache_set = AsyncMock()

    orders = _FakeOrders()

    # Fake session_maker: resolve_otm_option will be patched per test. The
    # session supports the durable strategy_leg writes (add/commit/execute) the
    # open/close paths now make; tests that assert on rehydrate override .scalars.
    fake_session = MagicMock()
    fake_session.add = MagicMock()
    fake_session.commit = AsyncMock()
    # Backs both the durable strategy_leg writes (result unused, fire-and-forget) and
    # `lot_size_for_underlying`'s SELECT — resolve to the same lot_size the strategy was
    # built with so on_bar's session-start resolution is a no-op for tests that don't
    # care about it (see strangle-observability-gaps/lot-size-live-reconciliation).
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
        orders=orders,
        session_maker=session_maker,
        chain_hub=fake_chain_hub,
        _event_service=None,
        _session_maker=session_maker,
        emit_critical=MagicMock(),
    )


    # Mirror StrategyContext.emit_critical: route to _event_service when wired.
    def _emit_critical(event_type, security_id, title, message, payload=None):
        if ctx._event_service is not None:
            ctx._event_service.emit_critical(event_type, security_id, title, message, payload)

    ctx.emit_critical = _emit_critical

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
    # hedge_enabled=False: this test exercises the roll path only. With hedges on, the
    # blanket resolve_otm_option stub would resolve the reopened short and its hedge to
    # the same security_id, which the one-leg-per-security invariant correctly rejects.
    s = await _build_strategy(
        params={"roll_trigger_prem": 20.0, "roll_target_min_prem": 50.0, "hedge_enabled": False}
    )

    # Manually inject an open short leg with high entry price
    fake_leg = OpenLeg(
        security_id="999",
        segment="NSE_FNO",
        opt_type="CE",
        strike=24200.0,
        lots=2,
        entry_price=Decimal("100"),
    )
    s._add_leg(fake_leg)
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
# Regression: exactly ONE terminal close event per physical leg close
# (previously TAKE_PROFIT/STOP_ALL pre-emitted a P&L event, then
# _close_short_leg emitted a second LEG_CLOSE for the same leg — the ledger
# then double-counted realized P&L for every closed leg).
# ---------------------------------------------------------------------------

_TERMINAL_CLOSE_TYPES = {
    StrangleEventType.LEG_CLOSE,
    StrangleEventType.TAKE_PROFIT,
    StrangleEventType.STOP_ALL,
}


@pytest.mark.asyncio
async def test_take_profit_emits_exactly_one_terminal_event():
    s = await _build_strategy(params={"take_profit_pct": 0.5})

    fake_leg = OpenLeg(
        security_id="700",
        segment="NSE_FNO",
        opt_type="CE",
        strike=24200.0,
        lots=2,
        entry_price=Decimal("100"),
    )
    s._add_leg(fake_leg)
    s._ltp_cache["700"] = 100.0
    s.ctx.orders._pos["700"] = {"net": -130, "avg": Decimal("100"), "realized": Decimal("0")}

    # ltp <= entry * take_profit_pct (100 * 0.5 = 50) triggers take-profit
    await s.on_tick(_make_tick("700", ltp=40.0))

    terminal = [
        e for e in s._activity if e.get("event_type") in _TERMINAL_CLOSE_TYPES and e.get("sid") == "700"
    ]
    assert len(terminal) == 1, f"Expected exactly 1 terminal event, got {len(terminal)}: {terminal}"
    assert terminal[0]["event_type"] == StrangleEventType.TAKE_PROFIT
    assert terminal[0]["pnl"] == (100 - 40) * 2 * s._lot_size


def test_leg_pnl_sign_convention_short_vs_hedge():
    """Short legs profit on a price fall; hedge/momentum longs profit on a price rise."""
    from pdp.strategies.directional_strangle import _leg_pnl

    lot_size = 65
    short_leg = OpenLeg(
        security_id="700",
        segment="NSE_FNO",
        opt_type="CE",
        strike=24200.0,
        lots=2,
        entry_price=Decimal("100"),
    )
    assert _leg_pnl(short_leg, 40.0, 2, lot_size) == (100 - 40) * 2 * lot_size

    hedge_leg = OpenLeg(
        security_id="701",
        segment="NSE_FNO",
        opt_type="CE",
        strike=24500.0,
        lots=2,
        entry_price=Decimal("5"),
        is_hedge=True,
    )
    assert _leg_pnl(hedge_leg, 2.0, 2, lot_size) == (2.0 - 5) * 2 * lot_size

    momentum_leg = OpenLeg(
        security_id="702",
        segment="NSE_FNO",
        opt_type="CE",
        strike=23900.0,
        lots=1,
        entry_price=Decimal("150"),
        is_momentum=True,
    )
    assert _leg_pnl(momentum_leg, 180.0, 1, lot_size) == (180.0 - 150) * 1 * lot_size


def test_leg_pnl_zero_entry_returns_zero_not_phantom():
    """A leg with an unresolved entry_price=0 must yield MtM 0, never -ltp*qty.

    Regression for the phantom -2.6L: a freshly-subscribed option with a cold
    ltp cache used to store entry_price=0, making state() MtM compute as
    (0 - ltp) * lots * lot_size = -ltp * qty. The guard in _leg_pnl (entry <= 0
    -> 0.0) plus the never-store-zero abort in _open_short prevent this.
    """
    from pdp.strategies.directional_strangle import _leg_pnl

    lot_size = 20  # SENSEX
    # SENSEX SHORT PE that reproduced -16,324 = -204.05 * (4 * 20)
    zero_entry_short = OpenLeg(
        security_id="800",
        segment="BSE_FNO",
        opt_type="PE",
        strike=80000.0,
        lots=4,
        entry_price=Decimal("0"),
    )
    assert _leg_pnl(zero_entry_short, 204.05, 4, lot_size) == 0.0

    # Same guard for hedge/momentum longs (entry unresolved).
    zero_entry_hedge = OpenLeg(
        security_id="801",
        segment="BSE_FNO",
        opt_type="CE",
        strike=82000.0,
        lots=6,
        entry_price=Decimal("0"),
        is_hedge=True,
    )
    assert _leg_pnl(zero_entry_hedge, 122.55, 6, lot_size) == 0.0


@pytest.mark.asyncio
async def test_stop_all_emits_exactly_one_terminal_event():
    s = await _build_strategy(params={"pct_stop_half": 0.30, "pct_stop_all": 0.40})

    # Leg already half-stopped on a prior tick (half_stopped=True) — this is the
    # realistic path to STOP_ALL, since pct_stop_all > pct_stop_half always, so
    # a fresh leg always hits the stop-half branch first (see the same-tick test).
    fake_leg = OpenLeg(
        security_id="701",
        segment="NSE_FNO",
        opt_type="CE",
        strike=24200.0,
        lots=1,
        entry_price=Decimal("100"),
        half_stopped=True,
    )
    s._add_leg(fake_leg)
    s._ltp_cache["701"] = 100.0
    s.ctx.orders._pos["701"] = {"net": -65, "avg": Decimal("100"), "realized": Decimal("0")}

    # ltp >= entry * (1 + pct_stop_all) = 140 triggers stop-all
    await s.on_tick(_make_tick("701", ltp=145.0))

    terminal = [
        e for e in s._activity if e.get("event_type") in _TERMINAL_CLOSE_TYPES and e.get("sid") == "701"
    ]
    assert len(terminal) == 1, f"Expected exactly 1 terminal event, got {len(terminal)}: {terminal}"
    assert terminal[0]["event_type"] == StrangleEventType.STOP_ALL


@pytest.mark.asyncio
async def test_stop_half_then_stop_all_same_tick_does_not_double_close():
    """A single tick that crosses BOTH stop-half and stop-all thresholds must
    only emit the stop_half partial this tick — stop-all re-checks on the
    NEXT tick against the now-halved leg, never firing twice in one tick."""
    s = await _build_strategy(params={"pct_stop_half": 0.30, "pct_stop_all": 0.40})

    fake_leg = OpenLeg(
        security_id="702",
        segment="NSE_FNO",
        opt_type="CE",
        strike=24200.0,
        lots=4,
        entry_price=Decimal("100"),
    )
    s._add_leg(fake_leg)
    s._ltp_cache["702"] = 100.0
    s.ctx.orders._pos["702"] = {"net": -260, "avg": Decimal("100"), "realized": Decimal("0")}

    # ltp = 160 crosses both entry*1.30=130 (stop-half) and entry*1.40=140 (stop-all)
    await s.on_tick(_make_tick("702", ltp=160.0))

    events = [e for e in s._activity if e.get("sid") == "702"]
    terminal = [e for e in events if e.get("event_type") in _TERMINAL_CLOSE_TYPES]
    partial = [e for e in events if e.get("event_type") == StrangleEventType.STOP_HALF]

    assert len(partial) == 1, f"Expected exactly 1 stop_half event, got {len(partial)}"
    assert len(terminal) == 0, f"Expected NO terminal close in the same tick as stop_half, got {terminal}"
    # The leg must still be open (half-closed), not fully removed
    assert any(l.security_id == "702" for l in s._short_legs)
    assert fake_leg.lots == 2


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

    # Simulate 3 bars with ltp < exit_px → gate becomes "ready" (not yet cleared)
    for i in range(3):
        s._ltp_cache["777"] = 30.0
        s._update_stop_gates()

    assert "PE" in s._stop_gate and s._stop_gate["PE"].get("ready"), (
        "Gate must be marked ready after 3 bars below exit_px (cleared on next bar)"
    )

    # 4th bar start: gate clears; re-entry is permitted from this bar onward
    s._ltp_cache["777"] = 30.0
    s._update_stop_gates()
    assert "PE" not in s._stop_gate, "Gate must be cleared at start of bar 4 (next bar after cooldown)"

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
    assert "/api/v1/strangle/readiness" in paths


# ---------------------------------------------------------------------------
# 9.6 GET /api/v1/strangle/activity — newest-first + n cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activity_newest_first_and_n_cap():
    """Activity endpoint must return events newest-first and respect n cap."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from pdp.strategy.routes import strangle_router

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


@pytest.mark.asyncio
async def test_readiness_route_surfaces_check_readiness():
    """GET /api/v1/strangle/readiness returns the same components check_readiness()
    computes, so a dashboard can show *why* a strategy is blocked, not just that it
    is — the platform-facing deliverable of strangle-observability-gaps."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from pdp.strategy.routes import strangle_router

    app = FastAPI()
    app.include_router(strangle_router)

    s = await _build_strategy()
    s._divergences.add("1001")  # force a "blocked" Reconciliation component

    class _FakeState:
        instance = s

    class _FakeHost:
        _running = {"directional_strangle": _FakeState()}

    app.state.strategy_host = _FakeHost()

    client = TestClient(app)
    resp = client.get("/api/v1/strangle/readiness")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "blocked"
    names = {c["name"] for c in body["components"]}
    assert "Reconciliation" in names
    reconciliation = next(c for c in body["components"] if c["name"] == "Reconciliation")
    assert reconciliation["state"] == "blocked"


# ---------------------------------------------------------------------------
# R4 — Bucket-change hysteresis (bucket_confirm_bars)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_bar_bucket_flip_does_not_churn():
    """A one-bar bucket change must not close/reopen legs (bucket_confirm_bars=2)."""
    from unittest.mock import patch

    from pdp.signals.bias import BiasBucket, BiasResult

    s = await _build_strategy(params={"bucket_confirm_bars": 2})

    # Prime the strategy to think it's in MORE_BULL with open short legs.
    s._current_bucket = "more_bull"
    fake_leg = OpenLeg(
        security_id="short_1",
        segment="NSE_FNO",
        opt_type="CE",
        strike=24200.0,
        lots=2,
        entry_price=Decimal("100"),
    )
    s._add_leg(fake_leg)

    # Mock score_bias to return MORE_BEAR for one bar.
    bear_result = BiasResult(
        score=-0.4,
        bucket=BiasBucket.MORE_BEAR,
        pe_lots=3,
        ce_lots=2,
        gated=False,
        reason="test",
        votes={},
    )

    bar = _make_bar(ist_hhmm="10:20")
    with (
        patch("pdp.strategies.directional_strangle.score_bias", return_value=bear_result),
        patch("pdp.strategies.directional_strangle.resolve_otm_option", AsyncMock(return_value=None)),
    ):
        await s.on_bar(bar)

    # Bucket must NOT have changed — pending_bucket_count == 1, threshold is 2.
    assert s._current_bucket == "more_bull", (
        "Single-bar flip must not churn; current bucket must stay MORE_BULL"
    )
    assert s._pending_bucket == "more_bear"
    assert s._pending_bucket_count == 1
    # Legs must still be open.
    assert len(s._short_legs) == 1, "Legs must not be closed on single-bar flip"


@pytest.mark.asyncio
async def test_sustained_bucket_change_acts_after_n_bars():
    """N-bar sustained bucket change must close/reopen legs after confirmation."""
    from pdp.signals.bias import BiasBucket, BiasResult

    # hedge_enabled=False: this test verifies the N-bar bucket-confirmation transition,
    # not hedging. The bucket commit opens a PE and a CE short; the resolver stub below
    # returns a distinct security_id per option type so the one-leg-per-security
    # invariant is satisfied (a blanket single-instrument stub would collide).
    s = await _build_strategy(params={"bucket_confirm_bars": 2, "hedge_enabled": False})
    s._current_bucket = "more_bull"
    fake_leg = OpenLeg(
        security_id="short_1",
        segment="NSE_FNO",
        opt_type="CE",
        strike=24200.0,
        lots=2,
        entry_price=Decimal("100"),
    )
    s._add_leg(fake_leg)
    s.ctx.orders._p("short_1")["net"] = -2

    bear_result = BiasResult(
        score=-0.4,
        bucket=BiasBucket.MORE_BEAR,
        pe_lots=3,
        ce_lots=2,
        gated=False,
        reason="test",
        votes={},
    )

    bar1 = _make_bar(ist_hhmm="10:20")
    bar2 = _make_bar(ist_hhmm="10:25")

    def _resolve(*_a, **k):
        ot = k.get("option_type", "CE")
        return _make_instrument(f"{ot}_new", 24000.0, ot)

    with (
        patch("pdp.strategies.directional_strangle.score_bias", return_value=bear_result),
        patch("pdp.strategies.directional_strangle.resolve_otm_option", AsyncMock(side_effect=_resolve)),
    ):
        await s.on_bar(bar1)  # bar 1: pending_count = 1, no action
        assert s._current_bucket == "more_bull"

        await s.on_bar(bar2)  # bar 2: pending_count = 2 >= 2, act
        assert s._current_bucket == "more_bear", (
            "After 2 consecutive bars with new bucket, change must be committed"
        )
        assert s._pending_bucket is None, "pending_bucket must be cleared after commitment"


@pytest.mark.asyncio
async def test_bucket_revert_before_confirmation_resets_counter():
    """A bucket that reverts before confirmation must reset the counter."""
    from pdp.signals.bias import BiasBucket, BiasResult

    s = await _build_strategy(params={"bucket_confirm_bars": 3})
    s._current_bucket = "more_bull"

    bear_result = BiasResult(
        score=-0.4,
        bucket=BiasBucket.MORE_BEAR,
        pe_lots=3,
        ce_lots=2,
        gated=False,
        reason="test",
        votes={},
    )
    bull_result = BiasResult(
        score=0.4,
        bucket=BiasBucket.MORE_BULL,
        pe_lots=2,
        ce_lots=3,
        gated=False,
        reason="test",
        votes={},
    )

    bar1 = _make_bar(ist_hhmm="10:20")
    bar2 = _make_bar(ist_hhmm="10:25")

    with patch("pdp.strategies.directional_strangle.resolve_otm_option", AsyncMock(return_value=None)):
        with patch("pdp.strategies.directional_strangle.score_bias", return_value=bear_result):
            await s.on_bar(bar1)  # pending MORE_BEAR, count=1
        assert s._pending_bucket == "more_bear" and s._pending_bucket_count == 1

        with patch("pdp.strategies.directional_strangle.score_bias", return_value=bull_result):
            await s.on_bar(bar2)  # reverts to MORE_BULL; counter must reset
        assert s._pending_bucket is None, "Revert must clear pending_bucket"
        assert s._pending_bucket_count == 0
        assert s._current_bucket == "more_bull"  # unchanged


# ---------------------------------------------------------------------------
# R5 — day_loss_cap halt persists across same-day restart
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_halt_marker_blocks_reentry_on_same_day_restart():
    """After day_loss_cap fires, a simulated restart on the same day must stay halted."""
    s = await _build_strategy(params={"day_loss_limit": 1})  # very low cap
    # Simulate the halt marker already being set for today (simulates post-halt restart).
    s.ctx.market.cache_get = AsyncMock(return_value="1")  # marker exists

    # Force _day_key=None so _maybe_reset_day will trigger on first bar
    s._day_key = None

    # First bar: should restore halt from Redis and remain done_for_day
    bar = _make_bar(ist_hhmm="10:20")
    with patch(
        "pdp.strategies.directional_strangle.resolve_otm_option",
        AsyncMock(return_value=None),
    ):
        await s.on_bar(bar)

    assert s._done_for_day is True, "Halt marker must be restored on first bar of same day"
    # No orders should have been placed
    assert s.ctx.orders.calls == [], "No orders must be placed when halt is active"


@pytest.mark.asyncio
async def test_halt_marker_clears_on_next_day():
    """After a halt on day D, day D+1 must start un-halted (different Redis key, no marker)."""
    from datetime import date

    s = await _build_strategy(params={"day_loss_limit": 1})

    # Simulate day 1 was halted: _day_key = June 28
    s._day_key = date(2026, 6, 28)
    s._done_for_day = True
    s._halt_checked = True

    # Day 2 bar arrives — different date so _maybe_reset_day will reset state.
    s.ctx.market.cache_get = AsyncMock(return_value=None)  # no halt for day 2

    bar_day2 = _make_bar(ist_hhmm="10:20")
    # Reuse same bar but with date June 29
    from datetime import UTC, datetime

    bar_day2 = BarClosed(
        security_id="13",
        timeframe="5m",
        bar_time=datetime(2026, 6, 29, 4, 50, tzinfo=UTC),  # 10:20 IST
        open=Decimal("24000"),
        high=Decimal("24050"),
        low=Decimal("23950"),
        close=Decimal("24000"),
        volume=1000,
        oi=0,
    )

    with patch(
        "pdp.strategies.directional_strangle.resolve_otm_option",
        AsyncMock(return_value=None),
    ):
        await s.on_bar(bar_day2)

    assert s._done_for_day is False, "Next day must start un-halted"
    assert s._day_key == date(2026, 6, 29), "Day key must update to new date"


@pytest.mark.asyncio
async def test_day_loss_cap_writes_halt_marker_to_redis():
    """When day_loss_cap fires, the halt marker must be written to Redis cache."""
    from datetime import date

    # Set day_loss_limit very low so it fires immediately
    s = await _build_strategy(params={"day_loss_limit": 1})

    # Inject a pre-existing realized loss so day_pnl <= -1
    s.ctx.orders._p("13")["realized"] = Decimal("-100")
    # Prime day key and baseline so _day_realized returns -100
    s._day_key = date(2026, 6, 28)
    s._touched_sids.add("13")
    s._day_baseline["13"] = Decimal("0")

    s.ctx.market.cache_set = AsyncMock()

    bar = _make_bar(ist_hhmm="10:20")
    with patch(
        "pdp.strategies.directional_strangle.resolve_otm_option",
        AsyncMock(return_value=None),
    ):
        await s.on_bar(bar)

    expected_key = f"halt:{s.strategy_id}:{date(2026, 6, 28).isoformat()}"
    s.ctx.market.cache_set.assert_called_once_with(expected_key, "1", ex=86400)


# ---------------------------------------------------------------------------
# R3 — Full bias signal set (PCR from chain hub)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pcr_read_from_chain_hub_when_wired():
    """When chain_hub is wired and returns a PCR, BiasInputs.pcr must be non-None."""
    s = await _build_strategy()

    # Wire a fake chain hub that returns a PCR value
    fake_hub = MagicMock()
    fake_hub.get_pcr.return_value = 1.25
    s.ctx.chain_hub = fake_hub

    inputs = s._build_bias_inputs(24000.0)

    assert inputs.pcr == pytest.approx(1.25)
    fake_hub.get_pcr.assert_called_once_with(s.underlying)


@pytest.mark.asyncio
async def test_pcr_is_none_when_chain_hub_not_wired():
    """Without a chain hub, PCR must stay None (vote is skipped by bias engine)."""
    s = await _build_strategy()
    s.ctx.chain_hub = None  # _build_strategy wires a fake hub by default; unwire it here

    inputs = s._build_bias_inputs(24000.0)

    assert inputs.pcr is None


# ---------------------------------------------------------------------------
# Close unpriced guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_unpriced_emits_critical_and_aborts():
    s = await _build_strategy()
    fake_es = MagicMock()
    s.ctx._event_service = fake_es

    leg = OpenLeg(security_id="OPT1", segment="NFO", opt_type="CE", strike=24000.0, lots=1, entry_price=100.0)
    s._add_leg(leg)
    s._ltp_cache["OPT1"] = 0.0  # unpriced

    await s._close_short_leg(leg, "take_profit")

    assert len(s._short_legs) == 1  # not closed
    fake_es.emit_critical.assert_called_once()
    assert fake_es.emit_critical.call_args[0][0].name == "CLOSE_UNPRICED"


@pytest.mark.asyncio
async def test_close_unpriced_allowed_on_expiry():
    s = await _build_strategy()
    fake_es = MagicMock()
    s.ctx._event_service = fake_es

    leg = OpenLeg(security_id="OPT1", segment="NFO", opt_type="CE", strike=24000.0, lots=1, entry_price=100.0)
    s._add_leg(leg)
    s._ltp_cache["OPT1"] = 0.0  # unpriced

    await s._close_short_leg(leg, "expiry")

    assert len(s._short_legs) == 0  # closed successfully
    fake_es.emit_critical.assert_not_called()


@pytest.mark.asyncio
async def test_close_all_does_not_orphan_unpriced_leg():
    """_close_all must not blanket-clear its leg lists: a leg rejected by the
    unpriced guard has to survive so the next bar retries it. Clearing it here
    would forget the leg in-memory while its broker position stays open in
    Postgres — exactly how zombie positions accumulated in production."""
    s = await _build_strategy()

    priced = OpenLeg(security_id="OPT_OK", segment="NFO", opt_type="CE", strike=24000.0, lots=1, entry_price=100.0)
    unpriced = OpenLeg(security_id="OPT_STUCK", segment="NFO", opt_type="PE", strike=23000.0, lots=1, entry_price=50.0)
    s._add_leg(priced)
    s._add_leg(unpriced)

    s.ctx.orders._p("OPT_OK")["net"] = -65
    s.ctx.orders._p("OPT_STUCK")["net"] = -65

    s._ltp_cache["OPT_OK"] = 80.0
    s._ltp_cache["OPT_STUCK"] = 0.0  # unpriced — CLOSE_UNPRICED guard rejects it

    await s._close_all("square_off")

    assert [l.security_id for l in s._short_legs] == ["OPT_STUCK"]


@pytest.mark.asyncio
async def test_close_momentum_leg_self_prunes():
    """_close_momentum_leg must remove itself from _momentum_legs on a
    successful close (it used to rely entirely on the caller's list.clear(),
    which also wiped legs that failed to close)."""
    s = await _build_strategy()

    leg = OpenLeg(
        security_id="OPT_MOM", segment="NFO", opt_type="CE", strike=24000.0,
        lots=1, entry_price=100.0, is_momentum=True,
    )
    s._add_leg(leg)
    s.ctx.orders._p("OPT_MOM")["net"] = 65  # long position (momentum leg)
    s._ltp_cache["OPT_MOM"] = 120.0

    await s._close_momentum_leg(leg, "score_exit")

    assert s._momentum_legs == []


@pytest.mark.asyncio
async def test_rehydrate_sets_day_baseline_to_avoid_phantom_pnl():
    """A rehydrated leg's historical realized_pnl must not be double-counted as
    today's P&L on every restart. _rehydrate_legs must call
    _record_day_baseline() for every sid it restores, exactly like the live
    _open_short/_open_hedge/_open_momentum paths do — otherwise
    _day_realized() has no baseline for that sid and treats the position's
    entire lifetime realized P&L as if it all happened today."""
    s = await _build_strategy()

    # Pre-existing paper position: short, with Rs 50,000 of realized_pnl
    # accrued on earlier partial closes days before this restart.
    s.ctx.orders._pos["OPT_OLD"] = {"net": -65, "avg": Decimal("100"), "realized": Decimal("50000")}

    fake_pos = SimpleNamespace(
        security_id="OPT_OLD",
        strategy_id="directional_strangle",
        net_qty=-65,
        avg_price=Decimal("100"),
        exchange_segment="NSE_FNO",
    )
    pos_result = SimpleNamespace(all=lambda: [fake_pos])
    empty_legs_result = SimpleNamespace(all=lambda: [])
    inst_result = SimpleNamespace(all=lambda: [])

    session = s.ctx.session_maker.return_value.__aenter__.return_value
    session.scalars = AsyncMock(side_effect=[pos_result, empty_legs_result, inst_result])

    await s._rehydrate_legs()

    assert len(s._short_legs) == 1
    assert s._day_baseline.get("OPT_OLD") == Decimal("50000")
    assert await s._day_realized() == Decimal("0")


# ---------------------------------------------------------------------------
# Position-size sanity cap (single sid must never exceed the widest ratio-
# table entry's lots — prevents unbounded growth like the 180/264-lot
# positions found in production, however they get triggered: a stale rollup
# reopen, a duplicated in-memory leg, or repeated same-strike re-entry).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_open_short_refuses_when_already_at_cap():
    s = await _build_strategy()  # default ratio_table max=5, scale_lots=2 -> cap=10 lots
    fake_es = MagicMock()
    s.ctx._event_service = fake_es

    inst = _make_instrument("OPT_CAPPED", 24500.0, "PE")
    # Already sitting at the cap (10 lots * lot_size=65 = 650).
    s.ctx.orders._p("OPT_CAPPED")["net"] = -650

    with patch(
        "pdp.strategies.directional_strangle.resolve_otm_option",
        AsyncMock(return_value=inst),
    ):
        await s._open_short(24000.0, "PE", 5)

    assert s.ctx.orders.calls == []  # no SELL placed — refused outright
    assert s._short_legs == []
    fake_es.emit_critical.assert_called_once()
    call_args = fake_es.emit_critical.call_args[0]
    assert call_args[0].name == "POSITION_SIZE_CAPPED"
    # Assert the condition, not just the label: the cap-refusal payload names the
    # existing/requested/cap lots — a close-path direction-mismatch alarm (the other
    # condition this event name currently covers) would not carry these fields.
    payload = call_args[4]
    assert payload["existing_lots"] == 10
    assert payload["requested_lots"] == 5
    assert payload["cap"] == 10


@pytest.mark.asyncio
async def test_open_short_clips_lots_to_stay_within_cap():
    # hedge_enabled=False: the fake resolve_otm_option always returns the same
    # instrument regardless of otm_steps, so a hedge scan would otherwise also
    # open a BUY on the same sid and pollute the assertion below.
    s = await _build_strategy(params={"hedge_enabled": False})  # cap=10 lots
    fake_es = MagicMock()
    s.ctx._event_service = fake_es

    inst = _make_instrument("OPT_CLIP", 24500.0, "PE")
    # Already at 8 lots (520 qty); requesting 5 more would breach the 10-lot cap.
    s.ctx.orders._p("OPT_CLIP")["net"] = -520

    with patch(
        "pdp.strategies.directional_strangle.resolve_otm_option",
        AsyncMock(return_value=inst),
    ):
        await s._open_short(24000.0, "PE", 5)

    assert s.ctx.orders.calls == [{"sid": "OPT_CLIP", "side": "SELL", "qty": 2 * s._lot_size}]
    assert len(s._short_legs) == 1
    assert s._short_legs[0].lots == 2
    fake_es.emit_critical.assert_called_once()
    call_args = fake_es.emit_critical.call_args[0]
    assert call_args[0].name == "POSITION_SIZE_CAPPED"
    payload = call_args[4]
    assert payload["existing_lots"] == 8
    assert payload["requested_lots"] == 5
    assert payload["cap"] == 10


@pytest.mark.asyncio
async def test_open_hedge_refuses_when_already_at_cap():
    """The same cap guard added to _open_short must also cover _open_hedge —
    the two runaway sids found in production (~900k and ~500k qty) were both
    far-OTM hedge legs, not shorts, so this path needs its own coverage."""
    s = await _build_strategy(params={"hedge_scan_start": 1, "hedge_scan_end": 1})
    fake_es = MagicMock()
    s.ctx._event_service = fake_es

    inst = _make_instrument("OPT_HEDGE_CAPPED", 25000.0, "PE")
    s.ctx.orders._p("OPT_HEDGE_CAPPED")["net"] = 650  # already at the 10-lot cap

    with patch(
        "pdp.strategies.directional_strangle.resolve_otm_option",
        AsyncMock(return_value=inst),
    ):
        await s._open_hedge("PE", 24000.0, 5, "NSE_FNO")

    assert s.ctx.orders.calls == []  # no BUY placed — refused outright
    assert s._hedge_legs == []
    fake_es.emit_critical.assert_called_once()
    call_args = fake_es.emit_critical.call_args[0]
    assert call_args[0].name == "POSITION_SIZE_CAPPED"
    payload = call_args[4]
    assert payload["existing_lots"] == 10
    assert payload["requested_lots"] == 5
    assert payload["cap"] == 10


@pytest.mark.asyncio
async def test_open_hedge_clips_lots_to_stay_within_cap():
    s = await _build_strategy(params={"hedge_scan_start": 1, "hedge_scan_end": 1})
    fake_es = MagicMock()
    s.ctx._event_service = fake_es

    inst = _make_instrument("OPT_HEDGE_CLIP", 25000.0, "PE")
    s.ctx.orders._p("OPT_HEDGE_CLIP")["net"] = 520  # 8 lots; +5 more would breach cap=10

    with patch(
        "pdp.strategies.directional_strangle.resolve_otm_option",
        AsyncMock(return_value=inst),
    ):
        await s._open_hedge("PE", 24000.0, 5, "NSE_FNO")

    assert s.ctx.orders.calls == [{"sid": "OPT_HEDGE_CLIP", "side": "BUY", "qty": 2 * s._lot_size}]
    assert len(s._hedge_legs) == 1
    assert s._hedge_legs[0].lots == 2
    fake_es.emit_critical.assert_called_once()
    call_args = fake_es.emit_critical.call_args[0]
    assert call_args[0].name == "POSITION_SIZE_CAPPED"
    payload = call_args[4]
    assert payload["existing_lots"] == 8
    assert payload["requested_lots"] == 5
    assert payload["cap"] == 10


# ---------------------------------------------------------------------------
# check_readiness() — strangle-observability-gaps tasks 1.3-1.9, 6.5
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_readiness_blocked_when_indicator_unseeded():
    """An unseeded indicator on any watched timeframe blocks the Indicators
    component, naming the family/period/timeframe in the reason (task 1.3)."""
    s = await _build_strategy()
    s._last_spot = 24000.0  # keep Bias component ok so only Indicators trips

    def _seeding_summary(underlying, tf):
        if tf == "1H":
            return {("ema", "200"): False}
        return {}

    s.ctx.indicators.seeding_summary.side_effect = _seeding_summary

    readiness = await s.check_readiness()

    ind = next(c for c in readiness.components if c.name == "Indicators")
    assert ind.state == "blocked"
    assert "EMA(200)" in ind.reason
    assert "1H" in ind.reason
    assert readiness.state == "blocked"


@pytest.mark.asyncio
async def test_check_readiness_keys_seeding_by_security_id_not_name():
    """Regression: the Indicators component must query `seeding_summary` by the
    security_id (`self.sid`), not the underlying *name* — the engine keys suites by
    security_id, so passing "NIFTY" returned an empty summary and the gate silently
    always reported ok. See strangle-readiness-indicators-truthful."""
    s = await _build_strategy()
    s._last_spot = 24000.0
    assert s.sid != s.underlying, "test is only meaningful when sid and name differ"

    seen_first_args: list[str] = []

    def _seeding(first, tf):
        seen_first_args.append(first)
        return {("ema", "200"): False} if tf == "1H" else {}

    s.ctx.indicators.seeding_summary.side_effect = _seeding

    readiness = await s.check_readiness()

    assert seen_first_args, "seeding_summary must be consulted"
    assert all(a == s.sid for a in seen_first_args), "must key by security_id, not underlying name"
    ind = next(c for c in readiness.components if c.name == "Indicators")
    assert ind.state == "blocked", "an unseeded indicator (keyed by sid) must now block"


@pytest.mark.asyncio
async def test_check_readiness_all_ok_composite():
    """Every component satisfied (paper mode bypasses broker sync, spot present,
    indicators seeded, PCR not required) composes to an overall `ok` (task 1.5)."""
    s = await _build_strategy()
    s._last_spot = 24000.0

    readiness = await s.check_readiness()

    assert readiness.state == "ok"
    assert all(c.state == "ok" for c in readiness.components)


@pytest.mark.asyncio
async def test_check_readiness_degraded_on_stale_broker_sync():
    """A `BrokerFund.synced_at` older than 60s degrades the Broker Sync component
    in live mode (paper mode always bypasses this check) (task 1.4)."""
    s = await _build_strategy()
    s._last_spot = 24000.0
    s._mode = "live"

    stale_row = SimpleNamespace(synced_at=datetime.now(UTC) - timedelta(seconds=120))
    session = s.ctx.session_maker.return_value.__aenter__.return_value
    session.scalar = AsyncMock(return_value=stale_row)

    readiness = await s.check_readiness()

    broker = next(c for c in readiness.components if c.name == "Broker Sync")
    assert broker.state == "degraded"
    assert readiness.state == "degraded"


def _block_indicators(s: DirectionalStrangle) -> None:
    """Force the Indicators readiness component to `blocked` regardless of spot
    (on_bar sets `_last_spot` from the bar's own close before the readiness
    check runs, so Bias can't be used to gate on_bar in a test)."""
    s.ctx.indicators.seeding_summary.side_effect = lambda underlying, tf: (
        {("ema", "200"): False} if tf == "1H" else {}
    )


@pytest.mark.asyncio
async def test_on_bar_refuses_entry_and_emits_once_while_blocked():
    """`on_bar` refuses new entries while any readiness component is blocked and
    emits `strategy_not_ready` exactly once on the ok->blocked transition, not
    once per bar (tasks 1.6, 1.9, 6.2, 6.5)."""
    s = await _build_strategy()
    _block_indicators(s)

    bar = _make_bar(security_id=s.sid)

    await s.on_bar(bar)
    await s.on_bar(bar)
    await s.on_bar(bar)

    not_ready_events = [
        e for e in s._activity if e.get("event_type") == StrangleEventType.STRATEGY_NOT_READY
    ]
    assert len(not_ready_events) == 1, "must emit once on the transition, not once per bar"
    # No bias evaluation ran (blocked before scoring) -> no bias_evaluated event.
    assert not any(e.get("event_type") == StrangleEventType.BIAS_EVALUATED for e in s._activity)


@pytest.mark.asyncio
async def test_on_bar_resumes_entries_once_readiness_recovers():
    """Once the blocking condition clears, the next bar resumes normal bias
    evaluation (readiness recovers -> entries resume) (task 1.8)."""
    s = await _build_strategy()
    _block_indicators(s)

    bar = _make_bar(security_id=s.sid)
    await s.on_bar(bar)
    assert not any(e.get("event_type") == StrangleEventType.BIAS_EVALUATED for e in s._activity)

    s.ctx.indicators.seeding_summary.side_effect = None
    s.ctx.indicators.seeding_summary.return_value = {("ema", "5m"): True, ("pivots", "1w"): True}
    await s.on_bar(bar)

    assert any(e.get("event_type") == StrangleEventType.BIAS_EVALUATED for e in s._activity)


# ---------------------------------------------------------------------------
# strangle-entry-fill-race-and-latch — no-latch-on-failed-open + retry + wait
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_open_does_not_latch_bucket_and_retries_next_bar():
    """A confirmed bucket whose open cannot resolve a fill price must NOT latch
    `_current_bucket`; it must emit `entry_aborted` and retry on the next bar, then
    open once the fill price resolves. Regression for the 2026-07-17 full-day outage
    where a cold first-open latched the bucket with zero legs."""
    from pdp.signals.bias import BiasBucket, BiasResult

    s = await _build_strategy(
        params={
            "bucket_confirm_bars": 1,
            "hedge_enabled": False,
            "dte_max": None,  # disable DTE gate so entry is always allowed in-test
            "entry_ltp_wait_s": 0.01,
        }
    )
    s._current_bucket = None

    bull = BiasResult(
        score=0.4, bucket=BiasBucket.MORE_BULL, pe_lots=3, ce_lots=2,
        gated=False, reason="test", votes={},
    )

    def _resolve(*_a, **k):
        ot = k.get("option_type", "CE")
        return _make_instrument(f"{ot}_opt", 24000.0, ot)

    cold = {"v": True}

    async def _fill(_sid):
        return None if cold["v"] else Decimal("100")

    bar1 = _make_bar(ist_hhmm="10:20")
    bar2 = _make_bar(ist_hhmm="10:25")

    with (
        patch("pdp.strategies.directional_strangle.score_bias", return_value=bull),
        patch("pdp.strategies.directional_strangle.resolve_otm_option", AsyncMock(side_effect=_resolve)),
        patch.object(s, "_resolve_fill_price", AsyncMock(side_effect=_fill)),
    ):
        await s.on_bar(bar1)  # cold: open aborts
        assert len(s._short_legs) == 0, "no legs must open while the fill price is cold"
        assert s._current_bucket is None, "bucket must NOT latch on a failed open"
        assert s._pending_bucket == "more_bull", "pending bucket retained so next bar retries"
        aborted = [e for e in s._activity if e.get("event_type") == StrangleEventType.ENTRY_ABORTED]
        assert aborted, "a failed open must emit entry_aborted"
        assert aborted[0]["reason"] == "fill_unresolved"

        cold["v"] = False
        await s.on_bar(bar2)  # warm: retry opens
        assert s._current_bucket == "more_bull", "bucket advances once a leg actually opens"
        assert len(s._short_legs) == 2, "PE + CE shorts open on the retry bar"


@pytest.mark.asyncio
async def test_await_option_ltp_true_when_tick_arrives_within_wait():
    """`_await_option_ltp` returns True as soon as a positive LTP is visible, so a
    freshly-subscribed option that ticks within the wait window is priced, not aborted."""
    s = await _build_strategy(params={"entry_ltp_wait_s": 1.0})
    calls = {"n": 0}

    async def _ltp(_sid):
        calls["n"] += 1
        return (Decimal("50"), 0.1) if calls["n"] >= 2 else (None, None)

    s.ctx.market.ltp_with_age = AsyncMock(side_effect=_ltp)
    s._ltp_cache.clear()

    assert await s._await_option_ltp("opt_1") is True
    assert calls["n"] >= 2, "must poll until a tick appears"


@pytest.mark.asyncio
async def test_await_option_ltp_false_when_no_tick_within_wait():
    """`_await_option_ltp` returns False (cold) when no LTP appears within the budget."""
    s = await _build_strategy(params={"entry_ltp_wait_s": 0.05})
    s.ctx.market.ltp_with_age = AsyncMock(return_value=(None, None))
    s._ltp_cache.clear()

    assert await s._await_option_ltp("opt_1") is False
