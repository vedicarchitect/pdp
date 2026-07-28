"""Leg-lifecycle invariants for the intraday directional option seller.

`IntradayDirectional` is a second strategy handling real broker positions, so it must
carry the same eight invariants `DirectionalStrangle` earned through live incidents (see
`pdp/strategies/CLAUDE.md` and `memory/leg_rehydration_misclassification_bug.md`). These
are proved here against the new class directly — a strategy that merely *looks* like it
copied the rules is exactly how `_open_hedge`/`_open_momentum` ended up missing the
cancel-confirmation fix that `_open_short` had (2026-07-25 review).

Decision logic itself lives in `tests/signals/test_intraday_directional.py`; this file
only covers I/O and leg bookkeeping.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, time
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from pdp.events.models import EventType
from pdp.signals.intraday_directional import ExitReason, Side
from pdp.strategies.intraday_directional import (
    IntradayDirectional,
    LiveLeg,
    params_from_config,
)
from pdp.strategy.context import MarketControl

_ENTRY_DAY = date(2026, 7, 1)


class _FakeOrders:
    """Minimal broker double: scripted net_qty/avg, records every place_order call."""

    def __init__(self, net_qty: int = 0, avg: Decimal = Decimal("100")) -> None:
        self.net_qty = net_qty
        self.avg = avg
        self.placed: list[dict] = []
        self.cancelled: list[str] = []

    async def place_order(self, **kw):
        self.placed.append(kw)
        return SimpleNamespace(order_id=len(self.placed), status="FILLED")

    async def get_net_qty(self, sid: str) -> int:
        return self.net_qty

    async def get_position(self, sid: str):
        return self.net_qty, self.avg

    async def get_realized_pnl(self, sid: str) -> Decimal:
        return Decimal("0")

    async def cancel_open_entry_orders(self, sid: str) -> None:
        self.cancelled.append(sid)


def _instrument(sid: str, strike: float) -> SimpleNamespace:
    return SimpleNamespace(
        security_id=sid, exchange_segment="NSE_FNO",
        strike=Decimal(str(strike)), expiry=_ENTRY_DAY,
    )


async def _build(params: dict | None = None, orders: _FakeOrders | None = None):
    """A strategy wired to mocks, with the reconcile timer left un-started.

    `on_init` is deliberately bypassed for the DB/timer parts — every field it sets is
    assigned here — so a test can drive one method without a live event loop task or a
    session_maker leaking into it. `params_from_config` is still the real one, so the
    decision knobs under test are the ones the YAML would produce.
    """
    s = IntradayDirectional()
    s.strategy_id = "intraday_directional_nifty"
    s.params = params or {}
    s._mode = "paper"
    s._slog = None

    ind = MagicMock()
    ind.ema.return_value = None
    ind.pivots.return_value = None
    ind.supertrend_variants.return_value = {}

    market = MagicMock()
    market.subscribe = AsyncMock(return_value=True)
    market.unsubscribe = AsyncMock()
    market.ltp_with_age = AsyncMock(return_value=(Decimal("100"), 0.1))
    market.cache_get = AsyncMock(return_value=None)
    # `spec=` so a wrong keyword raises here instead of silently passing — a bare
    # AsyncMock swallowed `ttl=` where `MarketControl.cache_set` takes `ex=`, which
    # would have thrown at runtime the first time the day cap fired.
    market.cache_set = AsyncMock(spec=MarketControl.cache_set)

    ctx = SimpleNamespace(
        params=s.params, watchlist=[], log=MagicMock(), indicators=ind, market=market,
        orders=orders or _FakeOrders(), session_maker=None, chain_hub=None,
        option_bars_col=None, _event_service=None,
    )
    ctx.emit_critical = MagicMock()

    await s.on_init(ctx)
    # on_init starts a real reconcile task; tests drive `_reconcile_divergences` directly.
    s._reconcile_task.cancel()
    return s


def _leg(sid: str = "1001", *, lots: int = 3, kind: str = "short") -> LiveLeg:
    return LiveLeg(
        security_id=sid, segment="NSE_FNO", opt_type="PE", strike=24000.0, lots=lots,
        entry_price=Decimal("100"), entry_time=datetime(2026, 7, 1, 10, 0), kind=kind,
    )


# ---------------------------------------------------------------------------- #
# Invariant 1 — one leg per security                                            #
# ---------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_duplicate_leg_for_one_security_is_refused() -> None:
    """Two leg records for one broker position is the state that let the 2026-07-09
    incident double-count lots; `_add_leg` must reject the second outright."""
    s = await _build()
    s._add_leg(_leg("1001"))

    with pytest.raises(ValueError, match="duplicate leg"):
        s._add_leg(_leg("1001", lots=9))

    assert s._legs["1001"].lots == 3
    assert s.ctx.emit_critical.call_args[0][0] == EventType.LEG_STATE_DIVERGED


# ---------------------------------------------------------------------------- #
# Invariant 2 — per-sid lock across every broker read-modify-write               #
# ---------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_lock_is_per_security_and_shared_by_open_and_close() -> None:
    s = await _build()
    assert s._lock_for("1001") is s._lock_for("1001")
    assert s._lock_for("1001") is not s._lock_for("1002")
    assert isinstance(s._lock_for("1001"), asyncio.Lock)


@pytest.mark.asyncio
async def test_concurrent_opens_on_one_security_cannot_jointly_exceed_the_cap() -> None:
    """The cap is read inside the lock. Two coroutines racing to open must serialise:
    the second sees the first's fill and is capped, rather than both reading 0 lots."""
    orders = _FakeOrders(net_qty=0)
    s = await _build({"initial_lots": 6, "max_lots": 6}, orders=orders)
    s._lot_size = 75
    s._resolve_strike = AsyncMock(return_value=_instrument("1001", 24000))
    s._fill_or_abort = AsyncMock(return_value=Decimal("100"))

    async def _place_and_book(**kw):
        orders.placed.append(kw)
        # The broker now holds what was just sold — what the *next* cap read must see.
        orders.net_qty -= kw["qty"]
        return SimpleNamespace(order_id=len(orders.placed), status="FILLED")

    orders.place_order = _place_and_book  # type: ignore[method-assign]

    now = datetime(2026, 7, 1, 10, 0)
    results = await asyncio.gather(
        s._open_position(now, 24000.0, Side.PE, 6),
        s._open_position(now, 24000.0, Side.PE, 6),
    )

    assert sum(1 for r in results if r) == 1, "only one open should land"
    assert abs(orders.net_qty) // 75 == 6, "never above the 6-lot cap"


# ---------------------------------------------------------------------------- #
# Invariant 3 — close side comes from the broker's net_qty sign, not leg.kind    #
# ---------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_close_uses_broker_sign_when_it_contradicts_the_leg_kind() -> None:
    """A leg tracked as `short` whose broker position is actually long must be closed
    with a SELL. Trusting `kind` here is the bug that grew 4 -> 8 -> 16 lots."""
    orders = _FakeOrders(net_qty=+225)  # long 3 lots, contradicting kind="short"
    s = await _build(orders=orders)
    s._lot_size = 75
    leg = _leg("1001", lots=3, kind="short")
    s._add_leg(leg)
    s._ltp_cache["1001"] = 100.0

    await s._close_leg(leg, "test")

    assert orders.placed[-1]["side"] == "SELL"
    assert s.ctx.emit_critical.call_args[0][0] == EventType.LEG_TYPE_CONTRADICTED
    assert "1001" not in s._legs


@pytest.mark.asyncio
async def test_close_of_a_genuine_short_buys_back() -> None:
    orders = _FakeOrders(net_qty=-225)
    s = await _build(orders=orders)
    s._lot_size = 75
    leg = _leg("1001", lots=3)
    s._add_leg(leg)
    s._ltp_cache["1001"] = 40.0

    await s._close_leg(leg, "square_off")

    assert orders.placed[-1]["side"] == "BUY"
    assert orders.placed[-1]["qty"] == 225
    assert orders.cancelled == ["1001"], "open entry orders cancelled before flattening"
    assert s.ctx.emit_critical.call_count == 0


# ---------------------------------------------------------------------------- #
# Invariant 4 — never close more lots than the broker actually holds             #
# ---------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_close_is_clamped_to_the_broker_lot_count() -> None:
    orders = _FakeOrders(net_qty=-150)  # broker holds 2 lots; memory thinks 9
    s = await _build(orders=orders)
    s._lot_size = 75
    leg = _leg("1001", lots=9)
    s._add_leg(leg)
    s._ltp_cache["1001"] = 40.0

    await s._close_leg(leg, "square_off")

    assert orders.placed[-1]["qty"] == 150, "closed the broker's 2 lots, not memory's 9"


@pytest.mark.asyncio
async def test_sub_lot_broker_residual_flags_divergence_and_keeps_the_leg() -> None:
    """`close_lots == 0` means the broker holds less than one lot. Placing a 0-qty order
    would be meaningless and dropping the leg would orphan the residual — so the leg
    stays tracked and the divergence is surfaced."""
    orders = _FakeOrders(net_qty=-30)  # 30 < one 75-lot
    s = await _build(orders=orders)
    s._lot_size = 75
    leg = _leg("1001", lots=1)
    s._add_leg(leg)
    s._ltp_cache["1001"] = 40.0

    await s._close_leg(leg, "square_off")

    assert orders.placed == []
    assert "1001" in s._legs
    assert s.ctx.emit_critical.call_args[0][0] == EventType.LEG_STATE_DIVERGED


@pytest.mark.asyncio
async def test_close_with_a_flat_broker_just_drops_the_leg() -> None:
    orders = _FakeOrders(net_qty=0)
    s = await _build(orders=orders)
    leg = _leg("1001")
    s._add_leg(leg)
    s._ltp_cache["1001"] = 40.0

    await s._close_leg(leg, "square_off")

    assert orders.placed == []
    assert s._legs == {}


@pytest.mark.asyncio
async def test_unpriced_close_is_refused_rather_than_traded_blind() -> None:
    orders = _FakeOrders(net_qty=-225)
    s = await _build(orders=orders)
    leg = _leg("1001")
    s._add_leg(leg)
    # no LTP in the cache

    await s._close_leg(leg, "square_off")

    assert orders.placed == []
    assert "1001" in s._legs
    assert s.ctx.emit_critical.call_args[0][0] == EventType.CLOSE_UNPRICED


# ---------------------------------------------------------------------------- #
# Invariant 5 — leg identity is durable across a restart                         #
# ---------------------------------------------------------------------------- #


class _Row:
    def __init__(self, sid: str, kind: str, opt_type: str, strike: float) -> None:
        self.security_id = sid
        self.leg_kind = kind
        self.opt_type = opt_type
        self.strike = Decimal(str(strike))
        self.expiry = _ENTRY_DAY


def _script_session(s: IntradayDirectional, rows: list[_Row]) -> MagicMock:
    session = MagicMock()
    scalars = SimpleNamespace(all=lambda: rows)
    session.execute = AsyncMock(return_value=SimpleNamespace(scalars=lambda: scalars))
    session.commit = AsyncMock()
    session.add = MagicMock()
    maker = MagicMock()
    maker.return_value.__aenter__ = AsyncMock(return_value=session)
    maker.return_value.__aexit__ = AsyncMock(return_value=False)
    s.ctx.session_maker = maker
    return session


@pytest.mark.asyncio
async def test_rehydrate_restores_kind_from_the_durable_row_not_from_sign() -> None:
    """A long hedge and a short leg both come back with the kind the table records —
    sign alone cannot tell a hedge from anything else that happens to be long."""
    orders = _FakeOrders(net_qty=-225, avg=Decimal("88"))
    s = await _build(orders=orders)
    s._lot_size = 75
    _script_session(s, [
        _Row("1001", "short", "PE", 24000),
        _Row("1002", "hedge", "PE", 23000),
    ])

    await s._rehydrate_legs()

    assert s._legs["1001"].kind == "short"
    assert s._legs["1002"].kind == "hedge"
    assert s._legs["1001"].lots == 3
    assert s._legs["1001"].entry_price == Decimal("88")
    # The decision core is re-armed from the restored short, not left flat.
    assert s._core.is_open and s._core.side is Side.PE and s._core.lots == 3


@pytest.mark.asyncio
async def test_rehydrate_closes_the_row_when_the_broker_is_already_flat() -> None:
    orders = _FakeOrders(net_qty=0)
    s = await _build(orders=orders)
    session = _script_session(s, [_Row("1001", "short", "PE", 24000)])

    await s._rehydrate_legs()

    assert s._legs == {}
    assert not s._core.is_open
    assert session.execute.await_count >= 2, "the stale row is marked closed"


# ---------------------------------------------------------------------------- #
# Invariant 6 — an unresolved entry price must never discard a real fill         #
# ---------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_entry_recovers_a_real_fill_when_the_price_read_fails(monkeypatch) -> None:
    """`_fill_or_abort` falls through to `confirm_fill_or_recover`, which only adopts a
    price the *broker* reports — so an order that filled while the price read timed out
    becomes a tracked leg instead of an orphan."""
    from pdp.strategy import fills

    s = await _build()
    monkeypatch.setattr(fills, "await_fill_avg_px", AsyncMock(return_value=None))
    monkeypatch.setattr(
        fills, "confirm_fill_or_recover", AsyncMock(return_value=Decimal("123.5"))
    )

    px = await s._fill_or_abort("1001", SimpleNamespace(order_id=1, status="FILLED"))

    assert px == Decimal("123.5")
    assert s.ctx.emit_critical.call_count == 0


@pytest.mark.asyncio
async def test_entry_aborts_and_alerts_when_no_fill_can_be_proven(monkeypatch) -> None:
    from pdp.strategy import fills

    s = await _build()
    monkeypatch.setattr(fills, "await_fill_avg_px", AsyncMock(return_value=None))
    monkeypatch.setattr(fills, "confirm_fill_or_recover", AsyncMock(return_value=None))

    px = await s._fill_or_abort("1001", SimpleNamespace(order_id=1, status="FILLED"))

    assert px is None
    assert s.ctx.emit_critical.call_args[0][0] == EventType.MISSING_LTP


@pytest.mark.asyncio
async def test_open_position_registers_no_leg_when_the_fill_cannot_be_proven() -> None:
    orders = _FakeOrders(net_qty=0)
    s = await _build(orders=orders)
    s._resolve_strike = AsyncMock(return_value=_instrument("1001", 24000))
    s._fill_or_abort = AsyncMock(return_value=None)

    opened = await s._open_position(
        datetime(2026, 7, 1, 10, 0), 24000.0, Side.PE, 3
    )

    assert opened is False
    assert s._legs == {}
    assert not s._core.is_open


# ---------------------------------------------------------------------------- #
# Invariant 7 — per-security lot cap                                            #
# ---------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_cap_lots_trims_to_the_remaining_headroom() -> None:
    s = await _build({"max_lots": 9}, orders=_FakeOrders(net_qty=-450))  # 6 lots held
    s._lot_size = 75

    assert await s._cap_lots("1001", 6) == 3
    assert s.ctx.emit_critical.call_count == 0


@pytest.mark.asyncio
async def test_cap_lots_refuses_entirely_at_the_cap_and_alerts() -> None:
    s = await _build({"max_lots": 9}, orders=_FakeOrders(net_qty=-675))  # 9 lots held
    s._lot_size = 75

    assert await s._cap_lots("1001", 3) == 0
    assert s.ctx.emit_critical.call_args[0][0] == EventType.POSITION_SIZE_CAPPED


# ---------------------------------------------------------------------------- #
# Invariant 8 — reconciliation runs unattended                                  #
# ---------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_reconcile_surfaces_a_memory_vs_broker_lot_divergence() -> None:
    s = await _build(orders=_FakeOrders(net_qty=-150))  # broker 2 lots
    s._lot_size = 75
    s._add_leg(_leg("1001", lots=9))

    await s._reconcile_divergences()

    assert s.ctx.emit_critical.call_args[0][0] == EventType.LEG_STATE_DIVERGED


@pytest.mark.asyncio
async def test_reconcile_is_silent_when_memory_matches_the_broker() -> None:
    s = await _build(orders=_FakeOrders(net_qty=-225))
    s._lot_size = 75
    s._add_leg(_leg("1001", lots=3))

    await s._reconcile_divergences()

    assert s.ctx.emit_critical.call_count == 0


@pytest.mark.asyncio
async def test_reconcile_task_is_started_on_init_and_cancelled_on_shutdown() -> None:
    s = IntradayDirectional()
    s.strategy_id = "intraday_directional_nifty"
    s.params = {}
    ctx = SimpleNamespace(
        params={}, watchlist=[], log=MagicMock(), indicators=MagicMock(),
        market=None, orders=_FakeOrders(), session_maker=None, chain_hub=None,
        option_bars_col=None, _event_service=None,
    )
    ctx.emit_critical = MagicMock()

    await s.on_init(ctx)
    assert not s._reconcile_task.done()

    await s.on_shutdown()
    await asyncio.sleep(0)
    assert s._reconcile_task.cancelled() or s._reconcile_task.cancelling()


# ---------------------------------------------------------------------------- #
# Rollup — all-or-nothing                                                       #
# ---------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_roll_that_cannot_price_an_acceptable_atm_leaves_the_leg_untouched() -> None:
    """Preconditions are checked before the book is mutated — a roll that can't reopen
    must not have already closed. Close-then-fail-to-reopen is the 2026-07-09 shape."""
    orders = _FakeOrders(net_qty=-225)
    s = await _build({"roll_trigger_prem": 20.0, "roll_target_min_prem": 60.0},
                     orders=orders)
    s._lot_size = 75
    s._add_leg(_leg("1001", lots=3))
    s._core.on_open(Side.PE, 3, 100.0, 24000.0, datetime(2026, 7, 1, 10, 0))
    s._resolve_strike = AsyncMock(return_value=_instrument("2001", 24100))
    s.ctx.market.ltp_with_age = AsyncMock(return_value=(Decimal("5"), 0.1))  # < 60

    rolled = await s._try_roll(datetime(2026, 7, 1, 13, 0), 24100.0, 15.0)

    assert rolled is False
    assert "1001" in s._legs
    assert orders.placed == [], "nothing traded"
    assert s._core.rolls_today == 0


@pytest.mark.asyncio
async def test_roll_skips_when_atm_resolves_to_the_strike_already_held() -> None:
    s = await _build(orders=_FakeOrders(net_qty=-225))
    s._lot_size = 75
    s._add_leg(_leg("1001", lots=3))
    s._core.on_open(Side.PE, 3, 100.0, 24000.0, datetime(2026, 7, 1, 10, 0))
    s._resolve_strike = AsyncMock(return_value=_instrument("1001", 24000))

    assert await s._try_roll(datetime(2026, 7, 1, 13, 0), 24000.0, 15.0) is False
    assert "1001" in s._legs


@pytest.mark.asyncio
async def test_successful_roll_preserves_the_lot_count() -> None:
    orders = _FakeOrders(net_qty=-450)  # 6 lots
    s = await _build({"max_lots": 9, "roll_target_min_prem": 20.0}, orders=orders)
    s._lot_size = 75
    s._add_leg(_leg("1001", lots=6))
    s._core.on_open(Side.PE, 6, 100.0, 24000.0, datetime(2026, 7, 1, 10, 0))
    s._ltp_cache["1001"] = 15.0
    s.ctx.market.ltp_with_age = AsyncMock(return_value=(Decimal("95"), 0.1))
    s._fill_or_abort = AsyncMock(return_value=Decimal("95"))

    strikes = iter([_instrument("2001", 24100), _instrument("2001", 24100)])
    s._resolve_strike = AsyncMock(side_effect=lambda *a, **k: next(strikes))

    # After the close the broker is flat, so the reopen's cap read sees full headroom.
    async def _place(**kw):
        orders.placed.append(kw)
        orders.net_qty = 0 if kw["side"] == "BUY" else -kw["qty"]
        return SimpleNamespace(order_id=len(orders.placed), status="FILLED")

    orders.place_order = _place  # type: ignore[method-assign]

    rolled = await s._try_roll(datetime(2026, 7, 1, 13, 0), 24100.0, 15.0)

    assert rolled is True
    assert s._core.lots == 6, "the roll re-establishes the same size"
    assert "2001" in s._legs and "1001" not in s._legs
    assert s._core.rolls_today == 1


# ---------------------------------------------------------------------------- #
# Session / risk gating                                                         #
# ---------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_opening_range_is_captured_only_from_the_0915_candle() -> None:
    s = await _build()
    ist = datetime(2026, 7, 1, 9, 15, tzinfo=None)
    s._maybe_capture_orb(ist, SimpleNamespace(high=24100.0, low=24000.0))

    assert (s._orb_low, s._orb_high) == (24000.0, 24100.0)

    # A later candle must not overwrite the range.
    s._maybe_capture_orb(
        datetime(2026, 7, 1, 9, 30), SimpleNamespace(high=99999.0, low=0.0)
    )
    assert s._orb_high == 24100.0


@pytest.mark.asyncio
async def test_a_missing_0915_candle_blocks_the_session_rather_than_using_a_later_bar() -> None:
    s = await _build()
    s._maybe_capture_orb(
        datetime(2026, 7, 1, 9, 30), SimpleNamespace(high=24100.0, low=24000.0)
    )

    assert s._orb_high is None
    assert s._orb_unseeded is True
    assert s.ctx.emit_critical.call_args[0][0] == EventType.INDICATOR_UNSEEDED
    assert await s._entry_allowed(_ENTRY_DAY) is False


@pytest.mark.asyncio
async def test_day_loss_cap_ends_the_day_and_persists_a_halt_marker() -> None:
    s = await _build(orders=_FakeOrders(net_qty=0))
    s._day_key = _ENTRY_DAY
    sig = SimpleNamespace(reason=ExitReason.DAY_LOSS_CAP, detail="day_pnl=-10001")

    await s._handle_exit(sig, datetime(2026, 7, 1, 13, 0))

    assert s._done_for_day is True
    s.ctx.market.cache_set.assert_awaited_once()
    call = s.ctx.market.cache_set.await_args
    assert call[0][0].endswith("2026-07-01")
    assert call.kwargs == {"ex": 86400}, "cache_set takes `ex`, not `ttl`"


@pytest.mark.asyncio
async def test_square_off_ends_the_day_without_a_halt_marker() -> None:
    """Square-off is the normal end of a session — persisting a halt marker would carry
    a false "halted" state into the console and any same-day restart."""
    s = await _build(orders=_FakeOrders(net_qty=0))
    s._day_key = _ENTRY_DAY

    await s._handle_exit(
        SimpleNamespace(reason=ExitReason.SQUARE_OFF, detail="15:15"),
        datetime(2026, 7, 1, 15, 15),
    )

    assert s._done_for_day is True
    s.ctx.market.cache_set.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_restored_halt_marker_keeps_the_day_ended_after_a_restart() -> None:
    s = await _build()
    s._day_key = _ENTRY_DAY
    s.ctx.market.cache_get = AsyncMock(return_value="1")

    await s._maybe_restore_halt_marker()

    assert s._done_for_day is True
    assert s._core.day_ended is True


@pytest.mark.asyncio
async def test_day_rollover_clears_session_state() -> None:
    s = await _build()
    s._maybe_reset_day(_ENTRY_DAY)
    s._orb_high, s._orb_low = 24100.0, 24000.0
    s._vwap_sum, s._vwap_n = 1000.0, 10
    s._done_for_day = True
    s._core.on_open(Side.PE, 3, 100.0, 24000.0, datetime(2026, 7, 1, 10, 0))

    s._maybe_reset_day(date(2026, 7, 2))

    assert s._orb_high is None and s._orb_low is None
    assert (s._vwap_sum, s._vwap_n) == (0.0, 0)
    assert s._done_for_day is False
    assert not s._core.is_open


@pytest.mark.asyncio
async def test_an_unresolvable_lot_size_blocks_entries_but_keeps_the_last_known_good() -> None:
    """The instruments table is authoritative; YAML is advisory. A lookup failure must
    not silently trade the stale YAML size."""
    s = await _build({"lot_size": 75})
    _script_session(s, [])
    monkey = AsyncMock(return_value=None)
    import pdp.strategies.intraday_directional as mod

    original = mod.lot_size_for_underlying
    mod.lot_size_for_underlying = monkey  # type: ignore[assignment]
    try:
        await s._maybe_resolve_lot_size(_ENTRY_DAY)
    finally:
        mod.lot_size_for_underlying = original  # type: ignore[assignment]

    assert s._lot_size_degraded is True
    assert s._lot_size == 75, "last-known-good retained for pricing open legs"
    assert await s._entry_allowed(_ENTRY_DAY) is False
    assert await s._open_position(
        datetime(2026, 7, 1, 10, 0), 24000.0, Side.PE, 3
    ) is False


@pytest.mark.asyncio
async def test_session_vwap_accumulates_only_on_1m_bars() -> None:
    """Same series and same arithmetic as `intraday_loader._session_vwap_series`, so the
    two paths agree bar for bar."""
    s = await _build()
    bar = SimpleNamespace(
        security_id="13", timeframe="1m", bar_time=datetime(2026, 7, 1, 9, 20),
        high=24030.0, low=24000.0, close=24015.0,
    )
    await s.on_bar(bar)

    assert s._vwap_n == 1
    assert s._vwap_sum == pytest.approx((24030.0 + 24000.0 + 24015.0) / 3.0)


@pytest.mark.asyncio
async def test_vwap_source_off_is_honoured_live_not_just_in_the_backtest() -> None:
    """A config value must mean the same thing on both paths. `off` was previously read
    by `IntradayDirectionalConfig` and ignored here, so a config that disabled the VWAP
    gate in the backtest would still have traded on it live."""
    s = await _build({"vwap_source": "off"})
    await s.on_bar(SimpleNamespace(
        security_id="13", timeframe="1m", bar_time=datetime(2026, 7, 1, 9, 20),
        high=24030.0, low=24000.0, close=24015.0,
    ))

    assert s._vwap_n == 0
    assert (await s.state())["session_vwap"] is None


@pytest.mark.asyncio
async def test_an_unknown_vwap_source_is_rejected_at_init() -> None:
    with pytest.raises(ValueError, match="vwap_source must be one of"):
        await _build({"vwap_source": "volume_weighted"})


@pytest.mark.asyncio
async def test_bars_for_another_security_are_ignored() -> None:
    s = await _build()
    await s.on_bar(SimpleNamespace(
        security_id="25", timeframe="1m", bar_time=datetime(2026, 7, 1, 9, 20),
        high=1.0, low=1.0, close=1.0,
    ))
    assert s._vwap_n == 0


# ---------------------------------------------------------------------------- #
# Readiness + config plumbing                                                   #
# ---------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_readiness_blocks_on_unseeded_indicators() -> None:
    s = await _build()
    r = await s.check_readiness()

    assert r.is_blocked
    blocked = {c.name for c in r.components if c.state == "blocked"}
    assert {"ema", "supertrend", "orb", "vwap"} <= blocked


@pytest.mark.asyncio
async def test_readiness_clears_once_every_input_is_seeded() -> None:
    s = await _build()
    s.ctx.indicators.ema.return_value = SimpleNamespace(values={9: 24010.0, 20: 24000.0})
    s.ctx.indicators.supertrend_variants.return_value = {
        "st_10_2": SimpleNamespace(direction=1)
    }
    s.ctx.indicators.pivots.return_value = SimpleNamespace(
        cam_r3=1.0, cam_r4=2.0, cam_s3=3.0, cam_s4=4.0
    )
    s._orb_high, s._orb_low = 24100.0, 24000.0
    s._vwap_n = 5

    assert not (await s.check_readiness()).is_blocked


def test_params_from_config_uses_yaml_values_and_core_defaults() -> None:
    p = params_from_config({"initial_lots": 5, "squareoff_ist": "15:05"})

    assert p.initial_lots == 5
    assert p.squareoff_ist == time(15, 5)
    assert p.max_lots == 9, "untouched knobs fall back to IntradayParams' own defaults"
    p.validate()


def test_supertrend_read_targets_the_10_2_variant_not_the_engine_default() -> None:
    """`ctx.indicators.supertrend()` returns the engine-wide SUPERTREND_PERIOD (3/1 by
    default) — reading it here would silently trade a different indicator than the spec."""
    s = IntradayDirectional()
    ind = MagicMock()
    ind.supertrend_variants.return_value = {"st_10_2": SimpleNamespace(direction=-1)}
    s.ctx = SimpleNamespace(indicators=ind)  # type: ignore[assignment]
    s.sid = "13"

    assert s._st_dir("5m") == -1
    ind.supertrend_variants.assert_called_once_with("13", "5m")
    ind.supertrend.assert_not_called()


@pytest.mark.asyncio
async def test_state_snapshot_reports_the_open_leg() -> None:
    s = await _build(orders=_FakeOrders(net_qty=-225))
    s._lot_size = 75
    s._add_leg(_leg("1001", lots=3))
    s._core.on_open(Side.PE, 3, 100.0, 24000.0, datetime(2026, 7, 1, 10, 0))
    s._ltp_cache["1001"] = 60.0

    st = await s.state()

    assert st["side"] == "PE"
    assert st["lots"] == 3
    assert st["ltp"] == 60.0
    assert st["unrealized"] == pytest.approx((100.0 - 60.0) * 3 * 75)
    assert [lg["sid"] for lg in st["legs"]] == ["1001"]
