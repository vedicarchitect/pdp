"""End-to-end smoke test for the SuperTrend short strategy pipeline.

Wires the real IndicatorEngine + StrategyHost + SuperTrendShort strategy + JournalService
together. Synthetic NIFTY 5m bars drive the SuperTrend; a fake order router stands in for
the paper engine and simulates fills by publishing trade events to a real OrdersHub (the
same event the PaperBroker emits after a tick fills). Strike resolution is monkeypatched so
no DB is needed. This validates: signal -> strategy -> order -> fill -> journal.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

import pdp.strategies.supertrend_short as strat_mod
from pdp.indicators.engine import IndicatorEngine
from pdp.journal.service import JournalService
from pdp.market.bars import BarClosed
from pdp.orders.ws import OrdersHub
from pdp.strategy.host import StrategyHost


class _Result:
    def scalar_one(self):
        return 0

    def scalar_one_or_none(self):
        return None


class _FakeSession:
    async def execute(self, *a, **k):
        return _Result()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSessionMaker:
    def __call__(self):
        return _FakeSession()


class _FakeRouter:
    """Stands in for OrderRouter+PaperBroker: records orders and simulates fills.

    SELL fills at 100, BUY (cover) fills at 60 — so any closed round-trip is profitable.
    """

    def __init__(self, hub: OrdersHub) -> None:
        self._hub = hub
        self.orders: list[dict] = []

    async def place_order(self, session, *, security_id, side, qty, strategy_id, **kw):
        oid = len(self.orders) + 1
        self.orders.append({"security_id": security_id, "side": side, "qty": qty})
        self._hub.publish(
            "trade",
            {
                "id": oid,
                "order_id": oid,
                "security_id": security_id,
                "side": side,
                "qty": qty,
                "fill_price": "100" if side == "SELL" else "60",
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
    async def fake_resolve(session, *, underlying, spot, option_type, otm_steps=1, strike_step=None, expiry=None):
        strike = 22450 if option_type == "PE" else 22550
        return SimpleNamespace(
            security_id=f"OPT_{option_type}",
            exchange_segment="NSE_FNO",
            strike=Decimal(str(strike)),
        )

    monkeypatch.setattr(strat_mod, "resolve_otm_option", fake_resolve)
    # Inside the trading window (09:30 - 15:10 IST).
    monkeypatch.setattr(strat_mod, "_now_ist", lambda: time(10, 0))

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

    host = StrategyHost(tmp_path, router, _FakeSessionMaker())
    host.set_indicator_engine(engine)
    host.set_market_adapter(None)  # no live feed -> ctx.market is a safe no-op
    host.load_registry()
    await host.start("st_smoke")

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
