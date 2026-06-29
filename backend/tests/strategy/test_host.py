"""Unit tests for StrategyHost dispatch, isolation, and overflow."""
from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pdp.market.bars import BarClosed
from pdp.market.models import Tick
from pdp.strategy.abc import FillEvent, Strategy
from pdp.strategy.context import StrategyContext
from pdp.strategy.host import AlreadyRunning, NotRunning, StrategyHost, StrategyStatus


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
    from datetime import datetime, timezone
    return Tick(
        security_id=security_id,
        exchange_segment="NSE_EQ",
        ltp=Decimal("100.0"),
        ltt=datetime.now(timezone.utc),
    )


def _bar(security_id: str = "1333", timeframe: str = "1m") -> BarClosed:
    from datetime import datetime, timezone
    return BarClosed(
        security_id=security_id,
        timeframe=timeframe,
        bar_time=datetime.now(timezone.utc),
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


# ---------------------------------------------------------------------------
# R1 — Dynamic SID routing (strangle-live-paper-hardening)
# ---------------------------------------------------------------------------

class _SubscribingStrategy(Strategy):
    """Strategy that subscribes to an option SID in on_init."""

    OPT_SID = "OPT_PE_9999"

    async def on_init(self, ctx: StrategyContext) -> None:
        self.received_ticks: list = []
        # Simulate the strangle subscribing an option at runtime.
        # The MarketControl adapter is mocked to return True.
        await ctx.market.subscribe(self.OPT_SID, "NSE_FNO")

    async def on_tick(self, tick) -> None:
        self.received_ticks.append(tick)


def _make_host_with_mock_adapter(strategies_dir: Path) -> StrategyHost:
    from unittest.mock import AsyncMock, MagicMock

    mock_router = MagicMock()
    mock_session_maker = MagicMock()

    # Build a host then wire a mock adapter so subscribe() returns True.
    host = StrategyHost(
        strategies_dir=strategies_dir,
        order_router=mock_router,
        session_maker=mock_session_maker,
    )

    adapter = MagicMock()
    adapter.subscribe = AsyncMock(return_value=True)
    adapter.unsubscribe = AsyncMock()
    host.set_market_adapter(adapter)

    return host


@pytest.mark.asyncio
async def test_dynamic_sid_tick_reaches_strategy(tmp_path):
    """A tick for a runtime-subscribed option SID must reach strategy.on_tick()."""
    yaml_content = (
        "id: dyn\n"
        "class: tests.strategy.test_host._SubscribingStrategy\n"
        "watchlist:\n"
        "  - security_id: '1333'\n"
        "    exchange_segment: NSE_EQ\n"
        "    timeframes: [5m]\n"
    )
    (tmp_path / "dyn.yaml").write_text(yaml_content)

    host = _make_host_with_mock_adapter(tmp_path)
    host.load_registry()
    await host.start("dyn")

    # SID "OPT_PE_9999" is NOT in the static watchlist but was subscribed in on_init.
    opt_tick = _tick(_SubscribingStrategy.OPT_SID)
    host.on_tick(opt_tick)
    await asyncio.sleep(0.05)

    state = host._running["dyn"]
    assert opt_tick in state.instance.received_ticks, (
        "Dynamically-subscribed SID tick must reach strategy.on_tick"
    )
    # Static-watchlist ticks still reach the strategy too.
    static_tick = _tick("1333")
    host.on_tick(static_tick)
    await asyncio.sleep(0.05)
    assert static_tick in state.instance.received_ticks

    await host.stop("dyn")


@pytest.mark.asyncio
async def test_stop_clears_dynamic_sids(tmp_path):
    """Dynamic SID set must be empty after strategy stop."""
    yaml_content = (
        "id: dyn2\n"
        "class: tests.strategy.test_host._SubscribingStrategy\n"
        "watchlist:\n"
        "  - security_id: '1333'\n"
        "    exchange_segment: NSE_EQ\n"
        "    timeframes: [5m]\n"
    )
    (tmp_path / "dyn2.yaml").write_text(yaml_content)

    host = _make_host_with_mock_adapter(tmp_path)
    host.load_registry()
    await host.start("dyn2")

    # Confirm option SID was registered in dynamic set.
    state = host._running["dyn2"]
    assert _SubscribingStrategy.OPT_SID in state.dynamic_sids

    await host.stop("dyn2")

    # After stop: dynamic_sids must be cleared (set is captured before pop).
    assert _SubscribingStrategy.OPT_SID not in state.dynamic_sids
    assert len(state.dynamic_sids) == 0


@pytest.mark.asyncio
async def test_unwatched_non_subscribed_sid_is_not_dispatched(tmp_path):
    """A SID that is neither in the static watchlist nor subscribed must be dropped."""
    yaml_content = (
        "id: dyn3\n"
        "class: tests.strategy.test_host._StubStrategy\n"
        "watchlist:\n"
        "  - security_id: '1333'\n"
        "    exchange_segment: NSE_EQ\n"
        "    timeframes: [5m]\n"
    )
    (tmp_path / "dyn3.yaml").write_text(yaml_content)

    host = _make_host(tmp_path)
    host.load_registry()
    await host.start("dyn3")

    host.on_tick(_tick("RANDOM_SID"))
    await asyncio.sleep(0.05)

    state = host._running["dyn3"]
    assert state.instance.received_ticks == []

    await host.stop("dyn3")
