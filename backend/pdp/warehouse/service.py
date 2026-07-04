"""Live options warehouser service.

Responsibilities
----------------
1. Subscribe to all configured underlying indices and their current+next-week ATM±N option bands,
   using one :class:`~pdp.market.dhan_ws.DhanTickerAdapter` connection (Dhan WS accepts multiple
   sids per subscribe call).
2. Route incoming ticks through a :class:`~pdp.market.bars.BarAggregator` (1-minute only) and
   hand closed bars to the correct :class:`~pdp.warehouse.writer.OptionBarWriter` instance,
   selected by security_id from the routing table.
3. Periodically re-roll each underlying's subscription band independently when spot ATM shifts
   or the current weekly expiry changes — without restarting the process.
4. Trigger a daily masters snapshot at session start so expired contracts' symbol + historical
   ``security_id`` remain recoverable.

The service does NOT touch the order router (paper-first, read/ingest only).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
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
from pdp.warehouse.writer import ContractMeta, OptionBarWriter, UnderlyingCfg

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorDatabase

log = structlog.get_logger()

# How often (seconds) to check whether any underlying's band needs rolling.
_ROLL_CHECK_INTERVAL = 60.0

# Segment labels
_SEGMENT_FNO = "NSE_FNO"
_SEGMENT_IDX = "IDX_I"

# Static registry: supported underlyings and their exchange metadata.
# sid = Dhan IDX_I security_id; step = strike increment in points.
UNDERLYING_REGISTRY: dict[str, dict[str, Any]] = {
    "NIFTY":     {"sid": "13", "step": 50,  "expiry_path_setting": "EXPIRY_CACHE_PATH"},
    "BANKNIFTY": {"sid": "25", "step": 100, "expiry_path_setting": "BANKNIFTY_EXPIRY_CACHE_PATH"},
    "SENSEX":    {"sid": "51", "step": 100, "expiry_path_setting": "SENSEX_EXPIRY_CACHE_PATH"},
}

# Dhan IDX_I security_id for every spot-style series the coverage/gap-radar reads from
# `market_bars`, including India VIX (which is not a tradeable underlying, so it lives outside
# UNDERLYING_REGISTRY). Single source of truth for underlying/VIX -> SID lookups.
SID_MAP: dict[str, str] = {**{name: reg["sid"] for name, reg in UNDERLYING_REGISTRY.items()}, "VIX": "21"}


@dataclass
class _UnderlyingState:
    """Mutable per-underlying state: calendar, writer, and roll-detection markers."""

    name: str
    sid: str
    step: int
    calendar: NiftyExpiryCalendar
    writer: OptionBarWriter
    current_atm: int | None = None
    current_expiry: date | None = None
    spot_ltp: Decimal | None = None


def _ist_today() -> date:
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo

    return _dt.now(ZoneInfo("Asia/Kolkata")).date()


class WarehouseService:
    """Standalone live options warehouser for one or more configured underlyings.

    Instantiate, then ``await service.run()`` (blocks until stopped).
    Call ``await service.stop()`` from a signal handler or another coroutine to shut down cleanly.
    """

    def __init__(
        self,
        *,
        settings: Any,
        mongo_db: AsyncIOMotorDatabase,  # type: ignore[type-arg]
        session_maker: async_sessionmaker[AsyncSession],
    ) -> None:
        # Validate configured underlyings against the registry before any I/O.
        invalid = [u for u in settings.WAREHOUSE_UNDERLYINGS if u not in UNDERLYING_REGISTRY]
        if invalid:
            raise ValueError(
                f"Unsupported warehouse underlyings: {invalid!r}. "
                f"Supported set: {sorted(UNDERLYING_REGISTRY)}"
            )

        self._settings = settings
        self._mongo_db = mongo_db
        self._session_maker = session_maker

        from pdp.mongo.collections import get_bars_collection, get_option_bars_collection

        opt_col = get_option_bars_collection(mongo_db)
        mkt_col = get_bars_collection(mongo_db)

        # Build per-underlying state keyed by underlying index SID.
        self._states: dict[str, _UnderlyingState] = {}
        for underlying_name in settings.WAREHOUSE_UNDERLYINGS:
            reg = UNDERLYING_REGISTRY[underlying_name]
            sid = reg["sid"]
            expiry_path = Path(getattr(settings, reg["expiry_path_setting"]))
            if expiry_path.exists():
                cal = NiftyExpiryCalendar.load(expiry_path)
            else:
                log.warning(
                    "warehouse_expiry_cache_missing",
                    underlying=underlying_name,
                    path=str(expiry_path),
                    hint="resolve_expiry will return None until the cache is built",
                )
                cal = NiftyExpiryCalendar({})

            cfg: UnderlyingCfg = {"sid": sid, "step": reg["step"], "underlying": underlying_name}
            writer = OptionBarWriter(
                option_bars_col=opt_col,
                market_bars_col=mkt_col,
                underlying_cfg=cfg,
            )
            self._states[sid] = _UnderlyingState(
                name=underlying_name,
                sid=sid,
                step=reg["step"],
                calendar=cal,
                writer=writer,
            )

        self._adapter = DhanTickerAdapter(
            settings.DHAN_CLIENT_ID,
            settings.DHAN_ACCESS_TOKEN,
        )
        self._aggregator = BarAggregator(["1m"])

        # Flat routing table: all currently subscribed SIDs (index + option) → their writer.
        # Initially contains only index SIDs; option SIDs are added on each _roll_band call.
        self._writers: dict[str, OptionBarWriter] = {
            sid: state.writer for sid, state in self._states.items()
        }

        self._stop_event = asyncio.Event()
        self._snapshot_done: date | None = None

    # ------------------------------------------------------------------ #
    # Main entry point                                                     #
    # ------------------------------------------------------------------ #

    async def run(self) -> None:
        """Start the service and block until stop() is called."""
        underlyings = [s.name for s in self._states.values()]
        log.info("warehouse_service_starting", underlyings=underlyings)

        async with self._session_maker() as session:
            await self._adapter.start(session)

        # Start all writers.
        for state in self._states.values():
            await state.writer.start()

        await self._ensure_snapshot()

        # Subscribe all index feeds before rolling bands so that incoming index ticks
        # populate each state's spot_ltp before ATM computation needs a price.
        async with self._session_maker() as session:
            for state in self._states.values():
                await self._adapter.subscribe(state.sid, _SEGMENT_IDX, session)

        # Start tick consumer now so buffered index ticks drain into spot_ltp caches.
        tick_task = asyncio.create_task(self._consume_ticks(), name="warehouse-tick-consumer")
        await asyncio.sleep(0)

        # Initial band roll for every underlying.
        for state in self._states.values():
            await self._roll_band(state)

        roll_task = asyncio.create_task(self._roll_loop(), name="warehouse-roll-loop")
        bg_tasks = [tick_task, roll_task]
        if self._settings.WAREHOUSE_GAP_BACKFILL_ENABLED:
            bg_tasks.append(
                asyncio.create_task(self._gap_backfill_loop(), name="warehouse-gap-backfill")
            )

        log.info("warehouse_service_running", underlyings=underlyings)
        await self._stop_event.wait()
        log.info("warehouse_service_stopping")

        for task in bg_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        for state in self._states.values():
            await state.writer.stop()
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

        import aiohttp

        from pdp.instruments.snapshots import create_snapshot, parse_underlyings, snapshot_path

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
    # Band roll (per-underlying)                                           #
    # ------------------------------------------------------------------ #

    async def _roll_band(self, state: _UnderlyingState) -> None:
        """Compute current+next-week band for one underlying; subscribe/unsubscribe diffs."""
        today = _ist_today()
        spot = await self._get_spot(state)
        if spot is None:
            log.warning(
                "warehouse_roll_no_spot",
                underlying=state.name,
                reason="cannot resolve ATM without spot",
            )
            return

        atm = atm_strike(float(spot), state.step)
        exp1 = state.calendar.resolve_expiry(today, "WEEK", 1)
        exp2 = state.calendar.resolve_expiry(today, "WEEK", 2)
        if exp1 is None:
            log.warning("warehouse_roll_no_expiry", underlying=state.name, code=1, today=str(today))
            return

        expiries = [exp1]
        if exp2 is not None:
            expiries.append(exp2)

        exp_month = None
        if self._settings.WAREHOUSE_INCLUDE_MONTHLY:
            exp_month = state.calendar.resolve_expiry(today, "MONTH", 1)
            if exp_month is not None and exp_month not in expiries:
                expiries.append(exp_month)

        band = self._settings.WAREHOUSE_STRIKE_BAND
        step = state.step

        desired_contracts: list[tuple[date, int, str, str]] = []
        for expiry in expiries:
            flag = (
                "MONTH"
                if (self._settings.WAREHOUSE_INCLUDE_MONTHLY and expiry == exp_month)
                else "WEEK"
            )
            for offset in range(-band, band + 1):
                strike = atm + offset * step
                for opt in ("CE", "PE"):
                    desired_contracts.append((expiry, strike, opt, flag))

        new_band: dict[str, ContractMeta] = {}
        async with self._session_maker() as session:
            for expiry, strike, opt, flag in desired_contracts:
                sid = await self._resolve_security_id(session, state.name, expiry, strike, opt)
                if sid is None:
                    log.warning(
                        "warehouse_unresolved_contract",
                        underlying=state.name,
                        expiry=str(expiry),
                        strike=strike,
                        option_type=opt,
                    )
                    continue
                trading_sym = symbol_for(state.name, expiry, float(strike), opt)
                strike_offset = (strike - atm) // step
                strike_label = f"ATM{strike_offset:+d}" if strike_offset != 0 else "ATM"
                new_band[sid] = ContractMeta(
                    underlying=state.name,
                    expiry_date=expiry,
                    strike=float(strike),
                    option_type=opt,
                    expiry_flag=flag,
                    trading_symbol=trading_sym,
                    security_id=sid,
                    strike_label=strike_label,
                )

        old_sids = set(state.writer._band.keys())
        new_sids = set(new_band.keys())

        async with self._session_maker() as session:
            await self._adapter.subscribe(state.sid, _SEGMENT_IDX, session)
            for sid in new_sids - old_sids:
                await self._adapter.subscribe(sid, _SEGMENT_FNO, session)
            for sid in old_sids - new_sids:
                await self._adapter.unsubscribe(sid, _SEGMENT_FNO, session)

        # Sync the flat routing table.
        for sid in old_sids - new_sids:
            self._writers.pop(sid, None)
        for sid in new_sids - old_sids:
            self._writers[sid] = state.writer

        state.writer.set_band(new_band)
        state.current_atm = atm
        state.current_expiry = exp1

        log.info(
            "warehouse_band_rolled",
            underlying=state.name,
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
        underlying_name: str,
        expiry: date,
        strike: int,
        option_type: str,
    ) -> str | None:
        """Look up security_id for an option from the instruments table."""
        from decimal import Decimal as Dec

        result = await session.execute(
            select(Instrument.security_id)
            .where(
                Instrument.underlying == underlying_name,
                Instrument.expiry == expiry,
                Instrument.strike == Dec(str(strike)),
                Instrument.option_type == option_type,
                Instrument.exchange_segment == _SEGMENT_FNO,
            )
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return str(row) if row is not None else None

    async def _get_spot(self, state: _UnderlyingState) -> Decimal | None:
        """Return the latest spot price for one underlying.

        Checks the in-memory LTP cache (populated by _consume_ticks) first; falls back to the
        most recent market_bars document on the first call after session start.
        """
        if state.spot_ltp is not None:
            return state.spot_ltp
        try:
            col = self._mongo_db["market_bars"]
            doc = await col.find_one(
                {"metadata.security_id": state.sid},
                sort=[("ts", -1)],
            )
            if doc and doc.get("close"):
                return Decimal(str(doc["close"]))
        except Exception as exc:
            log.debug(
                "warehouse_spot_from_mongo_failed",
                underlying=state.name,
                exc=str(exc),
            )
        return None

    # ------------------------------------------------------------------ #
    # Tick consumption                                                     #
    # ------------------------------------------------------------------ #

    async def _consume_ticks(self) -> None:
        """Consume ticks from the adapter queue, aggregate into bars, route to the correct writer."""
        log.info("warehouse_tick_consumer_started")
        while not self._stop_event.is_set():
            try:
                tick = await asyncio.wait_for(self._adapter.queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            try:
                # Update per-underlying spot_ltp when this is an index tick.
                index_state = self._states.get(tick.security_id)
                if index_state is not None:
                    index_state.spot_ltp = tick.ltp

                bars = self._aggregator.push(tick)
                for bar in bars:
                    writer = self._writers.get(bar.security_id)
                    if writer is None:
                        log.warning(
                            "warehouse_unsolicited_tick",
                            security_id=bar.security_id,
                        )
                    else:
                        writer.enqueue(bar)
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
        """Periodically check whether any underlying's ATM or expiry has changed."""
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
        """Re-roll each underlying independently if its ATM shifted ≥1 step or expiry changed."""
        today = _ist_today()
        for state in self._states.values():
            try:
                exp1 = state.calendar.resolve_expiry(today, "WEEK", 1)
                if exp1 != state.current_expiry:
                    log.info(
                        "warehouse_expiry_rolled",
                        underlying=state.name,
                        old=str(state.current_expiry),
                        new=str(exp1),
                    )
                    await self._roll_band(state)
                    await self._ensure_snapshot()
                    continue

                spot = await self._get_spot(state)
                if spot is None:
                    continue
                new_atm = atm_strike(float(spot), state.step)
                if new_atm != state.current_atm:
                    log.info(
                        "warehouse_atm_shifted",
                        underlying=state.name,
                        old_atm=state.current_atm,
                        new_atm=new_atm,
                    )
                    await self._roll_band(state)
            except Exception as exc:
                log.warning("warehouse_roll_check_underlying_error", underlying=state.name, exc=str(exc))

    # ------------------------------------------------------------------ #
    # Self-healing gap backfill                                            #
    # ------------------------------------------------------------------ #

    async def _gap_backfill_loop(self) -> None:
        """Periodically scan the rolling look-back window for missing option_bars trade-days
        and backfill them from Dhan.  Runs per-underlying; one failure does not block others."""
        interval = max(60.0, self._settings.WAREHOUSE_GAP_CHECK_INTERVAL_HOURS * 3600.0)
        log.info(
            "warehouse_gap_backfill_loop_started",
            interval_s=interval,
            lookback_days=self._settings.WAREHOUSE_GAP_LOOKBACK_DAYS,
        )
        while not self._stop_event.is_set():
            await self._run_gap_backfill()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
            except TimeoutError:
                pass
        log.info("warehouse_gap_backfill_loop_stopped")

    async def _run_gap_backfill(self) -> None:
        from pdp.options.gap_backfill import run_gap_backfill

        for state in self._states.values():
            reg = UNDERLYING_REGISTRY[state.name]
            expiry_path = Path(getattr(self._settings, reg["expiry_path_setting"]))
            if not expiry_path.exists():  # noqa: ASYNC240 — cheap stat, runs on a multi-hour cycle
                log.warning(
                    "warehouse.gap_heal.skipped",
                    underlying=state.name,
                    reason="expiry_cache_missing",
                    path=str(expiry_path),
                )
                continue
            try:
                summary = await asyncio.to_thread(
                    run_gap_backfill,
                    settings=self._settings,
                    cal=state.calendar,
                    lookback_days=self._settings.WAREHOUSE_GAP_LOOKBACK_DAYS,
                    underlying=state.name,
                    underlying_sid=int(state.sid),
                    strike_step=state.step,
                    exchange_segment="NSE_FNO",
                )
                log.info("warehouse_gap_backfill_cycle", underlying=state.name, **summary)
            except Exception as exc:
                log.warning("warehouse_gap_backfill_error", underlying=state.name, exc=str(exc))
                continue

            try:
                await self._emit_coverage_snapshot(state.name)
            except Exception as exc:
                log.warning("warehouse_coverage_snapshot_error", underlying=state.name, exc=str(exc))

    async def _emit_coverage_snapshot(self, underlying: str) -> None:
        """Ship this cycle's per-family coverage to OpenSearch (no-op if indexer inactive)."""
        from pdp.observability.indexer import get_active_indexer
        from pdp.observability.sinks import DATA_COVERAGE, data_coverage_doc

        indexer = get_active_indexer()
        if indexer is None:
            return

        from datetime import timedelta

        from pdp.warehouse.coverage import underlying_coverage

        window_to = _ist_today()
        window_from = window_to - timedelta(days=self._settings.WAREHOUSE_GAP_LOOKBACK_DAYS)
        result = await underlying_coverage(
            self._mongo_db, self._settings, underlying, window_from=window_from, window_to=window_to
        )
        for family, summary in result["families"].items():
            doc, doc_id = data_coverage_doc(underlying, family, summary)
            indexer.enqueue(DATA_COVERAGE, doc, doc_id)
