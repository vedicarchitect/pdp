"""Options chain background poller."""
from __future__ import annotations

import asyncio
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


def _spot_of(raw: dict) -> float:
    data = raw.get("data", raw)
    return float(data.get("last_price", data.get("lastPrice", 0)) or 0)


def _dhan_side(side: dict) -> dict:
    """Extract a CE/PE side from Dhan's raw payload, using Dhan greeks if present.

    Dhan reports ``implied_volatility`` in percent; we store it as a decimal to match
    the vollib convention. ``iv``/greeks are ``None`` when Dhan omits them so the
    caller can fall back to vollib.
    """
    g = side.get("greeks") or {}
    iv_raw = side.get("implied_volatility")
    has_greeks = all(g.get(k) is not None for k in ("delta", "gamma", "theta", "vega"))
    iv = float(iv_raw) / 100.0 if iv_raw not in (None, "") else None
    return {
        "ltp": float(side.get("last_price", side.get("lastPrice", 0)) or 0),
        "oi": int(side.get("oi", side.get("openInterest", 0)) or 0),
        "volume": int(side.get("volume", 0) or 0),
        "iv": iv,
        "delta": float(g["delta"]) if has_greeks else None,
        "gamma": float(g["gamma"]) if has_greeks else None,
        "theta": float(g["theta"]) if has_greeks else None,
        "vega": float(g["vega"]) if has_greeks else None,
    }


def _parse_chain(raw: dict, underlying: str, risk_free_rate: float) -> list[dict]:
    """Convert a single-expiry Dhan optionchain response into strike dicts.

    Expects the canonical shape from ``dhan_client.fetch_chain``:
    ``{"data": {"last_price": ..., "oc": {"<strike>": {"ce": {...}, "pe": {...}}}},
       "expiry": "<ISO>"}``. Prefers Dhan-provided IV/greeks per side and falls back
    to vollib only for sides Dhan did not supply.
    """
    data = raw.get("data", raw)
    expiry_str = raw.get("expiry", "")
    spot = _spot_of(raw)
    oc_data = data.get("oc", data.get("optionChain", {})) or {}

    rows: list[dict] = []
    for strike_str, sides in oc_data.items():
        try:
            strike = float(strike_str)
        except (ValueError, TypeError):
            continue
        ce = _dhan_side(sides.get("ce") or sides.get("CE") or {})
        pe = _dhan_side(sides.get("pe") or sides.get("PE") or {})
        rows.append({"strike": strike, "ce": ce, "pe": pe})

    if not rows:
        return []

    rows.sort(key=lambda r: r["strike"])

    # Fallback: compute vollib greeks once if any side is missing Dhan values.
    needs_fallback = any(
        r["ce"]["delta"] is None or r["ce"]["iv"] is None
        or r["pe"]["delta"] is None or r["pe"]["iv"] is None
        for r in rows
    )
    fallback = None
    if needs_fallback:
        try:
            expiry_date = date.fromisoformat(expiry_str)
        except ValueError:
            expiry_date = None
        if expiry_date is not None:
            df = pl.DataFrame(
                {
                    "strike": [r["strike"] for r in rows],
                    "ce_ltp": [r["ce"]["ltp"] for r in rows],
                    "pe_ltp": [r["pe"]["ltp"] for r in rows],
                }
            )
            fallback = greeks.compute_greeks(df, spot, expiry_date, risk_free_rate)

    result: list[dict] = []
    for i, r in enumerate(rows):
        fb = fallback.row(i, named=True) if fallback is not None else None
        result.append(
            {
                "expiry": expiry_str,
                "strike": r["strike"],
                "ce": _merge_side(r["ce"], fb, "ce"),
                "pe": _merge_side(r["pe"], fb, "pe"),
            }
        )
    return result


def _merge_side(side: dict, fallback_row: dict | None, prefix: str) -> dict:
    """Use Dhan values where present, else the vollib fallback row (else 0)."""
    def pick(key: str) -> float:
        if side[key] is not None:
            return float(side[key])
        if fallback_row is not None:
            return float(fallback_row[f"{prefix}_{key}"])
        return 0.0

    return {
        "ltp": side["ltp"],
        "oi": side["oi"],
        "volume": side["volume"],
        "iv": pick("iv"),
        "delta": pick("delta"),
        "gamma": pick("gamma"),
        "theta": pick("theta"),
        "vega": pick("vega"),
    }


# Public re-exports: CLI commands and other consumers should import these names
# rather than relying on the underscore-prefixed originals.
parse_chain = _parse_chain
spot_of = _spot_of


class OptionsChainPoller:
    def __init__(
        self,
        collection: AsyncIOMotorCollection,  # type: ignore[type-arg]
        hub: OptionsHub,
        settings: Settings,
        underlyings: list[str],
    ) -> None:
        self._col = collection
        self._hub = hub
        self._settings = settings
        self._underlyings: list[str] = underlyings
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
            expiries = await dhan_client.fetch_expiries(
                underlying,
                self._settings.DHAN_ACCESS_TOKEN,
                self._settings.DHAN_CLIENT_ID,
            )
        except Exception as exc:
            log.warning("options_expiry_fetch_error", underlying=underlying, exc=str(exc))
            return

        if not expiries:
            log.warning("options_expiry_empty", underlying=underlying)
            return

        for idx, expiry_str in enumerate(expiries[:_MAX_EXPIRIES]):
            if idx > 0:
                # Honour Dhan's 1-request-per-3-seconds option-chain rate limit.
                await asyncio.sleep(3)
            await self._poll_expiry(underlying, expiry_str)

    async def _poll_expiry(self, underlying: str, expiry_str: str) -> None:
        try:
            raw = await dhan_client.fetch_chain(
                underlying,
                expiry_str,
                self._settings.DHAN_ACCESS_TOKEN,
                self._settings.DHAN_CLIENT_ID,
            )
        except Exception as exc:
            log.warning(
                "options_chain_fetch_error",
                underlying=underlying,
                expiry=expiry_str,
                exc=str(exc),
            )
            return

        strike_list = _parse_chain(raw, underlying, self._risk_free)
        if not strike_list:
            log.warning("options_chain_empty", underlying=underlying, expiry=expiry_str)
            return

        doc = {
            "underlying": underlying,
            "expiry": expiry_str,
            "snapshot_ts": datetime.now(UTC),
            "spot_price": _spot_of(raw),
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
            return

        self._hub.broadcast(underlying, expiry_str, doc)
        log.info(
            "options_chain_stored",
            underlying=underlying,
            expiry=expiry_str,
            n_strikes=len(strike_list),
        )
