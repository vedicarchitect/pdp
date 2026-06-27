"""EventService — orchestrates detectors, position sync, dedup, persistence, delivery."""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, cast

import structlog

from pdp.events.config import EventConfig
from pdp.events.detectors.base import BarContext
from pdp.events.detectors.levels import LevelDetectors
from pdp.events.detectors.oi_greeks import OIGreeksDetectors
from pdp.events.detectors.portfolio import PortfolioDetectors
from pdp.events.detectors.position import PositionDetectors
from pdp.events.detectors.range_volume import RangeVolumeDetectors
from pdp.events.detectors.trend import TrendDetectors
from pdp.events.models import Event, EventType, Severity
from pdp.events.positions import PositionSync
from pdp.options.dhan_client import UNDERLYING_MAP

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorDatabase
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from pdp.events.hub import EventsHub
    from pdp.events.push import WebPushSender
    from pdp.events.store import EventStore
    from pdp.indicators.engine import IndicatorEngine
    from pdp.market.bars import BarClosed
    from pdp.market.dhan_ws import DhanTickerAdapter
    from pdp.settings import Settings

log = structlog.get_logger()

_SPOT_SID_TO_NAME = {str(sid): name for name, (sid, _seg) in UNDERLYING_MAP.items()}


class EventService:
    def __init__(
        self,
        *,
        settings: Settings,
        engine: IndicatorEngine | None,
        hub: EventsHub,
        store: EventStore,
        push_sender: WebPushSender | None,
        session_maker: async_sessionmaker[AsyncSession],
        adapter: DhanTickerAdapter | None = None,
        portfolio_service: Any = None,
        journal_service: Any = None,
        mongo_db: AsyncIOMotorDatabase | None = None,  # type: ignore[type-arg]
    ) -> None:
        self._settings = settings
        self._engine = engine
        self._hub = hub
        self._store = store
        self._push = push_sender
        self._portfolio = portfolio_service
        self._journal = journal_service
        self.cfg = EventConfig.from_settings(settings)

        self._trend = TrendDetectors()
        self._levels = LevelDetectors()
        self._range = RangeVolumeDetectors()
        self._position = PositionDetectors()
        self._oi = OIGreeksDetectors()
        self._portfolio_det = PortfolioDetectors()
        self._sync = PositionSync(
            settings, session_maker, adapter, self.emit, self.cfg.position_sync_seconds,
        )

        self._ltp: dict[str, float] = {}
        self._last_emit: dict[str, float] = {}
        self._store_q: asyncio.Queue[Event] = asyncio.Queue(maxsize=2000)
        self._push_q: asyncio.Queue[Event] = asyncio.Queue(maxsize=1000)
        self._tasks: list[asyncio.Task[None]] = []
        self._stop = asyncio.Event()
        self._min_rank = Severity(self.cfg.push_min_severity).rank

    # ── lifecycle ─────────────────────────────────────────────────────────────
    async def start(self) -> None:
        if not self.cfg.enabled:
            log.info("event_service_disabled")
            return
        self._tasks = [
            asyncio.create_task(self._run_store_worker(), name="events-store"),
            asyncio.create_task(self._run_push_worker(), name="events-push"),
            asyncio.create_task(self._run_position_checks(), name="events-position-checks"),
            asyncio.create_task(self._run_stats(), name="events-stats"),
        ]
        await self._sync.start()
        log.info("event_service_started", timeframes=self.cfg.timeframes)

    async def stop(self) -> None:
        self._stop.set()
        await self._sync.stop()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        log.info("event_service_stopped")

    # ── emit (dedup gate → delivery) ──────────────────────────────────────────
    def emit(self, event: Event) -> None:
        key = event.dedup_key or f"{event.event_type.value}:{event.security_id}"
        now = time.monotonic()
        last = self._last_emit.get(key)
        if last is not None and now - last < self.cfg.cooldown_seconds:
            return
        self._last_emit[key] = now
        self._hub.publish(event)
        _drop_put(self._store_q, event)
        if (self.cfg.push_enabled
                and event.severity.rank >= self._min_rank
                and event.event_type.value not in self.cfg.push_disabled_types):
            _drop_put(self._push_q, event)
        log.debug("event_emitted", type=event.event_type.value, sev=event.severity.value,
                  sid=event.security_id, tf=event.timeframe)

    def _emit_all(self, events: list[Event]) -> None:
        for e in events:
            self.emit(e)

    # ── hot-path hooks ────────────────────────────────────────────────────────
    def on_tick(self, security_id: str, ltp: float) -> None:
        if not self.cfg.enabled:
            return
        self._ltp[security_id] = ltp  # O(1) cache; detectors run on a timer

    def on_bar(self, bar: BarClosed, snapshot: Any = None) -> None:
        if not self.cfg.enabled or bar.timeframe not in self.cfg.timeframes:
            return
        sid = bar.security_id
        underlying = _SPOT_SID_TO_NAME.get(sid)
        eng = self._engine
        snap = snapshot if snapshot is not None else (
            eng.get_snapshot(sid, bar.timeframe) if eng is not None else None)
        st = eng.get(sid, bar.timeframe) if eng is not None else None
        ml = eng.get_ml_signal(sid, bar.timeframe) if eng is not None else None
        walls = self._oi.walls(underlying) if underlying else []
        ctx = BarContext(
            security_id=sid, underlying=underlying, timeframe=bar.timeframe,
            open=float(bar.open), high=float(bar.high), low=float(bar.low),
            close=float(bar.close), volume=float(bar.volume), bar_time=bar.bar_time,
            snapshot=snap, supertrend=st, ml_signal=ml, cfg=self.cfg, oi_levels=walls,
        )
        try:
            self._emit_all(self._trend.evaluate(ctx))
            self._emit_all(self._levels.evaluate(ctx))
            self._emit_all(self._range.evaluate(ctx))
            if underlying:
                positions = self._sync.for_underlying(underlying)
                if positions:
                    self._emit_all(self._position.evaluate_bar(ctx, positions))
        except Exception as exc:  # never break the tick router
            log.warning("event_on_bar_error", sid=sid, tf=bar.timeframe, exc=str(exc))

    # ── system event hooks (wired from main.py) ───────────────────────────
    def on_order_fill(self, payload: dict[str, Any]) -> None:
        """Called by OrdersHub fill callback. Emits ORDER_FILL (sync, no I/O)."""
        if not self.cfg.enabled:
            return
        side = payload.get("side", "")
        qty = payload.get("qty", 0)
        price = payload.get("fill_price", 0)
        symbol = payload.get("security_id", "")
        strategy_id = payload.get("strategy_id", "")
        self.emit(Event(
            event_type=EventType.ORDER_FILL,
            severity=Severity.INFO,
            security_id=symbol,
            title="Order Filled",
            message=f"{side} {qty} @ {price}" + (f" [{strategy_id}]" if strategy_id else ""),
            payload=payload,
            dedup_key=f"ORDER_FILL:{payload.get('order_id', symbol)}",
        ))

    def emit_kill_switch(self, trigger: str = "") -> None:
        """Called when the kill switch fires. Severity = CRITICAL."""
        self.emit(Event(
            event_type=EventType.KILL_SWITCH_TRIGGERED,
            severity=Severity.CRITICAL,
            security_id="PORTFOLIO",
            title="Kill Switch Triggered",
            message=f"All positions closed. Trigger: {trigger or 'hard_cap'}",
            dedup_key="KILL_SWITCH_TRIGGERED",
        ))

    def emit_margin_warning(self, daily_loss: float, cap: float) -> None:
        """Called when daily P&L reaches RISK_SOFT_CAP_PCT of the daily loss cap."""
        pct = (daily_loss / cap * 100) if cap > 0 else 0.0
        self.emit(Event(
            event_type=EventType.MARGIN_WARNING,
            severity=Severity.WARNING,
            security_id="PORTFOLIO",
            title="Margin Warning",
            message=f"Daily loss ₹{daily_loss:,.0f} is {pct:.0f}% of cap ₹{cap:,.0f}",
            payload={"daily_loss": daily_loss, "cap": cap, "pct": pct},
            dedup_key="MARGIN_WARNING",
        ))

    def emit_strategy_signal(
        self, strategy_id: str, security_id: str, signal: str, underlying: str | None = None
    ) -> None:
        """Called from StrategyHost when a strategy generates an entry/exit signal."""
        self.emit(Event(
            event_type=EventType.STRATEGY_SIGNAL,
            severity=Severity.INFO,
            security_id=security_id,
            underlying=underlying,
            title=f"Strategy Signal: {strategy_id}",
            message=signal,
            dedup_key=f"STRATEGY_SIGNAL:{strategy_id}:{signal[:20]}",
        ))

    def on_chain(self, underlying: str, doc: dict[str, Any]) -> None:
        if not self.cfg.enabled:
            return
        try:
            positions = self._sync.get_positions()
            self._emit_all(self._oi.evaluate(doc, positions, self.cfg))
        except Exception as exc:
            log.warning("event_on_chain_error", underlying=underlying, exc=str(exc))

    # ── background workers ────────────────────────────────────────────────────
    def _ltp_of(self, security_id: str) -> float | None:
        return self._ltp.get(security_id)

    def _spot_of(self, underlying: str) -> float | None:
        spot = UNDERLYING_MAP.get(underlying.upper())
        return self._ltp.get(str(spot[0])) if spot else None

    async def _run_position_checks(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=2.0)
            except TimeoutError:
                pass
            if self._stop.is_set():
                break
            try:
                positions = self._sync.get_positions()
                if positions:
                    self._emit_all(self._position.evaluate_tick(
                        positions, self._ltp_of, self._spot_of, self.cfg))
            except Exception as exc:
                log.warning("event_position_check_error", exc=str(exc))

    async def _run_stats(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=float(self.cfg.stats_interval_seconds))
            except TimeoutError:
                pass
            if self._stop.is_set():
                break
            try:
                stats = await self._gather_stats()
                if stats:
                    self.emit(self._portfolio_det.build_stats(stats))
            except Exception as exc:
                log.warning("event_stats_error", exc=str(exc))

    async def _gather_stats(self) -> dict[str, Any]:
        stats: dict[str, Any] = {}
        ps = self._portfolio
        if ps is not None:
            try:
                snap = ps.get_snapshot()
                realized = sum(float(p.get("realized_pnl", 0) or 0) for p in snap)
                unrealized = sum(float(p.get("unrealized_pnl", 0) or 0) for p in snap)
                stats.update(
                    total_realized_pnl=realized,
                    total_unrealized_pnl=unrealized,
                    day_pnl=realized + unrealized,
                    open_positions=sum(1 for p in snap if p.get("net_qty")),
                )
            except Exception:  # noqa: S110
                pass
        js = self._journal
        if js is not None:
            import inspect
            for attr in ("get_today_stats", "today_stats", "get_daily_stats"):
                fn = getattr(js, attr, None)
                if fn is None:
                    continue
                try:
                    raw: Any = await fn() if inspect.iscoroutinefunction(fn) else fn()
                    if isinstance(raw, dict):
                        d = cast("dict[str, Any]", raw)
                        stats.setdefault("num_trades", d.get("num_trades") or d.get("trades"))
                        stats.setdefault("premium_received", d.get("premium_received"))
                    break
                except Exception:  # noqa: S112
                    continue
        return stats

    async def _run_store_worker(self) -> None:
        while not self._stop.is_set():
            try:
                event = await asyncio.wait_for(self._store_q.get(), timeout=1.0)
            except TimeoutError:
                continue
            await self._store.insert(event)

    async def _run_push_worker(self) -> None:
        while not self._stop.is_set():
            try:
                event = await asyncio.wait_for(self._push_q.get(), timeout=1.0)
            except TimeoutError:
                continue
            if self._push is not None:
                await self._push.send(event)


def _drop_put(q: asyncio.Queue[Event], event: Event) -> None:
    if q.full():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
    try:
        q.put_nowait(event)
    except asyncio.QueueFull:
        pass
