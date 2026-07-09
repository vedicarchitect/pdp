"""End-to-end smoke test for the SuperTrend short strategy pipeline.

Wires the real IndicatorEngine + StrategyHost + SuperTrendShort strategy + JournalService
together. Synthetic NIFTY 5m bars drive the SuperTrend; a fake order router stands in for
the paper engine and simulates fills by publishing trade events to a real OrdersHub (the
same event the PaperBroker emits after a tick fills). Strike resolution is monkeypatched so
no DB is needed. This validates: signal -> strategy -> order -> fill -> journal.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

import pdp.strategies.supertrend_short as strat_mod
from pdp.indicators.engine import IndicatorEngine
from pdp.journal.service import JournalService
from pdp.market.bars import BarClosed
from pdp.orders.ws import OrdersHub
from pdp.strategy.host import StrategyHost

# Column-key -> ledger-field mapping for the fake position reads.
_COL_FIELD = {"net_qty": "net", "avg_price": "avg", "realized_pnl": "realized"}


def _default_pos() -> dict:
    return {"net": 0, "avg": Decimal("0"), "realized": Decimal("0")}


class _Result:
    def __init__(self, row=None) -> None:
        self._row = row

    def first(self):
        return self._row

    def scalar_one(self):
        return 0

    def scalar_one_or_none(self):
        return None

    def all(self):
        return [] if self._row is None else [self._row]

    def scalars(self):
        return self  # allows result.scalars().all() → [] when no match


class _FakeSession:
    """Answers the strategy's position reads from a shared ledger.

    Introspects the SQLAlchemy statement's selected columns + bound ``security_id`` so
    ``get_net_qty`` / ``get_position`` / ``get_realized_pnl`` see real fill state.
    """

    def __init__(self, ledger: dict[str, dict]) -> None:
        self._ledger = ledger

    async def execute(self, stmt, *a, **k):
        try:
            cols = [c.key for c in stmt.selected_columns]
            params = stmt.compile().params
        except Exception:
            return _Result(None)
        sid = next((v for key, v in params.items() if "security_id" in key), None)
        if sid is None or not all(c in _COL_FIELD for c in cols):
            return _Result(None)  # e.g. the open-order count query
        pos = self._ledger.get(sid, _default_pos())
        return _Result(tuple(pos[_COL_FIELD[c]] for c in cols))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSessionMaker:
    def __init__(self, ledger: dict[str, dict]) -> None:
        self._ledger = ledger

    def __call__(self):
        return _FakeSession(self._ledger)


class _FakeRouter:
    """Stands in for OrderRouter+PaperBroker: records orders and simulates fills.

    SELL fills at 100, BUY (cover) fills at 60 — so any closed round-trip is profitable.
    Maintains a shared ``ledger`` (net/avg/realized per security) using the same
    short-side math as the real paper engine, so the strategy's position reads agree.
    """

    def __init__(self, hub: OrdersHub) -> None:
        self._hub = hub
        self.orders: list[dict] = []
        self.ledger: dict[str, dict] = {}

    def _fill_ledger(self, sid: str, side: str, qty: int, fill: Decimal) -> None:
        p = self.ledger.setdefault(sid, _default_pos())
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

    async def cancel_open_entry_orders(self, session, security_id, strategy_id):
        return []

    async def place_order(self, session, *, security_id, side, qty, strategy_id, **kw):
        oid = len(self.orders) + 1
        self.orders.append({"security_id": security_id, "side": side, "qty": qty})
        fill = Decimal("100") if side == "SELL" else Decimal("60")
        self._fill_ledger(security_id, str(side), int(qty), fill)
        self._hub.publish(
            "trade",
            {
                "id": oid,
                "order_id": oid,
                "security_id": security_id,
                "side": side,
                "qty": qty,
                "fill_price": str(fill),
                "charges": "5",
                "filled_at": datetime.now(UTC).isoformat(),
                "strategy_id": strategy_id,
            },
        )
        return SimpleNamespace(id=oid, status="OPEN", security_id=security_id, side=side, qty=qty)


def _bar(i: int, close: float) -> BarClosed:
    base = datetime(2026, 6, 8, 4, 0, tzinfo=UTC)
    return BarClosed(
        security_id="13",
        timeframe="5m",
        bar_time=base + timedelta(minutes=5 * i),
        open=Decimal(str(close)),
        high=Decimal(str(close + 1)),
        low=Decimal(str(close - 1)),
        close=Decimal(str(close)),
        volume=0,
        oi=0,
    )


@pytest.mark.asyncio
async def test_pipeline_signal_to_journal(tmp_path, monkeypatch):
    # Strike resolver -> deterministic option per side, no DB.
    async def fake_resolve(
        session, *, underlying, spot, option_type, otm_steps=1, strike_step=None, expiry=None
    ):
        strike = 22450 if option_type == "PE" else 22550
        return SimpleNamespace(
            security_id=f"OPT_{option_type}",
            exchange_segment="NSE_FNO",
            strike=Decimal(str(strike)),
        )

    monkeypatch.setattr(strat_mod, "resolve_otm_option", fake_resolve)
    # Bars are timestamped 09:30-10:25 IST (UTC base 04:00), inside the trading window;
    # the strategy gates on bar time, so no clock patching is needed.

    # Strategy YAML.
    (tmp_path / "st_smoke.yaml").write_text(
        "id: st_smoke\n"
        "class: pdp.strategies.supertrend_short.SuperTrendShort\n"
        "watchlist:\n"
        "  - security_id: '13'\n"
        "    exchange_segment: IDX_I\n"
        "    timeframes: [5m]\n"
        "params:\n"
        "  underlying: NIFTY\n"
        "  underlying_security_id: '13'\n"
        "  timeframe: 5m\n"
        "  lot_size: 65\n"
        "  start_lots: 2\n"
        "  add_lots: 1\n"
        "  max_lots: 5\n"
        "  start_ist: '09:30'\n"
        "  square_off_ist: '15:10'\n"
        "risk:\n"
        "  max_open_orders: 50\n"
        "  max_daily_loss_inr: 100000\n"
    )

    hub = OrdersHub()
    router = _FakeRouter(hub)
    engine = IndicatorEngine(st_period=3, st_multiplier=1)
    journal = JournalService(mongo_db=None)
    journal.subscribe_fill_events(hub)

    host = StrategyHost(tmp_path, router, _FakeSessionMaker(router.ledger))
    host.set_indicator_engine(engine)
    host.set_market_adapter(None)  # no live feed -> ctx.market is a safe no-op
    host.load_registry()
    await host.start("st_smoke")

    # The warmup-disarm guard (strategy-critical-data-alerts) disarms any strategy whose
    # indicators lack 200 warmup bars at start. This smoke test intentionally drives the
    # signal→journal pipeline with a short synthetic series (not a full warmup), so
    # explicitly re-arm before feeding bars — warmup coverage is out of scope here.
    host._running["st_smoke"].instance._disarmed = False

    try:
        # Strong uptrend then a sharp drop to force at least one direction flip.
        series = [100, 101, 103, 105, 107, 109, 111, 113, 95, 80, 70, 60]
        for i, price in enumerate(series):
            engine.on_bar(_bar(i, price))  # router order: indicator before strategy
            host.on_bar(_bar(i, price))
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.2)

        # Both option sides were sold at some point.
        secs = {o["security_id"] for o in router.orders}
        assert "OPT_PE" in secs and "OPT_CE" in secs

        # At least one cover (BUY) happened.
        assert any(o["side"] == "BUY" for o in router.orders)

        # Journal recorded fills and computed a profitable closed round-trip.
        day = journal.get_day()
        stats = day["stats"]
        assert stats["total_trades"] == len(router.orders)
        assert stats["round_trips"] >= 1
        assert stats["wins"] == stats["round_trips"]
        assert stats["realized_pnl"] > 0
    finally:
        await host.stop("st_smoke")
