"""Sync manual Dhan positions into a monitored set + auto-subscribe their feeds."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

import structlog

from pdp.events.models import Event, EventType, MonitoredPosition, Severity
from pdp.options.dhan_client import UNDERLYING_MAP

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from pdp.market.dhan_ws import DhanTickerAdapter
    from pdp.settings import Settings

log = structlog.get_logger()


def _resolve_underlying(symbol: str) -> str:
    s = (symbol or "").upper().replace(" ", "")
    for name in UNDERLYING_MAP:
        if s.startswith(name):
            return name
    return "NIFTY"


def _map_dhan_position(pos: dict[str, Any]) -> MonitoredPosition | None:
    qty = int(float(pos.get("netQty", pos.get("quantity", 0)) or 0))
    if qty == 0:
        return None
    symbol = str(pos.get("tradingSymbol", pos.get("securityId", "")))
    seg = str(pos.get("exchangeSegment", "NSE_FNO"))
    if qty > 0:
        avg = float(pos.get("buyAvg", pos.get("costPrice", 0)) or 0)
    else:
        avg = float(pos.get("sellAvg", pos.get("costPrice", 0)) or 0)
    opt = pos.get("drvOptionType") or None
    strike_raw = pos.get("drvStrikePrice")
    strike = float(strike_raw) if strike_raw else None
    delta = pos.get("delta")
    return MonitoredPosition(
        security_id=str(pos.get("securityId", symbol)),
        underlying=_resolve_underlying(symbol),
        exchange_segment=seg,
        net_qty=qty,
        avg_price=avg,
        side="LONG" if qty > 0 else "SHORT",
        strike=strike,
        option_type=opt if opt in ("CE", "PE") else None,
        expiry=str(pos.get("drvExpiryDate")) if pos.get("drvExpiryDate") else None,
        delta=float(delta) if delta else None,
        trading_symbol=symbol,
    )


class PositionSync:
    """Polls broker positions, maintains the monitored set, and subscribes feeds."""

    def __init__(
        self,
        settings: Settings,
        session_maker: async_sessionmaker[AsyncSession],
        adapter: DhanTickerAdapter | None,
        emit: Callable[[Event], None],
        interval_seconds: int = 30,
    ) -> None:
        self._settings = settings
        self._session_maker = session_maker
        self._adapter = adapter
        self._emit = emit
        self._interval = interval_seconds
        self._positions: dict[str, MonitoredPosition] = {}
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    # ── public read surface ───────────────────────────────────────────────────
    def get_positions(self) -> list[MonitoredPosition]:
        return list(self._positions.values())

    def for_underlying(self, underlying: str) -> list[MonitoredPosition]:
        u = underlying.upper()
        return [p for p in self._positions.values() if p.underlying.upper() == u]

    def underlyings(self) -> set[str]:
        return {p.underlying for p in self._positions.values()}

    # ── lifecycle ─────────────────────────────────────────────────────────────
    async def start(self) -> None:
        await self._sync_once()
        self._task = asyncio.create_task(self._run(), name="events-position-sync")
        log.info("position_sync_started", positions=len(self._positions))

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except TimeoutError:
                pass
            if self._stop.is_set():
                break
            await self._sync_once()

    # ── sync ──────────────────────────────────────────────────────────────────
    async def _sync_once(self) -> None:
        try:
            if self._settings.DHAN_CLIENT_ID and self._settings.DHAN_ACCESS_TOKEN:
                new = await self._fetch_live()
            else:
                new = await self._fetch_paper()
        except Exception as exc:
            log.warning("position_sync_failed", exc=str(exc))
            return  # retain last known set
        await self._apply(new)

    async def _fetch_live(self) -> list[MonitoredPosition]:
        from dhanhq import DhanContext, dhanhq  # type: ignore[import-untyped]

        def _call() -> Any:
            ctx = DhanContext(self._settings.DHAN_CLIENT_ID, self._settings.DHAN_ACCESS_TOKEN)
            client: Any = dhanhq(ctx)
            resp: Any = client.get_positions()
            return resp.get("data", []) if resp else []

        raw: Any = await asyncio.to_thread(_call)
        items: list[Any] = cast("list[Any]", raw) if isinstance(raw, list) else []
        out: list[MonitoredPosition] = []
        for pos in items:
            if isinstance(pos, dict):
                mp = _map_dhan_position(cast("dict[str, Any]", pos))
                if mp is not None:
                    out.append(mp)
        return out

    async def _fetch_paper(self) -> list[MonitoredPosition]:
        from sqlalchemy import select

        from pdp.orders.models import Position

        async with self._session_maker() as session:
            result = await session.execute(select(Position).where(Position.net_qty != 0))
            rows = result.scalars().all()
        out: list[MonitoredPosition] = []
        for r in rows:
            out.append(
                MonitoredPosition(
                    security_id=r.security_id,
                    underlying=_resolve_underlying(r.security_id),
                    exchange_segment=r.exchange_segment,
                    net_qty=int(r.net_qty),
                    avg_price=float(r.avg_price),
                    side="LONG" if r.net_qty > 0 else "SHORT",
                )
            )
        return out

    async def _apply(self, new_list: list[MonitoredPosition]) -> None:
        new_map = {p.key: p for p in new_list}
        old_keys = set(self._positions)
        new_keys = set(new_map)

        # carry MTM peak across syncs for surviving positions
        for k in new_keys & old_keys:
            new_map[k].mtm_peak = self._positions[k].mtm_peak
            new_map[k].last_mtm = self._positions[k].last_mtm

        opened = new_keys - old_keys
        closed = old_keys - new_keys

        for k in opened:
            p = new_map[k]
            await self._subscribe(p)
            sym = p.trading_symbol or p.security_id
            self._emit(
                Event(
                    event_type=EventType.POSITION_CHANGE,
                    severity=Severity.INFO,
                    security_id=p.security_id,
                    underlying=p.underlying,
                    title=f"opened {sym}",
                    message=f"New position: {p.net_qty:+d} {sym} @ {p.avg_price:.1f}",
                    payload={
                        "qty": p.net_qty,
                        "avg": p.avg_price,
                        "strike": p.strike,
                        "option_type": p.option_type,
                    },
                    dedup_key=f"{k}:opened",
                )
            )
        for k in closed:
            p = self._positions[k]
            self._emit(
                Event(
                    event_type=EventType.POSITION_CHANGE,
                    severity=Severity.INFO,
                    security_id=p.security_id,
                    underlying=p.underlying,
                    title=f"closed {p.trading_symbol or p.security_id}",
                    message=f"Position closed: {p.trading_symbol or p.security_id}",
                    payload={"last_mtm": round(p.last_mtm, 0)},
                    dedup_key=f"{k}:closed",
                )
            )

        self._positions = new_map

    async def _subscribe(self, pos: MonitoredPosition) -> None:
        if self._adapter is None:
            return
        try:
            async with self._session_maker() as session:
                await self._adapter.subscribe(pos.security_id, pos.exchange_segment, session)
                spot = UNDERLYING_MAP.get(pos.underlying.upper())
                if spot is not None:
                    await self._adapter.subscribe(str(spot[0]), spot[1], session)
        except Exception as exc:
            log.warning("position_subscribe_failed", security_id=pos.security_id, exc=str(exc))
