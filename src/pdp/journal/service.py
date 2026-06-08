"""Paper-trade journal service.

Subscribes to OrdersHub fill events, buffers per IST trading day in memory, and periodically
upserts each day's entries + rollup stats to MongoDB ``paper_journal``. Read via the journal
REST routes and the frontend panel.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import structlog

from pdp.journal.stats import compute_daily_stats

if TYPE_CHECKING:
    from pdp.orders.ws import OrdersHub

log = structlog.get_logger()

_IST = ZoneInfo("Asia/Kolkata")
_FLUSH_INTERVAL = 5.0  # seconds


def _ist_today() -> str:
    return datetime.now(_IST).date().isoformat()


class JournalService:
    def __init__(self, mongo_db: Any = None) -> None:
        self._mongo = mongo_db
        self._trades_by_day: dict[str, list[dict[str, Any]]] = {}
        self._dirty_days: set[str] = set()
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------ #
    # Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        await self._load_today()
        self._task = asyncio.create_task(self._flush_loop(), name="journal-flush")
        log.info("journal_service_started")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            await self._task
        await self._flush()

    def subscribe_fill_events(self, orders_hub: OrdersHub) -> None:
        orders_hub.register_fill_callback(self.record_fill)

    # ------------------------------------------------------------------ #
    # Recording (sync — called from the OrdersHub fill callback)          #
    # ------------------------------------------------------------------ #

    def record_fill(self, payload: dict[str, Any]) -> None:
        day = _ist_today()
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "security_id": payload.get("security_id", ""),
            "side": payload.get("side", ""),
            "qty": payload.get("qty", 0),
            "fill_price": str(payload.get("fill_price", "0")),
            "charges": str(payload.get("charges", "0")),
            "strategy_id": payload.get("strategy_id"),
        }
        self._trades_by_day.setdefault(day, []).append(entry)
        self._dirty_days.add(day)

    # ------------------------------------------------------------------ #
    # Reads                                                               #
    # ------------------------------------------------------------------ #

    def get_day(self, day: str | None = None) -> dict[str, Any]:
        day = day or _ist_today()
        trades = self._trades_by_day.get(day, [])
        return {"date": day, "trades": trades, "stats": compute_daily_stats(trades)}

    def get_stats(self, day: str | None = None) -> dict[str, Any]:
        day = day or _ist_today()
        return {"date": day, "stats": compute_daily_stats(self._trades_by_day.get(day, []))}

    # ------------------------------------------------------------------ #
    # Mongo persistence                                                   #
    # ------------------------------------------------------------------ #

    async def _load_today(self) -> None:
        if self._mongo is None:
            return
        try:
            doc = await self._mongo["paper_journal"].find_one({"date": _ist_today()})
            if doc and isinstance(doc.get("trades"), list):
                self._trades_by_day[_ist_today()] = doc["trades"]
        except Exception as exc:
            log.warning("journal_load_failed", exc=str(exc))

    async def _flush_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=_FLUSH_INTERVAL)
            except TimeoutError:
                pass
            await self._flush()

    async def _flush(self) -> None:
        if self._mongo is None or not self._dirty_days:
            return
        days = list(self._dirty_days)
        self._dirty_days.clear()
        for day in days:
            trades = self._trades_by_day.get(day, [])
            doc = {
                "date": day,
                "mode": "paper",
                "trades": trades,
                "stats": compute_daily_stats(trades),
                "updated_at": datetime.now(UTC),
            }
            try:
                await self._mongo["paper_journal"].update_one(
                    {"date": day}, {"$set": doc}, upsert=True
                )
            except Exception as exc:
                log.warning("journal_flush_failed", day=day, exc=str(exc))
                self._dirty_days.add(day)  # retry next cycle
