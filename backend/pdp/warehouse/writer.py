"""Contract-aware async writer for the live options warehouser.

Mirrors the batching/flush-loop design of :class:`pdp.market.bar_writer.BarWriter` but
routes each closed bar to either:

* ``option_bars``  — for option contracts (NSE_FNO), using
  :func:`pdp.options.warehouse.build_option_bar_doc` + first-write-wins upserts.
* ``market_bars``  — for the index spot (security_id from settings), via the same
  batched insert pattern as :class:`~pdp.market.bar_writer.BarWriter`.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, TypedDict


class UnderlyingCfg(TypedDict):
    sid: str
    step: int
    underlying: str


import structlog

from pdp.options.warehouse import build_option_bar_doc, upsert_option_bars_async

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection

    from pdp.market.bars import BarClosed

log = structlog.get_logger()

# Flush tuning — mirrors bar_writer.py
_FLUSH_INTERVAL = 1.0  # seconds between periodic flushes
_FLUSH_BATCH = 500  # max docs per flush
_MAX_BUFFER = 10_000  # drop-oldest threshold per buffer


@dataclass(slots=True)
class ContractMeta:
    """All fixed-contract metadata for one option security_id."""

    underlying: str
    expiry_date: date
    strike: float
    option_type: str  # "CE" | "PE"
    expiry_flag: str  # "WEEK" | "MONTH"
    trading_symbol: str
    security_id: str | None = None
    strike_label: str | None = None


class OptionBarWriter:
    """Batched async writer that fans closed bars to ``option_bars`` or ``market_bars``.

    Usage::

        writer = OptionBarWriter(option_bars_col, market_bars_col)
        await writer.start()
        writer.set_band(band_map)          # {security_id: ContractMeta}
        writer.enqueue(bar_closed)
        ...
        await writer.stop()               # drains both buffers before returning
    """

    def __init__(
        self,
        option_bars_col: AsyncIOMotorCollection,  # type: ignore[type-arg]
        market_bars_col: AsyncIOMotorCollection,  # type: ignore[type-arg]
        underlying_cfg: UnderlyingCfg,
    ) -> None:
        self._opt_col = option_bars_col
        self._mkt_col = market_bars_col
        self._cfg = underlying_cfg
        # Per-collection buffers
        self._opt_buf: deque[dict[str, Any]] = deque()
        self._mkt_buf: deque[dict[str, Any]] = deque()
        # Band map: security_id -> ContractMeta (options only)
        self._band: dict[str, ContractMeta] = {}
        self._stop_event = asyncio.Event()
        self._flush_task: asyncio.Task[None] | None = None
        # Timestamps of spot bars already written; pre-populated from Mongo on start()
        # so a restart doesn't re-insert bars from the same session.
        self._flushed_spot_ts: set[datetime] = set()

    # ------------------------------------------------------------------ #
    # Public control API                                                   #
    # ------------------------------------------------------------------ #

    def set_band(self, band: dict[str, ContractMeta]) -> None:
        """Replace the current band map (called on roll without restart)."""
        self._band = band
        log.info("option_writer_band_updated", contracts=len(band))

    async def start(self) -> None:
        # Pre-load today's spot timestamps so a restart doesn't create duplicates in
        # the time-series collection (which has no uniqueness constraint).
        cutoff = datetime.now(UTC) - timedelta(hours=12)
        try:
            existing = await self._mkt_col.distinct(
                "ts",
                {"metadata.security_id": self._cfg["sid"], "ts": {"$gte": cutoff}},
            )
            self._flushed_spot_ts = set(existing)
            log.info("spot_writer_dedup_loaded", count=len(self._flushed_spot_ts))
        except Exception as exc:
            log.warning("spot_writer_dedup_load_failed", exc=str(exc))
        self._flush_task = asyncio.create_task(self._flush_loop(), name="option-writer-flush")
        log.info("option_writer_started")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._flush_task is not None:
            await self._flush_task

    # ------------------------------------------------------------------ #
    # Enqueue (hot path — called from event loop, no locking needed)       #
    # ------------------------------------------------------------------ #

    def enqueue(self, bar: BarClosed) -> None:
        """Route a closed bar to the appropriate buffer."""
        if bar.security_id == self._cfg["sid"]:
            self._enqueue_spot(bar)
        else:
            self._enqueue_option(bar)

    def _enqueue_spot(self, bar: BarClosed) -> None:
        if len(self._mkt_buf) >= _MAX_BUFFER:
            self._mkt_buf.popleft()
            log.warning("spot_writer_overflow", security_id=bar.security_id)
        self._mkt_buf.append(
            {
                "ts": bar.bar_time,
                "metadata": {
                    "security_id": bar.security_id,
                    "timeframe": bar.timeframe,
                },
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": bar.volume,
                "oi": bar.oi,
            }
        )

    def _enqueue_option(self, bar: BarClosed) -> None:
        meta = self._band.get(bar.security_id)
        if meta is None:
            # Bar arrived for a security_id not in our band — skip silently
            # (can happen on reconnect / stale sub before roll completes)
            return
        if len(self._opt_buf) >= _MAX_BUFFER:
            self._opt_buf.popleft()
            log.warning("option_writer_overflow", security_id=bar.security_id)
        doc = build_option_bar_doc(
            underlying=meta.underlying,
            expiry_date=meta.expiry_date,
            strike=meta.strike,
            option_type=meta.option_type,
            timeframe=bar.timeframe,
            ts=bar.bar_time,
            open=float(bar.open),
            high=float(bar.high),
            low=float(bar.low),
            close=float(bar.close),
            volume=bar.volume,
            oi=bar.oi,
            iv=0.0,
            expiry_flag=meta.expiry_flag,
            trading_symbol=meta.trading_symbol,
            security_id=meta.security_id,
            strike_label=meta.strike_label,
            source="live",
        )
        self._opt_buf.append(doc)

    # ------------------------------------------------------------------ #
    # Flush loop                                                           #
    # ------------------------------------------------------------------ #

    async def _flush_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=_FLUSH_INTERVAL)
            except TimeoutError:
                pass
            await self._flush_all()
        # Final drain on shutdown
        await self._flush_all()

    async def _flush_all(self) -> None:
        await self._flush_options()
        await self._flush_spot()

    async def _flush_options(self) -> None:
        if not self._opt_buf:
            return
        batch: list[dict[str, Any]] = []
        while self._opt_buf and len(batch) < _FLUSH_BATCH:
            batch.append(self._opt_buf.popleft())
        if not batch:
            return
        try:
            inserted = await upsert_option_bars_async(self._opt_col, batch)
            log.debug("option_writer_flushed", docs=len(batch), new=inserted)
        except Exception as exc:
            log.warning("option_writer_flush_error", exc=str(exc), rows=len(batch))
            # Re-queue on error (best-effort recovery)
            for doc in reversed(batch):
                self._opt_buf.appendleft(doc)

    async def _flush_spot(self) -> None:
        if not self._mkt_buf:
            return
        from pymongo.errors import BulkWriteError

        batch: list[dict[str, Any]] = []
        while self._mkt_buf and len(batch) < _FLUSH_BATCH:
            batch.append(self._mkt_buf.popleft())
        if not batch:
            return
        # Skip timestamps already written this session (guards against restart duplicates
        # since the market_bars time-series collection has no uniqueness constraint).
        batch = [doc for doc in batch if doc["ts"] not in self._flushed_spot_ts]
        if not batch:
            return
        try:
            await self._mkt_col.insert_many(batch, ordered=False)
            for doc in batch:
                self._flushed_spot_ts.add(doc["ts"])
            log.debug("spot_writer_flushed", rows=len(batch))
        except BulkWriteError as exc:
            details = exc.details
            log.warning(
                "spot_writer_bulk_error",
                inserted=details.get("nInserted", 0),
                errors=len(details.get("writeErrors", [])),
            )
        except Exception as exc:
            log.warning("spot_writer_flush_error", exc=str(exc), rows=len(batch))
            for doc in reversed(batch):
                self._mkt_buf.appendleft(doc)
