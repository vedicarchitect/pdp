"""Options chain background poller."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import httpx
import polars as pl
import structlog

from pdp.options import analytics, dhan_client, greeks

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection

    from pdp.options.hub import OptionsHub
    from pdp.settings import Settings

log = structlog.get_logger()

# Market hours in IST
_MARKET_OPEN = (9, 15)
_MARKET_CLOSE = (15, 35)

_MAX_EXPIRIES = 3


def _ist_now() -> datetime:
    import zoneinfo
    tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    return datetime.now(tz)


def _in_market_hours() -> bool:
    now = _ist_now()
    open_h, open_m = _MARKET_OPEN
    close_h, close_m = _MARKET_CLOSE
    start = now.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
    end = now.replace(hour=close_h, minute=close_m, second=0, microsecond=0)
    return start <= now <= end


def _parse_chain(raw: dict, underlying: str, risk_free_rate: float) -> list[dict]:
    """Convert Dhan optionchain response into list of strike dicts with Greeks."""
    data = raw.get("data", raw)
    spot = float(data.get("last_price", data.get("lastPrice", 0)) or 0)
    oc_data = data.get("oc", data.get("optionChain", {}))

    # Build flat list of strikes
    rows: list[dict] = []
    for strike_str, sides in oc_data.items():
        try:
            strike = float(strike_str)
        except ValueError:
            continue
        ce = sides.get("CE") or sides.get("ce") or {}
        pe = sides.get("PE") or sides.get("pe") or {}
        rows.append(
            {
                "strike": strike,
                "ce_ltp": float(ce.get("last_price", ce.get("lastPrice", 0)) or 0),
                "pe_ltp": float(pe.get("last_price", pe.get("lastPrice", 0)) or 0),
                "ce_oi": int(ce.get("oi", ce.get("openInterest", 0)) or 0),
                "pe_oi": int(pe.get("oi", pe.get("openInterest", 0)) or 0),
                "ce_volume": int(ce.get("volume", 0) or 0),
                "pe_volume": int(pe.get("volume", 0) or 0),
                # expiry comes from the Dhan response per strike
                "expiry": ce.get("expiry_date", ce.get("expiryDate", "")),
            }
        )

    if not rows:
        return []

    # Determine nearest expiry dates present
    expiry_dates: list[str] = sorted({r["expiry"] for r in rows if r["expiry"]})[:_MAX_EXPIRIES]

    result: list[dict] = []
    for expiry_str in expiry_dates:
        expiry_rows = [r for r in rows if r["expiry"] == expiry_str]
        try:
            expiry_date = date.fromisoformat(expiry_str)
        except ValueError:
            continue

        df = pl.DataFrame(
            {
                "strike": [r["strike"] for r in expiry_rows],
                "ce_ltp": [r["ce_ltp"] for r in expiry_rows],
                "pe_ltp": [r["pe_ltp"] for r in expiry_rows],
            }
        )
        df_with_greeks = greeks.compute_greeks(df, spot, expiry_date, risk_free_rate)

        for i, r in enumerate(expiry_rows):
            row_greeks = df_with_greeks.row(i, named=True)
            result.append(
                {
                    "expiry": expiry_str,
                    "strike": r["strike"],
                    "ce": {
                        "ltp": r["ce_ltp"],
                        "oi": r["ce_oi"],
                        "volume": r["ce_volume"],
                        "iv": float(row_greeks["ce_iv"]),
                        "delta": float(row_greeks["ce_delta"]),
                        "gamma": float(row_greeks["ce_gamma"]),
                        "theta": float(row_greeks["ce_theta"]),
                        "vega": float(row_greeks["ce_vega"]),
                    },
                    "pe": {
                        "ltp": r["pe_ltp"],
                        "oi": r["pe_oi"],
                        "volume": r["pe_volume"],
                        "iv": float(row_greeks["pe_iv"]),
                        "delta": float(row_greeks["pe_delta"]),
                        "gamma": float(row_greeks["pe_gamma"]),
                        "theta": float(row_greeks["pe_theta"]),
                        "vega": float(row_greeks["pe_vega"]),
                    },
                }
            )

    return result


class OptionsChainPoller:
    def __init__(
        self,
        collection: AsyncIOMotorCollection,  # type: ignore[type-arg]
        hub: OptionsHub,
        settings: Settings,
    ) -> None:
        self._col = collection
        self._hub = hub
        self._settings = settings
        self._underlyings: list[str] = json.loads(settings.OPTIONS_UNDERLYINGS)
        self._poll_interval = settings.OPTIONS_POLL_INTERVAL_SECONDS
        self._risk_free = settings.OPTIONS_RISK_FREE_RATE
        self._refresh_queue: asyncio.Queue[str] = asyncio.Queue()
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="options-poller")
        log.info("options_poller_started", underlyings=self._underlyings, interval=self._poll_interval)

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("options_poller_stopped")

    def request_refresh(self, underlying: str) -> None:
        try:
            self._refresh_queue.put_nowait(underlying.upper())
        except asyncio.QueueFull:
            pass

    async def _run(self) -> None:
        async with httpx.AsyncClient(timeout=15.0) as http:
            while not self._stop_event.is_set():
                # Drain on-demand refresh queue
                on_demand: list[str] = []
                while not self._refresh_queue.empty():
                    try:
                        on_demand.append(self._refresh_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                targets = list(dict.fromkeys(on_demand + (self._underlyings if _in_market_hours() else [])))
                for underlying in targets:
                    await self._poll_one(underlying, http)

                try:
                    await asyncio.wait_for(
                        asyncio.shield(self._stop_event.wait()),
                        timeout=self._poll_interval,
                    )
                    break
                except TimeoutError:
                    pass

    async def _poll_one(self, underlying: str, http: httpx.AsyncClient) -> None:
        try:
            raw = await dhan_client.fetch_chain(
                underlying,
                self._settings.DHAN_ACCESS_TOKEN,
                self._settings.DHAN_CLIENT_ID,
                httpx_client=http,
            )
        except Exception as exc:
            log.warning("options_chain_fetch_error", underlying=underlying, exc=str(exc))
            return

        all_strikes = _parse_chain(raw, underlying, self._risk_free)
        if not all_strikes:
            log.warning("options_chain_empty", underlying=underlying)
            return

        # Group by expiry and write one doc per expiry
        expiries: dict[str, list[dict]] = {}
        for s in all_strikes:
            expiries.setdefault(s["expiry"], []).append(s)

        spot = float((raw.get("data", raw)).get("last_price", raw.get("data", raw).get("lastPrice", 0)) or 0)
        snapshot_ts = datetime.now(UTC)

        for expiry_str, strike_list in expiries.items():
            doc = {
                "underlying": underlying,
                "expiry": expiry_str,
                "snapshot_ts": snapshot_ts,
                "spot_price": spot,
                "max_pain": analytics.compute_max_pain(strike_list),
                "pcr": analytics.compute_pcr(strike_list),
                "strikes": strike_list,
            }
            try:
                await self._col.insert_one(doc)
            except Exception as exc:
                log.warning(
                    "options_chain_insert_error",
                    underlying=underlying,
                    expiry=expiry_str,
                    exc=str(exc),
                )
                continue

            self._hub.broadcast(underlying, expiry_str, doc)
            log.info(
                "options_chain_stored",
                underlying=underlying,
                expiry=expiry_str,
                n_strikes=len(strike_list),
            )
