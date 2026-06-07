"""Real-time portfolio MTM service.

Maintains an in-memory position cache, recomputes unrealized P&L on each
Redis tick, flushes dirty values back to PG, and writes an EOD snapshot to
MongoDB at 15:36 IST.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from pdp.orders.models import Position
from pdp.portfolio.hub import PortfolioHub
from pdp.portfolio.models import PositionState

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from pdp.orders.ws import OrdersHub
    from pdp.settings import Settings

log = structlog.get_logger()

_IST = ZoneInfo("Asia/Kolkata")


def _ist_now() -> datetime:
    return datetime.now(_IST)


def _round4(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.0001"))


class PortfolioService:
    def __init__(
        self,
        redis,  # type: ignore[no-untyped-def]
        engine: AsyncEngine,
        hub: PortfolioHub,
        settings: Settings,
        mongo_db=None,  # type: ignore[no-untyped-def]
    ) -> None:
        self._redis = redis
        self._engine = engine
        self._hub = hub
        self._settings = settings
        self._mongo_db = mongo_db
        self._cache: dict[tuple[str, str, str], PositionState] = {}
        self._dirty: set[tuple[str, str, str]] = set()
        self._subscribed_sids: set[str] = set()
        self._stop_event = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []
        self._day_start_pnl: Decimal = Decimal("0")
        self._hard_cap_cb: Any = None
        self._hard_cap_inr: Decimal = Decimal("0")
        self._hard_cap_triggered: bool = False  # prevent repeated triggers

    # ------------------------------------------------------------------ #
    # Risk cap integration                                                #
    # ------------------------------------------------------------------ #

    def set_hard_cap_callback(
        self,
        callback: "Callable[[], Awaitable[None]]",
        daily_loss_cap_inr: float,
    ) -> None:
        """Wire the hard-cap breach callback (auto-invoked when daily loss exceeds cap)."""
        self._hard_cap_cb = callback
        self._hard_cap_inr = Decimal(str(daily_loss_cap_inr))
        self._hard_cap_triggered = False

    def get_daily_loss(self) -> Decimal:
        """Current session loss (positive = net loss since day start)."""
        current_pnl = sum(
            (ps.realized_pnl + ps.unrealized_pnl) for ps in self._cache.values()
        )
        return max(Decimal("0"), self._day_start_pnl - current_pnl)

    def _build_summary(self) -> dict:
        total_realized = sum(ps.realized_pnl for ps in self._cache.values())
        total_unrealized = sum(ps.unrealized_pnl for ps in self._cache.values())
        current_pnl = total_realized + total_unrealized
        return {
            "total_realized_pnl": float(total_realized),
            "total_unrealized_pnl": float(total_unrealized),
            "day_pnl": float(current_pnl - self._day_start_pnl),
            "realized_loss_today": float(max(Decimal("0"), self._day_start_pnl - current_pnl)),
            "open_positions": sum(1 for ps in self._cache.values() if ps.net_qty != 0),
        }

    def _reset_day_start_pnl(self) -> None:
        current_pnl = sum(
            (ps.realized_pnl + ps.unrealized_pnl) for ps in self._cache.values()
        )
        self._day_start_pnl = current_pnl
        self._hard_cap_triggered = False
        log.info("portfolio_day_start_reset", day_start_pnl=str(self._day_start_pnl))

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        async with AsyncSession(self._engine) as session:
            await self._load_positions(session)
        self._reset_day_start_pnl()
        self._tasks = [
            asyncio.create_task(self._run_tick_listener(), name="portfolio-tick"),
            asyncio.create_task(self._run_flush(), name="portfolio-flush"),
            asyncio.create_task(self._run_eod_snapshot(), name="portfolio-eod"),
            asyncio.create_task(self._run_loss_reset(), name="portfolio-loss-reset"),
            asyncio.create_task(self._run_periodic_broadcast(), name="portfolio-periodic-broadcast"),
        ]
        log.info("portfolio_service_started", positions=len(self._cache))

    async def stop(self) -> None:
        self._stop_event.set()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        log.info("portfolio_service_stopped")

    def subscribe_fill_events(self, orders_hub: OrdersHub) -> None:
        """Register a callback so fill events are acknowledged (reload happens in flush loop)."""
        orders_hub.register_position_callback(self._on_position_event)

    def _on_position_event(self, payload: dict[str, Any]) -> None:
        pass  # positions reload on every flush cycle; callback keeps the hook wired

    # ------------------------------------------------------------------ #
    # Position cache                                                       #
    # ------------------------------------------------------------------ #

    async def _load_positions(self, session: AsyncSession) -> None:
        result = await session.execute(select(Position))
        positions = result.scalars().all()
        self._cache.clear()
        for pos in positions:
            key = (pos.security_id, pos.exchange_segment, pos.product)
            self._cache[key] = PositionState(
                security_id=pos.security_id,
                exchange_segment=pos.exchange_segment,
                product=pos.product,
                net_qty=pos.net_qty,
                avg_price=pos.avg_price,
                realized_pnl=pos.realized_pnl,
                unrealized_pnl=pos.unrealized_pnl,
                updated_at=pos.updated_at,
            )
        self._subscribed_sids = {ps.security_id for ps in self._cache.values() if ps.net_qty != 0}

    def get_snapshot(self) -> list[dict]:
        return [ps.to_dict() for ps in self._cache.values()]

    # ------------------------------------------------------------------ #
    # Tick listener                                                        #
    # ------------------------------------------------------------------ #

    async def _run_tick_listener(self) -> None:
        pubsub = self._redis.pubsub()
        try:
            if self._subscribed_sids:
                await pubsub.subscribe(*(f"tick.{sid}" for sid in self._subscribed_sids))

            while not self._stop_event.is_set():
                # Sync subscriptions with current cache
                current_sids = {ps.security_id for ps in self._cache.values() if ps.net_qty != 0}
                new_sids = current_sids - self._subscribed_sids
                if new_sids:
                    await pubsub.subscribe(*(f"tick.{sid}" for sid in new_sids))
                    self._subscribed_sids |= new_sids
                gone_sids = self._subscribed_sids - current_sids
                if gone_sids:
                    await pubsub.unsubscribe(*(f"tick.{sid}" for sid in gone_sids))
                    self._subscribed_sids -= gone_sids

                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=0.5
                )
                if message is None or message.get("type") != "message":
                    continue

                try:
                    data = json.loads(message["data"])
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue

                self._handle_tick(data)

        except asyncio.CancelledError:
            pass
        finally:
            try:
                await pubsub.unsubscribe()
                await pubsub.aclose()
            except Exception as exc:
                log.warning("portfolio_pubsub_close_error", exc=str(exc))

    def _handle_tick(self, data: dict[str, Any]) -> None:
        sid = data.get("security_id", "")
        ltp_str = data.get("ltp")
        if not sid or not ltp_str:
            return
        try:
            ltp = Decimal(str(ltp_str))
        except Exception:
            return

        changed = False
        for key, ps in self._cache.items():
            if ps.security_id == sid and ps.net_qty != 0:
                ps.unrealized_pnl = _round4(Decimal(str(ps.net_qty)) * (ltp - ps.avg_price))
                ps.ltp_stale = False
                ps.updated_at = datetime.now(UTC)
                self._dirty.add(key)
                changed = True

        if changed:
            self._hub.broadcast(self.get_snapshot(), self._build_summary())

    # ------------------------------------------------------------------ #
    # Periodic flush + reload                                              #
    # ------------------------------------------------------------------ #

    async def _run_flush(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._stop_event.wait()),
                    timeout=float(self._settings.PORTFOLIO_MTM_INTERVAL_SECONDS),
                )
            except TimeoutError:
                pass

            if self._stop_event.is_set():
                break

            await self._flush_dirty()

            async with AsyncSession(self._engine) as session:
                await self._load_positions(session)
            await self._check_ltp_stale()
            await self._check_hard_cap()

    async def _flush_dirty(self) -> None:
        if not self._dirty:
            return
        dirty_keys = list(self._dirty)
        self._dirty.clear()
        try:
            async with AsyncSession(self._engine) as session:
                now = datetime.now(UTC)
                for key in dirty_keys:
                    ps = self._cache.get(key)
                    if ps is None:
                        continue
                    await session.execute(
                        update(Position)
                        .where(
                            Position.security_id == ps.security_id,
                            Position.exchange_segment == ps.exchange_segment,
                            Position.product == ps.product,
                        )
                        .values(unrealized_pnl=ps.unrealized_pnl, updated_at=now)
                    )
                await session.commit()
        except Exception as exc:
            log.warning("portfolio_flush_error", error=str(exc))
            self._dirty.update(dirty_keys)

    async def _check_ltp_stale(self) -> None:
        """Mark positions ltp_stale=True when the Redis LTP key has expired."""
        for ps in self._cache.values():
            if ps.net_qty == 0:
                continue
            try:
                val = await self._redis.get(f"ltp:{ps.security_id}")
            except Exception as exc:
                log.warning("portfolio_ltp_stale_check_error", sid=ps.security_id, exc=str(exc))
                continue
            if val is None:
                ps.ltp_stale = True

    # ------------------------------------------------------------------ #
    # EOD snapshot                                                         #
    # ------------------------------------------------------------------ #

    async def _run_eod_snapshot(self) -> None:
        if not self._settings.PORTFOLIO_EOD_SNAPSHOT or self._mongo_db is None:
            return

        last_snapshot_date: date | None = None

        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._stop_event.wait()),
                    timeout=60.0,
                )
            except TimeoutError:
                pass

            if self._stop_event.is_set():
                break

            now_ist = _ist_now()
            today = now_ist.date()
            if now_ist.hour == 15 and now_ist.minute == 36 and last_snapshot_date != today:
                await self._write_eod_snapshot(today)
                last_snapshot_date = today

    async def _write_eod_snapshot(self, snapshot_date: date) -> None:
        try:
            positions = self.get_snapshot()
            total_unrealized = sum(Decimal(p["unrealized_pnl"]) for p in positions)
            total_realized = sum(Decimal(p["realized_pnl"]) for p in positions)
            open_count = sum(1 for ps in self._cache.values() if ps.net_qty != 0)
            doc = {
                "snapshot_date": snapshot_date.isoformat(),
                "snapshot_ts": datetime.now(UTC),
                "mode": "live" if self._settings.LIVE else "paper",
                "positions": positions,
                "summary": {
                    "total_unrealized_pnl": float(total_unrealized),
                    "total_realized_pnl": float(total_realized),
                    "day_pnl": float(total_unrealized + total_realized),
                    "open_positions": open_count,
                },
            }
            await self._mongo_db["portfolio_snapshots"].insert_one(doc)
            log.info("portfolio_eod_snapshot_written", date=snapshot_date.isoformat())
        except Exception as exc:
            log.warning("portfolio_eod_snapshot_error", error=str(exc))

    # ------------------------------------------------------------------ #
    # Hard-cap enforcement                                                 #
    # ------------------------------------------------------------------ #

    async def _check_hard_cap(self) -> None:
        if self._hard_cap_cb is None or self._hard_cap_inr <= 0 or self._hard_cap_triggered:
            return
        daily_loss = self.get_daily_loss()
        if daily_loss >= self._hard_cap_inr:
            self._hard_cap_triggered = True
            log.warning(
                "hard_cap_breached_auto_kill",
                daily_loss=str(daily_loss),
                cap=str(self._hard_cap_inr),
            )
            try:
                await self._hard_cap_cb()
            except Exception as exc:
                log.error("hard_cap_callback_error", exc=str(exc))

    # ------------------------------------------------------------------ #
    # Daily loss reset at market open                                      #
    # ------------------------------------------------------------------ #

    async def _run_loss_reset(self) -> None:
        """Reset the day-start P&L reference at 09:15 IST (market open)."""
        last_reset_date: date | None = None
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._stop_event.wait()),
                    timeout=30.0,
                )
            except TimeoutError:
                pass
            if self._stop_event.is_set():
                break
            now_ist = _ist_now()
            today = now_ist.date()
            if now_ist.hour == 9 and now_ist.minute == 15 and last_reset_date != today:
                self._reset_day_start_pnl()
                last_reset_date = today

    # ------------------------------------------------------------------ #
    # Periodic portfolio broadcast (100ms)                                 #
    # ------------------------------------------------------------------ #

    async def _run_periodic_broadcast(self) -> None:
        """Broadcast position snapshot every 100ms so clients always have fresh data."""
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                break
            if self._stop_event.is_set():
                break
            self._hub.broadcast(self.get_snapshot(), self._build_summary())
