from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from pdp.settings import get_settings
from pdp.strategy.abc import FillEvent, Strategy
from pdp.strategy.context import (
    IndicatorReader,
    MarketControl,
    StrategyContext,
    StrategyOrderClient,
)
from pdp.strategy.log import StrategyDailyLog
from pdp.strategy.registry import StrategyConfig, import_strategy_class, load_all, load_one

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from pdp.indicators.engine import IndicatorEngine
    from pdp.market.bars import BarClosed
    from pdp.market.dhan_ws import DhanTickerAdapter
    from pdp.market.models import Tick
    from pdp.orders.router import OrderRouter
    from pdp.orders.ws import OrdersHub

log = structlog.get_logger()

_INBOX_SIZE = 1000
_LAGGING_LOG_EVERY = 100  # log strategy_lagging every N consecutive drops


class StrategyStatus(StrEnum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    CRASHED = "CRASHED"


# ---------------------------------------------------------------------------
# Internal event envelope types
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class _TickEvent:
    tick: Tick


@dataclass(slots=True)
class _BarEvent:
    bar: BarClosed


@dataclass(slots=True)
class _FillEvent:
    fill: FillEvent


_Event = _TickEvent | _BarEvent | _FillEvent


# ---------------------------------------------------------------------------
# Per-strategy runtime state
# ---------------------------------------------------------------------------

@dataclass
class _StrategyState:
    config: StrategyConfig
    instance: Strategy
    inbox: asyncio.Queue[_Event]
    task: asyncio.Task[None]
    status: StrategyStatus = StrategyStatus.RUNNING
    dropped_ticks: int = 0
    _drop_streak: int = field(default=0, repr=False)


# ---------------------------------------------------------------------------
# StrategyHost
# ---------------------------------------------------------------------------

class StrategyHost:
    """Manages strategy lifecycle, event dispatch, and fill routing."""

    def __init__(
        self,
        strategies_dir: Path,
        order_router: OrderRouter,
        session_maker: async_sessionmaker[Any],
    ) -> None:
        self._strategies_dir = strategies_dir
        self._order_router = order_router
        self._session_maker = session_maker
        self._configs: dict[str, StrategyConfig] = {}
        self._running: dict[str, _StrategyState] = {}
        self._indicator_engine: IndicatorEngine | None = None
        self._market_adapter: DhanTickerAdapter | None = None
        self._redis: Redis | None = None

    def set_indicator_engine(self, engine: IndicatorEngine | None) -> None:
        """Wire the universal indicator engine read by strategies via ctx.indicators."""
        self._indicator_engine = engine

    def set_market_adapter(self, adapter: DhanTickerAdapter | None) -> None:
        """Wire the live feed adapter so strategies can subscribe via ctx.market."""
        self._market_adapter = adapter

    def set_redis(self, redis: Redis | None) -> None:
        """Wire the Redis hot cache so strategies can read LTP via ctx.market.ltp."""
        self._redis = redis

    # ------------------------------------------------------------------ #
    # Registry                                                             #
    # ------------------------------------------------------------------ #

    def load_registry(self) -> None:
        """Populate configs from all *.yaml files in strategies_dir."""
        for cfg in load_all(self._strategies_dir):
            self._configs[cfg.id] = cfg
        log.info("strategy_registry_loaded", count=len(self._configs))

    def list_all(self) -> list[dict[str, Any]]:
        """Return a summary list for the REST /strategies endpoint."""
        result = []
        all_ids = set(self._configs) | set(self._running)
        for sid in sorted(all_ids):
            state = self._running.get(sid)
            cfg = self._configs.get(sid) or (state.config if state else None)
            result.append(
                {
                    "id": sid,
                    "status": state.status if state else StrategyStatus.STOPPED,
                    "dropped_ticks": state.dropped_ticks if state else 0,
                    "watchlist": [w.model_dump() for w in cfg.watchlist] if cfg else [],
                }
            )
        return result

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def start(self, strategy_id: str) -> None:
        """Load YAML, import class, start asyncio task.  Re-reads YAML each call."""
        if strategy_id in self._running:
            raise AlreadyRunning(strategy_id)

        # Re-read YAML each start call (hot-reload)
        cfg = load_one(strategy_id, self._strategies_dir)
        self._configs[strategy_id] = cfg

        cls = import_strategy_class(cfg.cls)
        instance: Strategy = cls()
        instance.strategy_id = cfg.id
        instance.params = dict(cfg.params)
        instance._mode = "live" if get_settings().LIVE else "paper"
        instance._slog = StrategyDailyLog(cfg.id)

        order_client = StrategyOrderClient(
            strategy_id=cfg.id,
            order_router=self._order_router,
            session_maker=self._session_maker,
            max_open_orders=cfg.risk.max_open_orders,
            max_daily_loss_inr=cfg.risk.max_daily_loss_inr,
        )
        ctx = StrategyContext(
            orders=order_client,
            params=dict(cfg.params),
            watchlist=list(cfg.watchlist),
            log=log.bind(strategy_id=cfg.id),
            indicators=IndicatorReader(self._indicator_engine),
            market=MarketControl(self._market_adapter, self._session_maker, self._redis),
            session_maker=self._session_maker,
        )

        inbox: asyncio.Queue[_Event] = asyncio.Queue(maxsize=_INBOX_SIZE)
        await instance.on_init(ctx)

        # Emit the run-start config header as the first lines of the day's log.
        _tfs = sorted({tf for w in cfg.watchlist for tf in w.timeframes})
        instance.log_config_header(
            mode=instance._mode,
            timeframe=", ".join(_tfs) or "unknown",
            params=dict(cfg.params),
            watchlist=[w.model_dump() for w in cfg.watchlist],
        )

        task = asyncio.create_task(
            self._run_strategy(strategy_id, instance, inbox),
            name=f"strategy-{strategy_id}",
        )
        self._running[strategy_id] = _StrategyState(
            config=cfg,
            instance=instance,
            inbox=inbox,
            task=task,
        )
        log.info("strategy_started", strategy_id=strategy_id)

    async def stop(self, strategy_id: str) -> None:
        """Signal shutdown, await on_shutdown, cancel task."""
        if strategy_id not in self._running:
            raise NotRunning(strategy_id)

        state = self._running.pop(strategy_id)
        try:
            await state.instance.on_shutdown()
        except Exception as exc:
            log.warning("strategy_shutdown_error", strategy_id=strategy_id, exc=str(exc))

        state.task.cancel()
        try:
            await state.task
        except asyncio.CancelledError:
            pass

        if state.instance._slog is not None:
            state.instance._slog.close()

        log.info("strategy_stopped", strategy_id=strategy_id)

    # ------------------------------------------------------------------ #
    # Event dispatch (called synchronously from TickRouter hot path)       #
    # ------------------------------------------------------------------ #

    def on_tick(self, tick: Tick) -> None:
        sid = tick.security_id
        for state in self._running.values():
            if not _watches_security(state.config, sid):
                continue
            self._enqueue(state, _TickEvent(tick))

    def on_bar(self, bar: BarClosed) -> None:
        for state in self._running.values():
            if not _watches_bar(state.config, bar.security_id, bar.timeframe):
                continue
            self._enqueue(state, _BarEvent(bar))

    # ------------------------------------------------------------------ #
    # Fill routing                                                         #
    # ------------------------------------------------------------------ #

    def subscribe_fill_events(self, orders_hub: OrdersHub) -> None:
        orders_hub.register_fill_callback(self._on_fill_event)

    def _on_fill_event(self, payload: dict[str, Any]) -> None:
        strategy_id = payload.get("strategy_id")
        if not strategy_id or strategy_id not in self._running:
            return
        fill = FillEvent(
            order_id=payload["order_id"],
            security_id=payload["security_id"],
            exchange_segment=payload.get("exchange_segment", ""),
            side=payload["side"],
            qty=payload["qty"],
            fill_price=_dec(payload["fill_price"]),
            charges=_dec(payload.get("charges", "0")),
            filled_at=payload["filled_at"],
            strategy_id=strategy_id,
        )
        self._enqueue(self._running[strategy_id], _FillEvent(fill))

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _enqueue(self, state: _StrategyState, event: _Event) -> None:
        try:
            state.inbox.put_nowait(event)
            state._drop_streak = 0
        except asyncio.QueueFull:
            state.dropped_ticks += 1
            state._drop_streak += 1
            if state._drop_streak % _LAGGING_LOG_EVERY == 1:
                log.warning(
                    "strategy_lagging",
                    strategy_id=state.config.id,
                    dropped_count=state.dropped_ticks,
                )

    async def _run_strategy(
        self,
        strategy_id: str,
        instance: Strategy,
        inbox: asyncio.Queue[_Event],
    ) -> None:
        while True:
            try:
                event = await inbox.get()
            except asyncio.CancelledError:
                break
            try:
                await _dispatch(instance, event)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error(
                    "strategy_crashed",
                    strategy_id=strategy_id,
                    exc=str(exc),
                    exc_type=type(exc).__name__,
                )
                if strategy_id in self._running:
                    self._running[strategy_id].status = StrategyStatus.CRASHED
                break


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _watches_security(cfg: StrategyConfig, security_id: str) -> bool:
    return any(w.security_id == security_id for w in cfg.watchlist)


def _watches_bar(cfg: StrategyConfig, security_id: str, timeframe: str) -> bool:
    return any(
        w.security_id == security_id and timeframe in w.timeframes
        for w in cfg.watchlist
    )


async def _dispatch(instance: Strategy, event: _Event) -> None:
    if isinstance(event, _TickEvent):
        await instance.on_tick(event.tick)
    elif isinstance(event, _BarEvent):
        await instance.on_bar(event.bar)
    elif isinstance(event, _FillEvent):
        await instance.on_fill(event.fill)


def _dec(v: Any):  # type: ignore[return]
    from decimal import Decimal
    return Decimal(str(v))


# ---------------------------------------------------------------------------
# Sentinel exceptions
# ---------------------------------------------------------------------------

class AlreadyRunning(Exception):
    def __init__(self, strategy_id: str) -> None:
        super().__init__(f"strategy {strategy_id!r} is already running")
        self.strategy_id = strategy_id


class NotRunning(Exception):
    def __init__(self, strategy_id: str) -> None:
        super().__init__(f"strategy {strategy_id!r} is not running")
        self.strategy_id = strategy_id
