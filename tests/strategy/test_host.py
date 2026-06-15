"""Unit tests for StrategyHost dispatch, isolation, and overflow."""
from __future__ import annotations

import asyncio
from datetime import UTC
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pdp.market.bars import BarClosed
from pdp.market.models import Tick
from pdp.strategy.abc import FillEvent, Strategy
from pdp.strategy.context import StrategyContext
from pdp.strategy.host import StrategyHost, StrategyStatus

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_host(strategies_dir: Path | None = None) -> StrategyHost:
    mock_router = MagicMock()
    mock_session = MagicMock()
    return StrategyHost(
        strategies_dir=strategies_dir or Path("strategies"),
        order_router=mock_router,
        session_maker=mock_session,
    )


def _tick(security_id: str = "1333") -> Tick:
    from datetime import datetime
    return Tick(
        security_id=security_id,
        exchange_segment="NSE_EQ",
        ltp=Decimal("100.0"),
        ltt=datetime.now(UTC),
    )


def _bar(security_id: str = "1333", timeframe: str = "1m") -> BarClosed:
    from datetime import datetime
    return BarClosed(
        security_id=security_id,
        timeframe=timeframe,
        bar_time=datetime.now(UTC),
        open=Decimal("100"),
        high=Decimal("105"),
        low=Decimal("99"),
        close=Decimal("102"),
        volume=1000,
        oi=0,
    )


class _StubStrategy(Strategy):
    """Minimal strategy that records events."""

    received_ticks: list
    received_bars: list
    received_fills: list

    async def on_init(self, ctx: StrategyContext) -> None:
        self.received_ticks = []
        self.received_bars = []
        self.received_fills = []

    async def on_tick(self, tick: Tick) -> None:
        self.received_ticks.append(tick)

    async def on_bar(self, bar: BarClosed) -> None:
        self.received_bars.append(bar)

    async def on_fill(self, fill: FillEvent) -> None:
        self.received_fills.append(fill)


# ---------------------------------------------------------------------------
# 8.1 — on_tick routing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_tick_enqueues_for_watched_security(tmp_path):
    """Tick for a watched security lands in the strategy's inbox."""
    yaml_content = (
        "id: s1\n"
        "class: tests.strategy.test_host._StubStrategy\n"
        "watchlist:\n"
        "  - security_id: '1333'\n"
        "    exchange_segment: NSE_EQ\n"
        "    timeframes: [1m]\n"
    )
    (tmp_path / "s1.yaml").write_text(yaml_content)

    host = _make_host(tmp_path)
    host.load_registry()
    await host.start("s1")

    tick = _tick("1333")
    host.on_tick(tick)

    # Give the task a moment to process
    await asyncio.sleep(0.05)

    state = host._running["s1"]
    assert state.instance.received_ticks == [tick]

    await host.stop("s1")


@pytest.mark.asyncio
async def test_on_tick_ignores_unwatched_security(tmp_path):
    """Tick for an unwatched security is silently discarded."""
    yaml_content = (
        "id: s1\n"
        "class: tests.strategy.test_host._StubStrategy\n"
        "watchlist:\n"
        "  - security_id: '1333'\n"
        "    exchange_segment: NSE_EQ\n"
        "    timeframes: [1m]\n"
    )
    (tmp_path / "s1.yaml").write_text(yaml_content)

    host = _make_host(tmp_path)
    host.load_registry()
    await host.start("s1")

    host.on_tick(_tick("9999"))  # unwatched
    await asyncio.sleep(0.05)

    state = host._running["s1"]
    assert state.instance.received_ticks == []

    await host.stop("s1")


# ---------------------------------------------------------------------------
# 8.2 — on_bar routing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_bar_routes_matching_timeframe(tmp_path):
    """Bar for watched (security, timeframe) pair is dispatched."""
    yaml_content = (
        "id: s1\n"
        "class: tests.strategy.test_host._StubStrategy\n"
        "watchlist:\n"
        "  - security_id: '1333'\n"
        "    exchange_segment: NSE_EQ\n"
        "    timeframes: [5m]\n"
    )
    (tmp_path / "s1.yaml").write_text(yaml_content)

    host = _make_host(tmp_path)
    host.load_registry()
    await host.start("s1")

    bar = _bar("1333", "5m")
    host.on_bar(bar)
    await asyncio.sleep(0.05)

    state = host._running["s1"]
    assert state.instance.received_bars == [bar]

    await host.stop("s1")


@pytest.mark.asyncio
async def test_on_bar_filters_wrong_timeframe(tmp_path):
    """Bar for watched security but wrong timeframe is NOT dispatched."""
    yaml_content = (
        "id: s1\n"
        "class: tests.strategy.test_host._StubStrategy\n"
        "watchlist:\n"
        "  - security_id: '1333'\n"
        "    exchange_segment: NSE_EQ\n"
        "    timeframes: [1m]\n"
    )
    (tmp_path / "s1.yaml").write_text(yaml_content)

    host = _make_host(tmp_path)
    host.load_registry()
    await host.start("s1")

    host.on_bar(_bar("1333", "5m"))  # 5m not watched
    await asyncio.sleep(0.05)

    state = host._running["s1"]
    assert state.instance.received_bars == []

    await host.stop("s1")


# ---------------------------------------------------------------------------
# 8.3 — Inbox overflow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_inbox_overflow_increments_counter_not_raises(tmp_path):
    """Full inbox increments dropped_ticks and does not raise."""
    yaml_content = (
        "id: s1\n"
        "class: tests.strategy.test_host._StubStrategy\n"
        "watchlist:\n"
        "  - security_id: '1333'\n"
        "    exchange_segment: NSE_EQ\n"
        "    timeframes: [1m]\n"
    )
    (tmp_path / "s1.yaml").write_text(yaml_content)

    host = _make_host(tmp_path)
    host.load_registry()
    await host.start("s1")

    state = host._running["s1"]
    # Fill the inbox to capacity by direct queue manipulation
    for _ in range(state.inbox.maxsize):
        state.inbox.put_nowait(MagicMock())

    # This should drop without raising
    tick = _tick("1333")
    host.on_tick(tick)  # inbox is full — should drop

    assert state.dropped_ticks == 1

    # Drain and stop
    state.task.cancel()
    try:
        await state.task
    except asyncio.CancelledError:
        pass
    host._running.pop("s1", None)


# ---------------------------------------------------------------------------
# 8.4 — Crash containment
# ---------------------------------------------------------------------------

class _CrashingStrategy(Strategy):
    """Strategy that raises on every bar — for crash containment tests."""

    async def on_init(self, ctx: StrategyContext) -> None:
        pass

    async def on_bar(self, bar: BarClosed) -> None:
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_crash_sets_status_without_affecting_other_strategies(tmp_path):
    """Unhandled exception in on_bar sets CRASHED; other strategies keep running."""
    yaml_stable = (
        "id: stable\n"
        "class: tests.strategy.test_host._StubStrategy\n"
        "watchlist:\n"
        "  - security_id: '1333'\n"
        "    exchange_segment: NSE_EQ\n"
        "    timeframes: [1m]\n"
    )
    (tmp_path / "stable.yaml").write_text(yaml_stable)

    host = _make_host(tmp_path)
    host.load_registry()
    await host.start("stable")

    # Manually inject the crashing strategy
    from pdp.strategy.host import _StrategyState
    from pdp.strategy.registry import StrategyConfig, WatchlistEntry

    crash_cfg = StrategyConfig(
        id="crash",
        cls="not.used",
        watchlist=[WatchlistEntry(security_id="1333", exchange_segment="NSE_EQ", timeframes=["1m"])],
    )
    crash_instance = _CrashingStrategy()
    crash_instance.strategy_id = "crash"
    crash_instance.params = {}
    await crash_instance.on_init(MagicMock())

    inbox: asyncio.Queue = asyncio.Queue(maxsize=10)
    task = asyncio.create_task(
        host._run_strategy("crash", crash_instance, inbox),
        name="strategy-crash",
    )
    host._running["crash"] = _StrategyState(
        config=crash_cfg,
        instance=crash_instance,
        inbox=inbox,
        task=task,
    )

    host.on_bar(_bar("1333", "1m"))
    await asyncio.sleep(0.1)

    assert host._running["crash"].status == StrategyStatus.CRASHED
    assert "stable" in host._running
    assert host._running["stable"].status == StrategyStatus.RUNNING

    await host.stop("stable")
