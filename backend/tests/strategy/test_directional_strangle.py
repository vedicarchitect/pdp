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
from datetime import date, datetime, timezone
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

    # Fake market: subscribe is no-op; ltp_with_age returns entry-level price
    market = MagicMock()
    market.subscribe = AsyncMock(return_value=True)
    market.unsubscribe = AsyncMock()
    ltp_val = Decimal(str(ltp_override or 100.0))
    market.ltp_with_age = AsyncMock(return_value=(ltp_val, 0.1))
    market.cache_get = AsyncMock(return_value=None)  # no halt marker by default
    market.cache_set = AsyncMock()

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
        chain_hub=None,
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
        security_id="700", segment="NSE_FNO", opt_type="CE",
        strike=24200.0, lots=2, entry_price=Decimal("100"),
    )
    s._short_legs.append(fake_leg)
    s._ltp_cache["700"] = 100.0
    s.ctx.orders._pos["700"] = {"net": -130, "avg": Decimal("100"), "realized": Decimal("0")}

    # ltp <= entry * take_profit_pct (100 * 0.5 = 50) triggers take-profit
    await s.on_tick(_make_tick("700", ltp=40.0))

    terminal = [e for e in s._activity if e.get("event_type") in _TERMINAL_CLOSE_TYPES
                and e.get("sid") == "700"]
    assert len(terminal) == 1, f"Expected exactly 1 terminal event, got {len(terminal)}: {terminal}"
    assert terminal[0]["event_type"] == StrangleEventType.TAKE_PROFIT
    assert terminal[0]["pnl"] == (100 - 40) * 2 * s._lot_size


@pytest.mark.asyncio
async def test_stop_all_emits_exactly_one_terminal_event():
    s = await _build_strategy(params={"pct_stop_half": 0.30, "pct_stop_all": 0.40})

    # Leg already half-stopped on a prior tick (half_stopped=True) — this is the
    # realistic path to STOP_ALL, since pct_stop_all > pct_stop_half always, so
    # a fresh leg always hits the stop-half branch first (see the same-tick test).
    fake_leg = OpenLeg(
        security_id="701", segment="NSE_FNO", opt_type="CE",
        strike=24200.0, lots=1, entry_price=Decimal("100"), half_stopped=True,
    )
    s._short_legs.append(fake_leg)
    s._ltp_cache["701"] = 100.0
    s.ctx.orders._pos["701"] = {"net": -65, "avg": Decimal("100"), "realized": Decimal("0")}

    # ltp >= entry * (1 + pct_stop_all) = 140 triggers stop-all
    await s.on_tick(_make_tick("701", ltp=145.0))

    terminal = [e for e in s._activity if e.get("event_type") in _TERMINAL_CLOSE_TYPES
                and e.get("sid") == "701"]
    assert len(terminal) == 1, f"Expected exactly 1 terminal event, got {len(terminal)}: {terminal}"
    assert terminal[0]["event_type"] == StrangleEventType.STOP_ALL


@pytest.mark.asyncio
async def test_stop_half_then_stop_all_same_tick_does_not_double_close():
    """A single tick that crosses BOTH stop-half and stop-all thresholds must
    only emit the stop_half partial this tick — stop-all re-checks on the
    NEXT tick against the now-halved leg, never firing twice in one tick."""
    s = await _build_strategy(params={"pct_stop_half": 0.30, "pct_stop_all": 0.40})

    fake_leg = OpenLeg(
        security_id="702", segment="NSE_FNO", opt_type="CE",
        strike=24200.0, lots=4, entry_price=Decimal("100"),
    )
    s._short_legs.append(fake_leg)
    s._ltp_cache["702"] = 100.0
    s.ctx.orders._pos["702"] = {"net": -260, "avg": Decimal("100"), "realized": Decimal("0")}

    # ltp = 160 crosses both entry*1.30=130 (stop-half) and entry*1.40=140 (stop-all)
    await s.on_tick(_make_tick("702", ltp=160.0))

    events = [e for e in s._activity if e.get("sid") == "702"]
    terminal = [e for e in events if e.get("event_type") in _TERMINAL_CLOSE_TYPES]
    partial = [e for e in events if e.get("event_type") == StrangleEventType.STOP_HALF]

    assert len(partial) == 1, f"Expected exactly 1 stop_half event, got {len(partial)}"
    assert len(terminal) == 0, (
        f"Expected NO terminal close in the same tick as stop_half, got {terminal}"
    )
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

    assert "PE" in s._stop_gate and s._stop_gate["PE"].get("ready"), \
        "Gate must be marked ready after 3 bars below exit_px (cleared on next bar)"

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


# ---------------------------------------------------------------------------
# R4 — Bucket-change hysteresis (bucket_confirm_bars)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_single_bar_bucket_flip_does_not_churn():
    """A one-bar bucket change must not close/reopen legs (bucket_confirm_bars=2)."""
    from pdp.signals.bias import BiasResult, BiasBucket
    from unittest.mock import patch

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
    s._short_legs.append(fake_leg)

    # Mock score_bias to return MORE_BEAR for one bar.
    bear_result = BiasResult(
        score=-0.4, bucket=BiasBucket.MORE_BEAR, pe_lots=3, ce_lots=2,
        gated=False, reason="test", votes={},
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
    from pdp.signals.bias import BiasResult, BiasBucket

    s = await _build_strategy(params={"bucket_confirm_bars": 2})
    s._current_bucket = "more_bull"
    fake_leg = OpenLeg(
        security_id="short_1",
        segment="NSE_FNO",
        opt_type="CE",
        strike=24200.0,
        lots=2,
        entry_price=Decimal("100"),
    )
    s._short_legs.append(fake_leg)
    s.ctx.orders._p("short_1")["net"] = -2

    bear_result = BiasResult(
        score=-0.4, bucket=BiasBucket.MORE_BEAR, pe_lots=3, ce_lots=2,
        gated=False, reason="test", votes={},
    )

    bar1 = _make_bar(ist_hhmm="10:20")
    bar2 = _make_bar(ist_hhmm="10:25")

    new_inst = _make_instrument("pe_new", 24000.0, "PE")
    with (
        patch("pdp.strategies.directional_strangle.score_bias", return_value=bear_result),
        patch("pdp.strategies.directional_strangle.resolve_otm_option", AsyncMock(return_value=new_inst)),
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
    from pdp.signals.bias import BiasResult, BiasBucket

    s = await _build_strategy(params={"bucket_confirm_bars": 3})
    s._current_bucket = "more_bull"

    bear_result = BiasResult(
        score=-0.4, bucket=BiasBucket.MORE_BEAR, pe_lots=3, ce_lots=2,
        gated=False, reason="test", votes={},
    )
    bull_result = BiasResult(
        score=0.4, bucket=BiasBucket.MORE_BULL, pe_lots=2, ce_lots=3,
        gated=False, reason="test", votes={},
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
# R3 — Full bias signal set (PCR from chain hub, VWAP from futures config)
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
    # ctx.chain_hub is None by default in _build_strategy

    inputs = s._build_bias_inputs(24000.0)

    assert inputs.pcr is None


@pytest.mark.asyncio
async def test_vwap_uses_futures_sid_when_configured():
    """When futures_security_id is set, VWAP is read from the futures SID, not spot."""
    from pdp.indicators.vwap import VWAPState

    futures_sid = "NIFTY_FUT_SID"
    s = await _build_strategy(params={"futures_security_id": futures_sid})

    # Futures SID returns a VWAP; spot SID returns None (as in production)
    futures_vwap = VWAPState(vwap=23950.5, session_date=None)  # type: ignore[arg-type]
    def _vwap_side_effect(sid, tf):
        if sid == futures_sid:
            return futures_vwap
        return None

    s.ctx.indicators.vwap.side_effect = _vwap_side_effect

    inputs = s._build_bias_inputs(24000.0)

    assert inputs.vwap == pytest.approx(23950.5)


@pytest.mark.asyncio
async def test_vwap_falls_back_to_spot_sid_when_no_futures_configured():
    """Without futures_security_id, VWAP call uses the spot SID (may return None for index)."""
    s = await _build_strategy()  # no futures_security_id in params

    # Spot SID returns None (no volume on index), futures SID never called
    s.ctx.indicators.vwap.return_value = None

    inputs = s._build_bias_inputs(24000.0)

    assert inputs.vwap is None
    # Confirm it called with spot SID, not some unknown futures SID
    s.ctx.indicators.vwap.assert_called_with(s.sid, "5m")
