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


def _ship_journal(day: str, trades: list[dict[str, Any]], stats: dict[str, Any]) -> None:
    """Dual-sink fills + the daily rollup to OpenSearch (no-op when indexer inactive)."""
    from pdp.observability.indexer import get_active_indexer

    indexer = get_active_indexer()
    if indexer is None:
        return
    from pdp.observability.sinks import JOURNAL, TRADES, fill_doc, journal_day_doc

    for entry in trades:
        doc, doc_id = fill_doc(entry)
        indexer.enqueue(TRADES, doc, doc_id)
    jdoc, jid = journal_day_doc(day, stats)
    indexer.enqueue(JOURNAL, jdoc, jid)


class JournalService:
    def __init__(self, mongo_db: Any = None) -> None:
        self._mongo = mongo_db
        self._trades_by_day: dict[str, list[dict[str, Any]]] = {}
        self._dirty_days: set[str] = set()
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._notes_by_day: dict[str, str] = {}
        self._tags_by_day: dict[str, list[str]] = {}
        self._screenshots_by_day: dict[str, list[str]] = {}

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
    # Reads & Writes                                                      #
    # ------------------------------------------------------------------ #

    def get_day(self, day: str | None = None) -> dict[str, Any]:
        day = day or _ist_today()
        trades = self._trades_by_day.get(day, [])
        return {
            "date": day,
            "trades": trades,
            "stats": compute_daily_stats(trades),
            "notes": getattr(self, "_notes_by_day", {}).get(day, ""),
            "tags": getattr(self, "_tags_by_day", {}).get(day, []),
            "screenshots": getattr(self, "_screenshots_by_day", {}).get(day, []),
        }

    def get_stats(self, day: str | None = None) -> dict[str, Any]:
        day = day or _ist_today()
        return {"date": day, "stats": compute_daily_stats(self._trades_by_day.get(day, []))}
        
    async def update_metadata(self, day: str, notes: str, tags: list[str], screenshots: list[str]) -> None:
        self._notes_by_day[day] = notes
        self._tags_by_day[day] = tags
        self._screenshots_by_day[day] = screenshots
        self._dirty_days.add(day)

    # ------------------------------------------------------------------ #
    # Mongo persistence                                                   #
    # ------------------------------------------------------------------ #

    async def _load_today(self) -> None:
        if self._mongo is None:
            return
        
        try:
            doc = await self._mongo["paper_journal"].find_one({"date": _ist_today()})
            if doc:
                if isinstance(doc.get("trades"), list):
                    self._trades_by_day[_ist_today()] = doc["trades"]
                self._notes_by_day[_ist_today()] = doc.get("notes", "")
                self._tags_by_day[_ist_today()] = doc.get("tags", [])
                self._screenshots_by_day[_ist_today()] = doc.get("screenshots", [])
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
            stats = compute_daily_stats(trades)
            doc = {
                "date": day,
                "mode": "paper",
                "trades": trades,
                "stats": stats,
                "notes": self._notes_by_day.get(day, ""),
                "tags": self._tags_by_day.get(day, []),
                "screenshots": self._screenshots_by_day.get(day, []),
                "updated_at": datetime.now(UTC),
            }
            try:
                await self._mongo["paper_journal"].update_one(
                    {"date": day}, {"$set": doc}, upsert=True
                )
            except Exception as exc:
                log.warning("journal_flush_failed", day=day, exc=str(exc))
                self._dirty_days.add(day)  # retry next cycle
            _ship_journal(day, trades, stats)
