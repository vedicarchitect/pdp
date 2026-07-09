"""Behavioural tests for the SuperTrend short strategy.

The strategy is driven with a stubbed indicator, a faithful fake order ledger (which
mirrors the short-side weighted-average / realize-on-reduce math of the real paper
engine so leg- and day-stop logic can be exercised), a market control exposing LTP,
a monkeypatched strike resolver, and a controllable IST clock.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import pdp.strategies.supertrend_short as mod
from pdp.indicators.supertrend import DOWN, UP, SuperTrendState
from pdp.market.bars import BarClosed
from pdp.strategies.supertrend_short import SuperTrendShort


class _Orders:
    """Fake ledger: fills market orders synchronously and tracks net/avg/realized.

    Set ``price`` (or ``price_by_sid[sid]``) to control the fill price of the next
    order, mirroring how the paper engine would fill on the prevailing LTP.
    """

    def __init__(self):
        self.calls: list[dict] = []
        self.price: Decimal = Decimal("100")
        self.price_by_sid: dict[str, Decimal] = {}
        self._pos: dict[str, dict] = {}  # sid -> {net, avg, realized}
        # When True, BUY (cover) orders are accepted but NOT filled — simulating a
        # MARKET cover whose fill lands after the next on_bar (the flip-race in GAP 2).
        self.defer_buy_fill: bool = False

    def _p(self, sid: str) -> dict:
        return self._pos.setdefault(sid, {"net": 0, "avg": Decimal("0"), "realized": Decimal("0")})

    async def place_order(self, *, security_id, side, qty, **kw):
        self.calls.append({"security_id": security_id, "side": side, "qty": qty, **kw})
        if str(side) == "BUY" and self.defer_buy_fill:
            return SimpleNamespace(id=len(self.calls), status="OPEN")  # fill deferred
        px = self.price_by_sid.get(security_id, self.price)
        self._apply_fill(security_id, str(side), int(qty), Decimal(str(px)))
        return SimpleNamespace(id=len(self.calls), status="OPEN")

    def _apply_fill(self, sid: str, side: str, qty: int, fill: Decimal) -> None:
        p = self._p(sid)
        signed = qty if side == "BUY" else -qty
        old_qty, old_avg = p["net"], p["avg"]
        new_qty = old_qty + signed
        if new_qty == 0:
            p["realized"] += (fill - old_avg) * Decimal(old_qty)
            p["avg"] = Decimal("0")
        elif (old_qty >= 0 and signed > 0) or (old_qty <= 0 and signed < 0):
            total = old_avg * Decimal(abs(old_qty)) + fill * Decimal(qty)
            p["avg"] = total / Decimal(abs(new_qty))
        else:
            reduce_qty = min(abs(signed), abs(old_qty))
            if old_qty > 0:
                p["realized"] += (fill - old_avg) * Decimal(reduce_qty)
            else:
                p["realized"] += (old_avg - fill) * Decimal(reduce_qty)
        p["net"] = new_qty

    async def cancel_open_entry_orders(self, security_id):
        return []

    async def get_net_qty(self, security_id):
        return self._p(security_id)["net"]

    async def get_position(self, security_id):
        p = self._p(security_id)
        return p["net"], p["avg"]

    async def get_realized_pnl(self, security_id):
        return self._p(security_id)["realized"]


class _Indicators:
    def __init__(self):
        self.state: SuperTrendState | None = None

    def supertrend(self, security_id, timeframe):
        return self.state


class _Market:
    def __init__(self):
        self.subs: list[tuple[str, str]] = []
        self.unsubs: list[tuple[str, str]] = []
        self.ltp_by_sid: dict[str, Decimal | None] = {}
        # Age (seconds) of each sid's LTP; default 0.0 (fresh). Set > staleness to
        # exercise the GAP 5 stale-LTP fallback to bar close.
        self.ltp_age_by_sid: dict[str, float] = {}

    async def subscribe(self, security_id, segment):
        self.subs.append((security_id, segment))
        return True

    async def unsubscribe(self, security_id, segment):
        self.unsubs.append((security_id, segment))

    async def ltp(self, security_id):
        return self.ltp_by_sid.get(security_id)

    async def ltp_with_age(self, security_id):
        return self.ltp_by_sid.get(security_id), self.ltp_age_by_sid.get(security_id, 0.0)


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
            "leg_stop_per_lot": 1000,
            "day_stop": 10000,
        },
    )


def _bar(i: int, close: float = 22500.0, day: int = 8) -> BarClosed:
    base = datetime(2026, 6, day, 4, 0, tzinfo=UTC)
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
    async def fake_resolve(
        session, *, underlying, spot, option_type, otm_steps=1, strike_step=None, expiry=None
    ):
        strike = 22450 if option_type == "PE" else 22550
        return SimpleNamespace(
            security_id=f"OPT_{option_type}",
            exchange_segment="NSE_FNO",
            strike=Decimal(str(strike)),
        )

    monkeypatch.setattr(mod, "resolve_otm_option", fake_resolve)


_IST = ZoneInfo("Asia/Kolkata")


def _bar_ist(hh: int, mm: int, close: float = 22500.0, day: int = 8) -> BarClosed:
    """Bar timestamped at a specific IST time (the strategy now gates on bar time)."""
    return BarClosed(
        security_id="13",
        timeframe="5m",
        bar_time=datetime(2026, 6, day, hh, mm, tzinfo=_IST),
        open=Decimal(str(close)),
        high=Decimal(str(close + 5)),
        low=Decimal(str(close - 5)),
        close=Decimal(str(close)),
        volume=0,
        oi=0,
    )


@pytest.mark.asyncio
async def test_no_entry_before_start(patched_resolver, monkeypatch):
    orders, ind, market = _Orders(), _Indicators(), _Market()
    ind.state = SuperTrendState(direction=UP, value=Decimal("0"), flipped=False)
    strat = SuperTrendShort()
    await strat.on_init(_ctx(orders, ind, market))

    await strat.on_bar(_bar_ist(9, 0))  # bar timestamped before 09:30 IST

    assert orders.calls == []  # no trades before the window


@pytest.mark.asyncio
async def test_opens_short_pe_on_uptrend(patched_resolver, monkeypatch):
    orders, ind, market = _Orders(), _Indicators(), _Market()
    ind.state = SuperTrendState(direction=UP, value=Decimal("0"), flipped=False)
    strat = SuperTrendShort()
    await strat.on_init(_ctx(orders, ind, market))

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

    await strat.on_bar(_bar(1))  # open PE (09:35 IST)
    assert strat._current is not None

    await strat.on_bar(_bar_ist(15, 12))  # bar past square-off -> close all, done
    assert strat._current is None
    assert strat._done_for_day is True

    n_before = len(orders.calls)
    await strat.on_bar(_bar_ist(15, 13))  # no more trading
    assert len(orders.calls) == n_before


# --------------------------------------------------------------------------- #
# Risk controls                                                               #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_leg_stop_fires_and_no_reentry_same_bar(patched_resolver, monkeypatch):
    orders, ind, market = _Orders(), _Indicators(), _Market()
    ind.state = SuperTrendState(direction=UP, value=Decimal("0"), flipped=False)
    strat = SuperTrendShort()
    await strat.on_init(_ctx(orders, ind, market))

    orders.price = Decimal("100")  # open PE at 100, 2 lots = 130 qty
    await strat.on_bar(_bar(1))
    assert strat._current is not None and strat._current["option_type"] == "PE"

    # Price rises to 120: MTM = (100-120)*130 = -2600 <= -(1000*2) -> stop.
    market.ltp_by_sid["OPT_PE"] = Decimal("120")
    n_before = len(orders.calls)
    await strat.on_bar(_bar(2))

    buys = [c for c in orders.calls if c["side"] == "BUY"]
    assert len(buys) == 1 and buys[0]["security_id"] == "OPT_PE"  # leg bought back
    assert strat._current is None  # closed
    # No new entry on the stop bar: exactly one new order (the cover) since.
    assert len(orders.calls) == n_before + 1


@pytest.mark.asyncio
async def test_leg_stop_holds_below_threshold(patched_resolver, monkeypatch):
    orders, ind, market = _Orders(), _Indicators(), _Market()
    ind.state = SuperTrendState(direction=UP, value=Decimal("0"), flipped=False)
    strat = SuperTrendShort()
    await strat.on_init(_ctx(orders, ind, market))

    orders.price = Decimal("100")
    await strat.on_bar(_bar(1))  # open PE, 2 lots

    # Price 110: MTM = (100-110)*130 = -1300 > -2000 -> no stop; scales instead.
    market.ltp_by_sid["OPT_PE"] = Decimal("110")
    await strat.on_bar(_bar(2))

    assert strat._current is not None and strat._current["option_type"] == "PE"
    assert not any(c["side"] == "BUY" for c in orders.calls)
    assert strat._current["lots"] == 3  # scaled in, not stopped


@pytest.mark.asyncio
async def test_zero_ltp_does_not_trip_stop(patched_resolver, monkeypatch):
    orders, ind, market = _Orders(), _Indicators(), _Market()
    ind.state = SuperTrendState(direction=UP, value=Decimal("0"), flipped=False)
    strat = SuperTrendShort()
    await strat.on_init(_ctx(orders, ind, market))

    orders.price = Decimal("100")
    await strat.on_bar(_bar(1))  # open PE

    market.ltp_by_sid["OPT_PE"] = None  # stale/missing quote
    await strat.on_bar(_bar(2))
    assert not any(c["side"] == "BUY" for c in orders.calls)  # no stop on bogus price
    assert strat._current is not None


@pytest.mark.asyncio
async def test_day_stop_latches_and_blocks_entries(patched_resolver, monkeypatch):
    orders, ind, market = _Orders(), _Indicators(), _Market()
    ind.state = SuperTrendState(direction=UP, value=Decimal("0"), flipped=False)
    strat = SuperTrendShort()
    await strat.on_init(_ctx(orders, ind, market))

    orders.price = Decimal("100")
    await strat.on_bar(_bar(1))  # open PE at 100

    # Flip with the cover filling at 200: realized = (200-100)*-130 = -13000 <= -10000.
    orders.price = Decimal("200")
    ind.state = SuperTrendState(direction=DOWN, value=Decimal("0"), flipped=True)
    await strat.on_bar(_bar(2))  # close PE (big loss), open CE

    # Next bar: day cap already breached -> flatten and stop, no further entries.
    n_before = len(orders.calls)
    await strat.on_bar(_bar(3))
    assert strat._done_for_day is True
    assert strat._current is None

    n_after_stop = len(orders.calls)
    ind.state = SuperTrendState(direction=UP, value=Decimal("0"), flipped=False)
    await strat.on_bar(_bar(4))
    assert len(orders.calls) == n_after_stop  # no new entries after the day stop
    assert n_after_stop >= n_before  # at most the flatten cover


@pytest.mark.asyncio
async def test_day_accumulator_resets_next_day(patched_resolver, monkeypatch):
    orders, ind, market = _Orders(), _Indicators(), _Market()
    ind.state = SuperTrendState(direction=UP, value=Decimal("0"), flipped=False)
    strat = SuperTrendShort()
    await strat.on_init(_ctx(orders, ind, market))

    # Day 1: realize a big loss and hit the day stop.
    orders.price = Decimal("100")
    await strat.on_bar(_bar(1, day=8))
    orders.price = Decimal("200")
    ind.state = SuperTrendState(direction=DOWN, value=Decimal("0"), flipped=True)
    await strat.on_bar(_bar(2, day=8))
    await strat.on_bar(_bar(3, day=8))
    assert strat._done_for_day is True

    # Day 2: a bar on the next IST day clears the latch and the accumulator.
    orders.price = Decimal("100")
    ind.state = SuperTrendState(direction=UP, value=Decimal("0"), flipped=False)
    await strat.on_bar(_bar(1, day=9))
    assert strat._done_for_day is False
    assert strat._touched == {"OPT_PE"}  # baselines reset; fresh touch today
    assert strat._current is not None and strat._current["option_type"] == "PE"


# --------------------------------------------------------------------------- #
# Live↔backtest parity gaps (offline simulation of the live-only verifies)     #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_flip_open_deferred_when_cover_unfilled(patched_resolver):
    """GAP 2 (task 2.3): when the flip's cover order has not yet filled, the new leg
    is deferred (no opposite-side SELL) and ``_current`` stays None so a later bar retries."""
    orders, ind, market = _Orders(), _Indicators(), _Market()
    ind.state = SuperTrendState(direction=UP, value=Decimal("0"), flipped=False)
    strat = SuperTrendShort()
    await strat.on_init(_ctx(orders, ind, market))

    await strat.on_bar(_bar(1))  # open PE, net = -130
    assert strat._current is not None and strat._current["option_type"] == "PE"

    # Flip, but the MARKET cover does not fill this bar (race condition).
    orders.defer_buy_fill = True
    ind.state = SuperTrendState(direction=DOWN, value=Decimal("0"), flipped=True)
    await strat.on_bar(_bar(2))

    # The PE cover was placed, but no CE was opened because the old leg is still open.
    assert any(c["security_id"] == "OPT_PE" and c["side"] == "BUY" for c in orders.calls)
    assert not any(c["security_id"] == "OPT_CE" for c in orders.calls)
    assert strat._current is None  # cleared by _close_current; next bar retries

    # Next bar: the cover has now filled, so the deferred CE opens.
    orders.defer_buy_fill = False
    orders._apply_fill("OPT_PE", "BUY", 130, Decimal("100"))  # belated fill -> net 0
    await strat.on_bar(_bar(3))
    assert any(c["security_id"] == "OPT_CE" and c["side"] == "SELL" for c in orders.calls)
    assert strat._current is not None and strat._current["option_type"] == "CE"


@pytest.mark.asyncio
async def test_lots_sync_reads_net_from_positions_table(patched_resolver):
    """GAP 3 (task 3.2): on the first bar after a restart with a 3-lot position in the
    ledger, the scale-in counter is re-derived from net_qty, not stale in-memory state."""
    orders, ind, market = _Orders(), _Indicators(), _Market()
    ind.state = SuperTrendState(direction=UP, value=Decimal("0"), flipped=False)  # desired PE
    strat = SuperTrendShort()
    await strat.on_init(_ctx(orders, ind, market))
    strat.max_lots = 3  # so the synced count (3) doesn't immediately scale further

    # Simulate restart: recovered leg carries a stale lot count, but the ledger holds 3 lots.
    strat._current = {
        "security_id": "OPT_PE",
        "segment": "NSE_FNO",
        "option_type": "PE",
        "strike": 22450.0,
        "lots": 1,
    }
    orders._pos["OPT_PE"] = {"net": -3 * 65, "avg": Decimal("22500"), "realized": Decimal("0")}
    strat._touched.add("OPT_PE")  # day-realized accounting expects a baseline

    await strat.on_bar(_bar(1))  # close == 22500 == avg -> no leg stop

    assert strat._current is not None
    assert strat._current["lots"] == 3  # synced from abs(net)//lot_size, not the stale 1


@pytest.mark.asyncio
async def test_lots_sync_clears_when_position_flat(patched_resolver):
    """GAP 3 (task 3.2): if the ledger shows the position is flat, the stale open leg is
    dropped (``lots_sync_position_flat``) and the strategy re-enters fresh at start_lots."""
    orders, ind, market = _Orders(), _Indicators(), _Market()
    ind.state = SuperTrendState(direction=UP, value=Decimal("0"), flipped=False)
    strat = SuperTrendShort()
    await strat.on_init(_ctx(orders, ind, market))

    # Recovered leg claims 5 lots, but the ledger has no position for it.
    strat._current = {
        "security_id": "OPT_PE",
        "segment": "NSE_FNO",
        "option_type": "PE",
        "strike": 22450.0,
        "lots": 5,
    }
    strat._touched.add("OPT_PE")

    await strat.on_bar(_bar(1))

    # Stale 5-lot leg discarded; a fresh entry of start_lots (2) opened instead.
    assert strat._current is not None
    assert strat._current["lots"] == 2


@pytest.mark.asyncio
async def test_leg_stop_skips_when_ltp_stale(patched_resolver):
    """GAP 5 (task 5.5): a stale option LTP is not actionable — the stop is skipped (logged
    leg_stop_ltp_stale_fallback) rather than marking the option against the index bar close.
    The leg stays open and a later fresh tick catches the move."""
    orders, ind, market = _Orders(), _Indicators(), _Market()
    ind.state = SuperTrendState(direction=UP, value=Decimal("0"), flipped=False)
    strat = SuperTrendShort()
    await strat.on_init(_ctx(orders, ind, market))

    orders.price = Decimal("100")
    await strat.on_bar(_bar(1))  # open PE at 100, 2 lots

    # A 60s-old LTP at 200 would imply a stop-worthy loss, but it is stale -> ignored.
    market.ltp_by_sid["OPT_PE"] = Decimal("200")
    market.ltp_age_by_sid["OPT_PE"] = 60.0  # > leg_stop_ltp_staleness_secs (30)
    await strat.on_bar(_bar(2))

    assert not any(c["side"] == "BUY" for c in orders.calls)  # no stop on a stale quote
    assert strat._current is not None and strat._current["option_type"] == "PE"


@pytest.mark.asyncio
async def test_leg_stop_fires_on_fresh_ltp(patched_resolver):
    """GAP 5 (task 5.5): with a fresh LTP showing a stop-worthy loss, the stop fires; the
    NIFTY index bar close is never used as the option mark."""
    orders, ind, market = _Orders(), _Indicators(), _Market()
    ind.state = SuperTrendState(direction=UP, value=Decimal("0"), flipped=False)
    strat = SuperTrendShort()
    await strat.on_init(_ctx(orders, ind, market))

    orders.price = Decimal("100")
    await strat.on_bar(_bar(1))  # open PE at 100, 2 lots = 130 qty

    market.ltp_by_sid["OPT_PE"] = Decimal("120")  # fresh: MTM (100-120)*130 = -2600 <= -2000
    market.ltp_age_by_sid["OPT_PE"] = 5.0  # < staleness threshold
    await strat.on_bar(_bar(2, close=120.0))

    buys = [c for c in orders.calls if c["side"] == "BUY"]
    assert len(buys) == 1 and buys[0]["security_id"] == "OPT_PE"  # stopped on the fresh quote
    assert strat._current is None
