"""Daily pre-open scrip-master refresh scheduler.

Fires once per day at SCRIP_REFRESH_TIME (IST, default 08:45) before market open.
Calls the existing refresh_instruments() and logs lot-size / freeze-qty / expiry
diffs via snapshots.py.  Idempotent: skips if today already ran successfully.
Never blocks startup; failures are logged and retried the next day.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from pdp.settings import Settings

log = structlog.get_logger()

_IST = timezone(timedelta(hours=5, minutes=30))


class ScripRefreshScheduler:
    def __init__(self, session_maker: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._session_maker = session_maker
        self._settings = settings
        try:
            hh, mm = settings.SCRIP_REFRESH_TIME.split(":")
            self._target = (int(hh), int(mm))
        except (ValueError, AttributeError):
            self._target = (8, 45)
        self._last_run_date: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="scrip-refresh")
        log.info(
            "scrip_refresh_scheduler_started",
            refresh_time=f"{self._target[0]:02d}:{self._target[1]:02d}",
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                now = datetime.now(_IST)
                date_str = now.strftime("%Y-%m-%d")
                past_target = (now.hour, now.minute) >= self._target
                if past_target and self._last_run_date != date_str:
                    await self._run(date_str)
                    self._last_run_date = date_str
            except Exception as exc:
                log.warning("scrip_refresh_scheduler_error", error=str(exc))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=60)
            except TimeoutError:
                pass

    async def _run(self, date_str: str) -> None:
        from pathlib import Path

        from pdp.instruments.loader import download_dhan_master, parse_dhan_csv, upsert_instruments
        from pdp.instruments.snapshots import create_snapshot, parse_underlyings

        log.info("scrip_refresh_start", date=date_str)
        try:
            raw = await download_dhan_master(self._settings.DHAN_SCRIPMASTER_URL)
            rows = parse_dhan_csv(raw)
            log.info("scrip_refresh_parsed", rows=len(rows))
            async with self._session_maker() as session:
                stats = await upsert_instruments(session, rows)
            log.info(
                "scrip_refresh_upserted",
                date=date_str,
                rows_seen=stats.rows_seen,
                rows_upserted=stats.rows_upserted,
            )
            underlyings = parse_underlyings(self._settings.SNAPSHOT_UNDERLYINGS)
            snap_date = date.fromisoformat(date_str)
            _, snap_count = create_snapshot(
                rows, snap_date,
                masters_dir=Path(self._settings.MASTERS_DIR),
                underlyings=underlyings,
            )
            log.info("scrip_refresh_snapshot_written", date=date_str, rows=snap_count)
            try:
                await self._sync_expiry_calendar(date.fromisoformat(date_str))
            except Exception as exc:  # never let calendar upkeep fail the refresh
                log.warning("expiry_calendar_sync_failed", date=date_str, exc=str(exc))
        except Exception as exc:
            # Log and retain last-good; retry next day
            log.warning("scrip_refresh_failed", date=date_str, exc=str(exc))
            self._last_run_date = None  # allow retry

    async def _sync_expiry_calendar(self, today: date) -> None:
        """Upsert upcoming real expiries into the DB `expiry_calendar` so it self-maintains.

        Keeps the persistent calendar current with what the scrip master now lists (source
        `scripmaster`), classifying each month's last expiry as MONTH. Idempotent — only genuinely
        new dates are inserted. Runs the blocking pymongo upsert in a thread.
        """
        from sqlalchemy import select

        from pdp.instruments.expiry_calendar import (
            classify_month_expiries,
            upsert_confirmed_expiries,
        )
        from pdp.instruments.models import Instrument

        underlyings = ("NIFTY", "BANKNIFTY", "SENSEX")
        async with self._session_maker() as session:
            per_underlying: dict[str, list[date]] = {}
            for underlying in underlyings:
                rows = await session.execute(
                    select(Instrument.expiry)
                    .where(
                        Instrument.underlying == underlying,
                        Instrument.option_type.in_(["CE", "PE"]),
                        Instrument.expiry >= today,
                    )
                    .distinct()
                    .order_by(Instrument.expiry)
                )
                per_underlying[underlying] = [e for (e,) in rows.all() if e is not None]

        def _upsert() -> None:
            from pymongo import MongoClient

            client = MongoClient(
                self._settings.MONGO_URI,
                serverSelectionTimeoutMS=self._settings.MONGO_CONNECT_TIMEOUT_MS,
                maxPoolSize=1,
            )
            try:
                mdb = client[self._settings.MONGO_DB_NAME]
                for underlying, exps in per_underlying.items():
                    if not exps:
                        continue
                    week_list, month_list = classify_month_expiries(exps)
                    nw = upsert_confirmed_expiries(mdb, underlying, "WEEK", week_list,
                                                   source="scripmaster")
                    nm = upsert_confirmed_expiries(mdb, underlying, "MONTH", month_list,
                                                   source="scripmaster")
                    log.info("expiry_calendar_synced", underlying=underlying,
                             upcoming=len(exps), new_week=nw, new_month=nm)
            finally:
                client.close()

        await asyncio.to_thread(_upsert)
