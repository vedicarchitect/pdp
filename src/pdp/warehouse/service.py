"""Live options warehouser service.

Responsibilities
----------------
1. Subscribe to the primary index (sid ``INDEX_SID``, segment ``IDX_I``) and the current+next-week
   ATM±N × {CE, PE} band, using one :class:`~pdp.market.dhan_ws.DhanTickerAdapter` connection.
2. Route incoming ticks through a :class:`~pdp.market.bars.BarAggregator` (1-minute only) and
   hand closed bars to :class:`~pdp.warehouse.writer.OptionBarWriter`.
3. Periodically re-roll the subscription band when spot ATM shifts or the current weekly expiry
   changes — without restarting the process.
4. Trigger a daily masters snapshot at session start so expired contracts' symbol + historical
   ``security_id`` remain recoverable.

The service does NOT touch the order router (paper-first, read/ingest only).
"""
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pdp.instruments.expiry_calendar import NiftyExpiryCalendar
from pdp.instruments.models import Instrument
from pdp.instruments.symbols import symbol_for
from pdp.market.bars import BarAggregator
from pdp.market.dhan_ws import DhanTickerAdapter
from pdp.strategy.strikes import atm_strike
from pdp.warehouse.writer import INDEX_SID, ContractMeta, OptionBarWriter

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

log = structlog.get_logger()

# How often (seconds) to check whether the band needs rolling.
_ROLL_CHECK_INTERVAL = 60.0

# Segment labels
_SEGMENT_FNO = "NSE_FNO"
_SEGMENT_IDX = "IDX_I"

# Underlying name
_UNDERLYING = "NIFTY"


def _ist_today() -> date:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


class WarehouseService:
    """Standalone live options warehouser.

    Instantiate, then ``await service.run()`` (blocks until stopped).
    Call ``await service.stop()`` from a signal handler or another coroutine to shut down cleanly.
    """

    def __init__(
        self,
        *,
        settings: Any,
        mongo_db: AsyncIOMotorDatabase,  # type: ignore[type-arg]
        session_maker: async_sessionmaker[AsyncSession],
        calendar: NiftyExpiryCalendar,
    ) -> None:
        self._settings = settings
        self._mongo_db = mongo_db
        self._session_maker = session_maker
        self._calendar = calendar

        from pdp.mongo.collections import get_bars_collection, get_option_bars_collection

        self._adapter = DhanTickerAdapter(
            settings.DHAN_CLIENT_ID,
            settings.DHAN_ACCESS_TOKEN,
        )
        self._aggregator = BarAggregator(["1m"])
        self._writer = OptionBarWriter(
            option_bars_col=get_option_bars_collection(mongo_db),
            market_bars_col=get_bars_collection(mongo_db),
        )

        self._stop_event = asyncio.Event()
        # State for roll detection
        self._current_atm: int | None = None
        self._current_expiry: date | None = None   # code-1 expiry
        self._snapshot_done: date | None = None    # date on which snapshot was triggered
        # Latest NIFTY index LTP cached by _consume_ticks; avoids Mongo round-trip in _get_spot
        self._spot_ltp: Decimal | None = None

    # ------------------------------------------------------------------ #
    # Main entry point                                                     #
    # ------------------------------------------------------------------ #

    async def run(self) -> None:
        """Start the service and block until stop() is called."""
        log.info("warehouse_service_starting")
        async with self._session_maker() as session:
            await self._adapter.start(session)

        await self._writer.start()
        await self._ensure_snapshot()

        # Subscribe the index feed before rolling the band so that incoming ticks
        # populate _spot_ltp before ATM computation needs a spot price.
        async with self._session_maker() as session:
            await self._adapter.subscribe(INDEX_SID, _SEGMENT_IDX, session)

        # Start tick consumer now so any buffered index ticks warm the LTP cache
        # before _roll_band calls _get_spot.
        tick_task = asyncio.create_task(self._consume_ticks(), name="warehouse-tick-consumer")
        await asyncio.sleep(0)  # cooperative yield — lets queued ticks drain into _spot_ltp

        # Initial band roll (index already subscribed above; options subscribed here)
        await self._roll_band()

        roll_task = asyncio.create_task(self._roll_loop(), name="warehouse-roll-loop")
        bg_tasks = [tick_task, roll_task]
        if self._settings.WAREHOUSE_GAP_BACKFILL_ENABLED:
            bg_tasks.append(
                asyncio.create_task(self._gap_backfill_loop(), name="warehouse-gap-backfill")
            )

        log.info("warehouse_service_running")
        await self._stop_event.wait()
        log.info("warehouse_service_stopping")

        # Cancel background tasks
        for task in bg_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Stop writer (drains buffers) then adapter
        await self._writer.stop()
        await self._adapter.stop()
        log.info("warehouse_service_stopped")

    async def stop(self) -> None:
        """Signal the service to stop gracefully."""
        self._stop_event.set()

    # ------------------------------------------------------------------ #
    # Masters snapshot                                                     #
    # ------------------------------------------------------------------ #

    async def _ensure_snapshot(self) -> None:
        """Trigger a masters snapshot for today if not already done this session."""
        today = _ist_today()
        if self._snapshot_done == today:
            return
        try:
            await self._take_snapshot(today)
            self._snapshot_done = today
        except Exception as exc:
            log.warning("warehouse_snapshot_failed", exc=str(exc))

    async def _take_snapshot(self, snapshot_date: date) -> None:
        """Download the Dhan scrip master and write today's snapshot."""
        import csv
        import io
        from pathlib import Path

        import aiohttp

        from pdp.instruments.snapshots import create_snapshot, snapshot_path
        from pdp.instruments.snapshots import parse_underlyings

        masters_dir = Path(self._settings.MASTERS_DIR)
        path = snapshot_path(snapshot_date, masters_dir)
        if path.exists():
            log.info("warehouse_snapshot_exists", date=str(snapshot_date), path=str(path))
            return

        url = self._settings.DHAN_SCRIPMASTER_URL
        log.info("warehouse_snapshot_downloading", url=url)
        try:
            async with aiohttp.ClientSession() as http:
                async with http.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    resp.raise_for_status()
                    content = await resp.text(encoding="utf-8")
        except Exception as exc:
            log.warning("warehouse_snapshot_download_failed", exc=str(exc))
            return

        reader = csv.DictReader(io.StringIO(content))
        rows = [dict(r) for r in reader]

        underlyings = parse_underlyings(self._settings.SNAPSHOT_UNDERLYINGS)
        snap_path, count = create_snapshot(rows, snapshot_date, masters_dir, underlyings)
        log.info("warehouse_snapshot_created", date=str(snapshot_date), rows=count, path=str(snap_path))

    # ------------------------------------------------------------------ #
    # Band roll                                                            #
    # ------------------------------------------------------------------ #

    async def _roll_band(self) -> None:
        """Compute current+next-week band; subscribe/unsubscribe diffs; update writer band."""
        today = _ist_today()
        spot = await self._get_spot()
        if spot is None:
            log.warning("warehouse_roll_no_spot", reason="cannot resolve ATM without spot")
            return

        atm = atm_strike(float(spot), self._settings.WAREHOUSE_STRIKE_STEP)
        exp1 = self._calendar.resolve_expiry(today, "WEEK", 1)
        exp2 = self._calendar.resolve_expiry(today, "WEEK", 2)
        if exp1 is None:
            log.warning("warehouse_roll_no_expiry", code=1, today=str(today))
            return

        expiries = [exp1]
        if exp2 is not None:
            expiries.append(exp2)

        if self._settings.WAREHOUSE_INCLUDE_MONTHLY:
            exp_month = self._calendar.resolve_expiry(today, "MONTH", 1)
            if exp_month is not None and exp_month not in expiries:
                expiries.append(exp_month)

        band = self._settings.WAREHOUSE_STRIKE_BAND
        step = self._settings.WAREHOUSE_STRIKE_STEP

        # Build desired (expiry, strike, option_type) tuples
        desired_contracts: list[tuple[date, int, str, str]] = []  # (expiry, strike, opt, flag)
        for expiry in expiries:
            flag = "MONTH" if (expiry == exp_month if self._settings.WAREHOUSE_INCLUDE_MONTHLY else False) else "WEEK"
            for offset in range(-band, band + 1):
                strike = atm + offset * step
                for opt in ("CE", "PE"):
                    desired_contracts.append((expiry, strike, opt, flag))

        # Resolve security_ids from the instruments table
        new_band: dict[str, ContractMeta] = {}
        async with self._session_maker() as session:
            for expiry, strike, opt, flag in desired_contracts:
                sid = await self._resolve_security_id(session, expiry, strike, opt)
                if sid is None:
                    log.warning(
                        "warehouse_unresolved_contract",
                        expiry=str(expiry),
                        strike=strike,
                        option_type=opt,
                    )
                    continue
                trading_sym = symbol_for(_UNDERLYING, expiry, float(strike), opt)
                strike_offset = (strike - atm) // step
                strike_label = f"ATM{strike_offset:+d}" if strike_offset != 0 else "ATM"
                new_band[sid] = ContractMeta(
                    underlying=_UNDERLYING,
                    expiry_date=expiry,
                    strike=float(strike),
                    option_type=opt,
                    expiry_flag=flag,
                    trading_symbol=trading_sym,
                    security_id=sid,
                    strike_label=strike_label,
                )

        # Subscribe new sids, unsubscribe dropped sids
        old_sids = set(self._writer._band.keys())
        new_sids = set(new_band.keys())

        async with self._session_maker() as session:
            # Subscribe index if not already done
            await self._adapter.subscribe(INDEX_SID, _SEGMENT_IDX, session)
            for sid in new_sids - old_sids:
                await self._adapter.subscribe(sid, _SEGMENT_FNO, session)
            for sid in old_sids - new_sids:
                await self._adapter.unsubscribe(sid, _SEGMENT_FNO, session)

        self._writer.set_band(new_band)
        self._current_atm = atm
        self._current_expiry = exp1

        log.info(
            "warehouse_band_rolled",
            atm=atm,
            expiry1=str(exp1),
            expiry2=str(exp2) if exp2 else None,
            contracts=len(new_band),
            subscribed=len(new_sids - old_sids),
            unsubscribed=len(old_sids - new_sids),
        )

    async def _resolve_security_id(
        self,
        session: AsyncSession,
        expiry: date,
        strike: int,
        option_type: str,
    ) -> str | None:
        """Look up security_id for a NIFTY option from the instruments table."""
        from decimal import Decimal as Dec

        result = await session.execute(
            select(Instrument.security_id)
            .where(
                Instrument.underlying == _UNDERLYING,
                Instrument.expiry == expiry,
                Instrument.strike == Dec(str(strike)),
                Instrument.option_type == option_type,
                Instrument.exchange_segment == _SEGMENT_FNO,
            )
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return str(row) if row is not None else None

    async def _get_spot(self) -> Decimal | None:
        """Return the latest NIFTY spot price.

        Checks the in-memory LTP cache first (populated by _consume_ticks as soon as
        the index subscription delivers ticks).  Falls back to the most recent
        market_bars document for the first call on session start.  Returns None when
        neither source has a value; the caller logs a warning and retries next cycle.
        """
        if self._spot_ltp is not None:
            return self._spot_ltp
        try:
            col = self._mongo_db["market_bars"]
            doc = await col.find_one(
                {"metadata.security_id": INDEX_SID},
                sort=[("ts", -1)],
            )
            if doc and doc.get("close"):
                return Decimal(str(doc["close"]))
        except Exception as exc:
            log.debug("warehouse_spot_from_mongo_failed", exc=str(exc))
        return None

    # ------------------------------------------------------------------ #
    # Tick consumption                                                     #
    # ------------------------------------------------------------------ #

    async def _consume_ticks(self) -> None:
        """Consume ticks from the adapter queue, aggregate into bars, route to writer."""
        log.info("warehouse_tick_consumer_started")
        while not self._stop_event.is_set():
            try:
                tick = await asyncio.wait_for(self._adapter.queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            try:
                if tick.security_id == INDEX_SID:
                    self._spot_ltp = tick.ltp
                bars = self._aggregator.push(tick)
                for bar in bars:
                    self._writer.enqueue(bar)
            except Exception as exc:
                log.warning(
                    "warehouse_tick_error",
                    exc=str(exc),
                    security_id=tick.security_id,
                )
            finally:
                self._adapter.queue.task_done()
        log.info("warehouse_tick_consumer_stopped")

    # ------------------------------------------------------------------ #
    # Roll loop                                                            #
    # ------------------------------------------------------------------ #

    async def _roll_loop(self) -> None:
        """Periodically check whether ATM or expiry has changed; re-roll if so."""
        log.info("warehouse_roll_loop_started")
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=_ROLL_CHECK_INTERVAL)
            except TimeoutError:
                pass
            if self._stop_event.is_set():
                break
            try:
                await self._check_roll()
            except Exception as exc:
                log.warning("warehouse_roll_check_error", exc=str(exc))
        log.info("warehouse_roll_loop_stopped")

    async def _check_roll(self) -> None:
        """Re-roll if ATM shifted by ≥1 step or the code-1 expiry changed."""
        today = _ist_today()

        # Check expiry change first (cheap)
        exp1 = self._calendar.resolve_expiry(today, "WEEK", 1)
        if exp1 != self._current_expiry:
            log.info(
                "warehouse_expiry_rolled",
                old=str(self._current_expiry),
                new=str(exp1),
            )
            await self._roll_band()
            # Also ensure snapshot for the new day
            await self._ensure_snapshot()
            return

        # Check ATM shift
        spot = await self._get_spot()
        if spot is None:
            return
        new_atm = atm_strike(float(spot), self._settings.WAREHOUSE_STRIKE_STEP)
        if new_atm != self._current_atm:
            log.info(
                "warehouse_atm_shifted",
                old_atm=self._current_atm,
                new_atm=new_atm,
            )
            await self._roll_band()

    # ------------------------------------------------------------------ #
    # Self-healing gap backfill                                            #
    # ------------------------------------------------------------------ #

    async def _gap_backfill_loop(self) -> None:
        """Periodically scan the rolling look-back window for missing option_bars trade-days
        and backfill them from Dhan. The blocking REST/pymongo work runs in a worker thread so
        the event loop stays responsive; first-write-wins upserts keep re-fills non-duplicate."""
        interval = max(60.0, self._settings.WAREHOUSE_GAP_CHECK_INTERVAL_HOURS * 3600.0)
        log.info("warehouse_gap_backfill_loop_started", interval_s=interval,
                 lookback_days=self._settings.WAREHOUSE_GAP_LOOKBACK_DAYS)
        while not self._stop_event.is_set():
            try:
                await self._run_gap_backfill()
            except Exception as exc:
                log.warning("warehouse_gap_backfill_error", exc=str(exc))
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
            except TimeoutError:
                pass
        log.info("warehouse_gap_backfill_loop_stopped")

    async def _run_gap_backfill(self) -> None:
        from pdp.options.gap_backfill import run_gap_backfill

        summary = await asyncio.to_thread(
            run_gap_backfill,
            settings=self._settings,
            cal=self._calendar,
            lookback_days=self._settings.WAREHOUSE_GAP_LOOKBACK_DAYS,
        )
        log.info("warehouse_gap_backfill_cycle", **summary)
