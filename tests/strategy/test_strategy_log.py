"""Tests for the per-strategy daily log (add-strategy-log capability).

Each test maps to a spec scenario:
  5.1 — config header written once at run start with resolved params + mode
  5.2 — heartbeat fires within trading window, not outside
  5.3 — each action emits a decision line with its reason
  5.4 — file path is logs/<id>/<date>; date rollover opens new file; restart appends
  5.5 — a strategy with no overrides still gets header + common heartbeat + decisions
"""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import pdp.strategy.log as log_mod
from pdp.indicators.supertrend import DOWN, UP, SuperTrendState
from pdp.market.bars import BarClosed
from pdp.strategy.abc import Strategy
from pdp.strategy.log import StrategyDailyLog
from pdp.strategies.supertrend_short import SuperTrendShort

_IST = ZoneInfo("Asia/Kolkata")

# ---------------------------------------------------------------------------
# Shared fakes (reused from test_supertrend_short for consistency)
# ---------------------------------------------------------------------------

class _Orders:
    def __init__(self):
        self.calls: list[dict] = []
        self.price: Decimal = Decimal("100")
        self._pos: dict[str, dict] = {}

    def _p(self, sid):
        return self._pos.setdefault(sid, {"net": 0, "avg": Decimal("0"), "realized": Decimal("0")})

    async def place_order(self, *, security_id, side, qty, **kw):
        self.calls.append({"security_id": security_id, "side": side, "qty": qty})
        p = self._p(security_id)
        signed = qty if side == "BUY" else -qty
        new_qty = p["net"] + signed
        if new_qty == 0:
            p["realized"] += (self.price - p["avg"]) * Decimal(p["net"])
            p["avg"] = Decimal("0")
        elif (p["net"] <= 0 and signed < 0):
            total = p["avg"] * Decimal(abs(p["net"])) + self.price * Decimal(qty)
            p["avg"] = total / Decimal(abs(new_qty))
        p["net"] = new_qty
        return SimpleNamespace(id=len(self.calls), status="OPEN")

    async def cancel_open_entry_orders(self, sid): return []
    async def get_net_qty(self, sid): return self._p(sid)["net"]
    async def get_position(self, sid): p = self._p(sid); return p["net"], p["avg"]
    async def get_realized_pnl(self, sid): return self._p(sid)["realized"]


class _Indicators:
    def __init__(self, state=None):
        self.state = state or SuperTrendState(direction=UP, value=Decimal("0"), flipped=False)
    def supertrend(self, sid, tf): return self.state


class _Market:
    async def subscribe(self, sid, seg): return True
    async def unsubscribe(self, sid, seg): pass
    async def ltp(self, sid): return None


class _SessionMaker:
    def __call__(self): return self
    async def __aenter__(self): return SimpleNamespace()
    async def __aexit__(self, *a): return False


def _ctx(orders, indicators, market):
    import structlog
    return SimpleNamespace(
        orders=orders, indicators=indicators, market=market,
        session_maker=_SessionMaker(),
        log=structlog.get_logger(),
        params={
            "underlying": "NIFTY", "underlying_security_id": "13", "timeframe": "5m",
            "lot_size": 65, "start_lots": 2, "add_lots": 1, "max_lots": 5,
            "start_ist": "09:30", "square_off_ist": "15:10",
            "leg_stop_per_lot": 1000, "day_stop": 10000,
        },
    )


def _bar_ist(hh: int, mm: int, close: float = 22500.0) -> BarClosed:
    return BarClosed(
        security_id="13", timeframe="5m",
        bar_time=datetime(2026, 6, 12, hh, mm, tzinfo=_IST),
        open=Decimal(str(close)), high=Decimal(str(close + 5)),
        low=Decimal(str(close - 5)), close=Decimal(str(close)),
        volume=0, oi=0,
    )


import pdp.strategies.supertrend_short as mod_st


@pytest.fixture
def patched_resolver(monkeypatch):
    async def fake_resolve(session, *, underlying, spot, option_type, **kw):
        return SimpleNamespace(
            security_id=f"OPT_{option_type}", exchange_segment="NSE_FNO",
            strike=Decimal("22450" if option_type == "PE" else "22550"),
        )
    monkeypatch.setattr(mod_st, "resolve_otm_option", fake_resolve)


def _read_records(log_dir, strategy_id: str) -> list[dict]:
    """Read all JSON lines from the strategy's latest log file."""
    today = datetime.now(tz=_IST).date().isoformat()
    path = log_dir / strategy_id / f"{today}.log"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# 5.1 — Config header written once at run start
# ---------------------------------------------------------------------------

def test_config_header_written_at_run_start(tmp_path):
    strat = SuperTrendShort()
    strat.strategy_id = "supertrend_short"
    strat._slog = StrategyDailyLog("supertrend_short", logs_dir=tmp_path)

    strat.log_config_header(
        mode="paper",
        timeframe="5m",
        params={"leg_stop_per_lot": 1000, "day_stop": 10000},
        watchlist=[{"security_id": "13", "exchange_segment": "IDX_I"}],
    )
    strat._slog.close()

    records = _read_records(tmp_path, "supertrend_short")
    assert len(records) == 1
    r = records[0]
    assert r["event"] == "run_start"
    assert r["mode"] == "paper"
    assert r["strategy_id"] == "supertrend_short"
    assert r["params"]["leg_stop_per_lot"] == 1000
    assert r["timeframe"] == "5m"


# ---------------------------------------------------------------------------
# 5.2 — Heartbeat only within the trading window
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_heartbeat_only_within_window(tmp_path, patched_resolver):
    orders, ind, market = _Orders(), _Indicators(), _Market()
    strat = SuperTrendShort()
    strat.strategy_id = "supertrend_short"
    strat._slog = StrategyDailyLog("supertrend_short", logs_dir=tmp_path)
    strat._mode = "paper"
    await strat.on_init(_ctx(orders, ind, market))

    # Bar before window (08:55 IST) — no heartbeat
    await strat.on_bar(_bar_ist(8, 55))
    records = _read_records(tmp_path, "supertrend_short")
    assert not any(r["event"] == "heartbeat" for r in records)

    # Bar inside window (09:35 IST) — heartbeat expected
    await strat.on_bar(_bar_ist(9, 35))
    records = _read_records(tmp_path, "supertrend_short")
    assert any(r["event"] == "heartbeat" for r in records)

    # Done-for-day (squareoff closes position and sets done_for_day).
    await strat.on_bar(_bar_ist(15, 12))  # past squareoff
    n_hb_after_sqoff = sum(1 for r in _read_records(tmp_path, "supertrend_short")
                           if r["event"] == "heartbeat")
    # A bar after squareoff should add no more heartbeats.
    await strat.on_bar(_bar_ist(15, 20))
    n_hb_final = sum(1 for r in _read_records(tmp_path, "supertrend_short")
                     if r["event"] == "heartbeat")
    assert n_hb_final == n_hb_after_sqoff

    strat._slog.close()


# ---------------------------------------------------------------------------
# 5.3 — Each action emits a decision line with its reason
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_decisions_on_open_scale_close(tmp_path, patched_resolver):
    orders, ind, market = _Orders(), _Indicators(), _Market()
    strat = SuperTrendShort()
    strat.strategy_id = "supertrend_short"
    strat._slog = StrategyDailyLog("supertrend_short", logs_dir=tmp_path)
    strat._mode = "paper"
    await strat.on_init(_ctx(orders, ind, market))

    # Open
    await strat.on_bar(_bar_ist(9, 35))
    # Scale
    await strat.on_bar(_bar_ist(9, 40))
    # Flip (close + open opposite)
    ind.state = SuperTrendState(direction=DOWN, value=Decimal("0"), flipped=True)
    await strat.on_bar(_bar_ist(9, 45))
    # Square-off
    await strat.on_bar(_bar_ist(15, 12))

    strat._slog.close()

    decisions = [r for r in _read_records(tmp_path, "supertrend_short")
                 if r["event"] == "decision"]
    actions = [d["action"] for d in decisions]

    assert "open" in actions
    assert "scale" in actions
    assert "flip" in actions
    assert "square_off" in actions

    # Decision lines carry reason and strategy_id
    for d in decisions:
        assert "reason" in d
        assert d["strategy_id"] == "supertrend_short"


# ---------------------------------------------------------------------------
# 5.4 — File path, date rollover, restart appends
# ---------------------------------------------------------------------------

def test_file_path_and_date_rollover(tmp_path, monkeypatch):
    # First date
    monkeypatch.setattr(
        log_mod, "_now_ist",
        lambda: datetime(2026, 6, 12, 10, 0, tzinfo=_IST),
    )
    slog = StrategyDailyLog("supertrend_short", logs_dir=tmp_path)
    slog.write({"event": "day1"})
    assert (tmp_path / "supertrend_short" / "2026-06-12.log").exists()

    # Roll to next day
    monkeypatch.setattr(
        log_mod, "_now_ist",
        lambda: datetime(2026, 6, 13, 10, 0, tzinfo=_IST),
    )
    slog.write({"event": "day2"})
    assert (tmp_path / "supertrend_short" / "2026-06-13.log").exists()
    slog.close()

    # Day-1 file still has only the day1 record
    day1_records = [
        json.loads(l)
        for l in (tmp_path / "supertrend_short" / "2026-06-12.log").read_text().splitlines()
    ]
    assert len(day1_records) == 1 and day1_records[0]["event"] == "day1"


def test_restart_appends(tmp_path, monkeypatch):
    monkeypatch.setattr(
        log_mod, "_now_ist",
        lambda: datetime(2026, 6, 12, 10, 0, tzinfo=_IST),
    )
    # First run
    slog1 = StrategyDailyLog("supertrend_short", logs_dir=tmp_path)
    slog1.write({"event": "first_run"})
    slog1.close()

    # Second run (same day) — should append
    slog2 = StrategyDailyLog("supertrend_short", logs_dir=tmp_path)
    slog2.write({"event": "restart"})
    slog2.close()

    records = [
        json.loads(l)
        for l in (tmp_path / "supertrend_short" / "2026-06-12.log").read_text().splitlines()
    ]
    assert len(records) == 2
    assert records[0]["event"] == "first_run"
    assert records[1]["event"] == "restart"


# ---------------------------------------------------------------------------
# 5.5 — Minimal strategy (no overrides) still gets base logging
# ---------------------------------------------------------------------------

class _MinimalStrategy(Strategy):
    async def on_init(self, ctx) -> None:
        self.ctx = ctx

    async def on_bar(self, bar: BarClosed) -> None:
        self.log_heartbeat(bar.bar_time)
        self.log_decision("test_action", "test_reason", extra="x")


@pytest.mark.asyncio
async def test_minimal_strategy_gets_base_logging(tmp_path):
    strat = _MinimalStrategy()
    strat.strategy_id = "minimal"
    strat._mode = "paper"
    strat._slog = StrategyDailyLog("minimal", logs_dir=tmp_path)

    import structlog
    await strat.on_init(SimpleNamespace(log=structlog.get_logger()))

    strat.log_config_header(
        mode="paper", timeframe="5m", params={"p": 1}, watchlist=[],
    )
    await strat.on_bar(_bar_ist(10, 0))
    strat._slog.close()

    records = _read_records(tmp_path, "minimal")
    events = [r["event"] for r in records]
    assert "run_start" in events
    assert "heartbeat" in events
    assert "decision" in events

    hb = next(r for r in records if r["event"] == "heartbeat")
    assert hb["strategy_id"] == "minimal"
    assert hb["mode"] == "paper"
    assert "ts" in hb
